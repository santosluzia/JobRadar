"""Relatório por e-mail (HTML + texto), com idempotência por vaga.

Seleção (a mesma regra do filtro "Ontem e hoje" da tela de vagas do portfólio):
- do dia: relevantes, publicadas a partir de 00:00 de ontem (São Paulo) e ainda não enviadas;
- encontradas atrasadas: relevantes, vistas pela 1ª vez nesse mesmo período, mas publicadas antes
  (a fonte demorou a mostrar a vaga, ou a empresa entrou agora na coleta). Sem essa seção elas
  nunca seriam enviadas.
"Ainda não enviada" faz cada turno (a cada 6 h: 00, 06, 12, 18 em SP) levar só o que os anteriores
não levaram: a vaga publicada hoje às 10h entra no e-mail das 12:00 e não volta nos seguintes.

Layout: cartões completos para as `cartoes` de maior score do dia; o resto em lista compacta.
`max_vagas` protege contra o corte do Gmail (~100 KB de HTML); o excedente é avisado no rodapé
e NÃO é registrado.

Visual: o mesmo do portfólio (santosluzia.com): marinho da logo LS no cabeçalho, fundo branco
com toque violeta, destaques em violeta e os três pixels da logo. Só tabelas e estilos inline,
que é o que os clientes de e-mail respeitam; as fontes do site (Fraunces, Inter, IBM Plex Mono)
aparecem no Apple Mail e caem para Georgia/Arial/monoespaçada nos demais.

Idempotência: o registro meta/notifications guarda (job_id, canal). Uma vaga só é enviada
uma vez por canal, mesmo que o workflow seja reexecutado. Se o envio falhar, nada é
registrado e a vaga volta a ser candidata na próxima execução (dentro do período).
"""
from __future__ import annotations

import html
import json
import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any

import pandas as pd

from ..analytics.selection import FUSO, inicio_periodo, publicadas_no_periodo, relevantes
from ..settings import Settings
from ..storage import Lake

log = logging.getLogger(__name__)
CANAL = "email"
PERIODO = "ontem_e_hoje"
DO_DIA, ATRASADA = "do_dia", "atrasada"
# Rótulos separados: "nao_informada" existe nas duas colunas e antes virava "Modalidade n/i" na senioridade.
MODALIDADE = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial", "nao_informada": "Modalidade n/i"}
SENIORIDADE = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "estagio": "Estágio",
               "lideranca": "Liderança", "nao_informada": "Senioridade n/i"}
FONTE = {"gupy": "Gupy", "adzuna": "Adzuna", "greenhouse": "Greenhouse", "lever": "Lever"}

# Tela pública com todas as vagas (mesmo contrato v1 que este pipeline publica).
URL_VAGAS = "https://santosluzia.com/vagas-engenharia-de-dados"
URL_PROJETO = "https://github.com/santosluzia/JobRadar"

# Paleta da logo LS, a mesma de src/styles.css do portfólio.
MARINHO, PAPEL, VIOLETA, VIOLETA_VIVO = "#0c1330", "#f6f5fd", "#5b3df5", "#8466ff"
TEXTO_SUAVE, LINHA, LILAS, ALERTA = "#5b5e86", "#dcd8f3", "#ebe9fa", "#b3261e"
COR_FONTE = {"gupy": "#38bdf8", "adzuna": "#e879f9", "greenhouse": "#22c55e", "lever": "#f59e0b"}
SERIF = "Fraunces,Georgia,serif"
SANS = "Inter,Arial,Helvetica,sans-serif"
MONO = "'IBM Plex Mono',Menlo,Consolas,monospace"
DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


@dataclass
class Candidata:
    job: dict[str, Any]
    score: int
    explicacao: list[dict]
    lacunas: list[dict]
    sem_evidencia: list[dict]
    requisitos: list[str]
    secao: str = DO_DIA


def selecionar(s: Settings, agora: datetime) -> tuple[list[Candidata], int]:
    """Vagas do e-mail (do dia por score, depois atrasadas por data) e quantas ficaram de fora por max_vagas."""
    lake = Lake(s.lake)
    jobs, skills = lake.read("silver/jobs"), lake.read("silver/job_skills")
    if jobs.empty:
        return [], 0
    cfg = s.sources.get("notificacoes", {})
    mask = relevantes(jobs, skills, s.filtros, agora, int(s.sources["busca"].get("max_dias_publicacao", 30)))
    ja = set(lake.read("meta/notifications").query("canal == @CANAL")["job_id"])
    mask &= ~jobs["job_id"].isin(ja)
    do_dia = publicadas_no_periodo(jobs, PERIODO, agora)
    primeira = pd.to_datetime(jobs["primeira_observacao"], utc=True)
    atrasada = ~do_dia & (primeira >= inicio_periodo(PERIODO, agora)) if cfg.get("incluir_atrasadas", True) \
        else pd.Series(False, index=jobs.index)
    jobs = jobs.assign(secao=None)
    jobs.loc[do_dia, "secao"] = DO_DIA
    jobs.loc[atrasada, "secao"] = ATRASADA
    sel = jobs[mask & (do_dia | atrasada)].merge(lake.read("gold/job_scores"), on="job_id", how="left")
    sel = sel[sel["score"].fillna(0) >= int(s.filtros.get("score_minimo", 0))]
    sel["_pub"] = pd.to_datetime(sel["publicada_em"], utc=True, errors="coerce")
    sel = pd.concat([sel[sel["secao"] == DO_DIA].sort_values(["score", "_pub"], ascending=[False, False]),
                     sel[sel["secao"] == ATRASADA].sort_values(["_pub", "score"], ascending=[False, False])])
    limite = int(cfg.get("max_vagas", 130))
    excedentes = max(len(sel) - limite, 0)
    sel = sel.head(limite).drop(columns="_pub")
    sel = sel.astype(object).where(sel.notna(), None)  # NaN do pandas → None
    req = skills[skills["importancia"] == "requisito"].groupby("job_id")["skill_id"].apply(list).to_dict()
    return [Candidata(j, int(j["score"]), json.loads(j["explicacao"] or "[]"), json.loads(j["lacunas"] or "[]"),
                      json.loads(j["sem_evidencia"] or "[]"), sorted(req.get(j["job_id"], [])), j["secao"])
            for j in sel.to_dict("records")], excedentes


def candidatas(s: Settings, agora: datetime) -> list[Candidata]:
    return selecionar(s, agora)[0]


def _ts(v: Any) -> pd.Timestamp | None:
    if v is None or pd.isna(v):
        return None
    return pd.Timestamp(v).tz_convert(FUSO)


def _data(v: Any) -> str:
    t = _ts(v)
    return t.strftime("%d/%m/%Y") if t is not None else "não informada"


def _data_hora(v: Any) -> str:
    t = _ts(v)
    return t.strftime("%d/%m %H:%M") if t is not None else "data n/i"


# ---------- peças do HTML ----------

def _pixels() -> str:
    """Os três pixels em escada da logo LS (tabela, para funcionar em qualquer cliente)."""
    q = "width:6px;height:6px;font-size:0;line-height:0"
    return (f'<table role="presentation" cellspacing="0" cellpadding="0" style="display:inline-table;'
            f'vertical-align:middle;margin-right:8px"><tr><td style="{q}"></td><td style="{q}"></td>'
            f'<td style="{q};background:{VIOLETA}"></td></tr><tr><td style="{q}"></td>'
            f'<td style="{q};background:{VIOLETA_VIVO}"></td><td style="{q}"></td></tr><tr>'
            f'<td style="{q}"></td><td style="{q}"></td><td style="{q};background:{VIOLETA}"></td></tr></table>')


def _etiqueta(texto: str, fundo: str = LILAS, cor: str = MARINHO, borda: str | None = None) -> str:
    b = f"border:1px solid {borda};" if borda else ""
    return (f'<span style="display:inline-block;margin:0 4px 4px 0;padding:3px 9px;border-radius:999px;'
            f'background:{fundo};{b}color:{cor};font-size:12px;line-height:16px">'
            f'{html.escape(texto)}</span>')


def _fonte(source: str) -> str:
    cor = COR_FONTE.get(source, VIOLETA_VIVO)
    return (f'<span style="display:inline-block;width:8px;height:8px;border-radius:4px;background:{cor};'
            f'margin-right:5px;vertical-align:middle"></span>{html.escape(FONTE.get(source, source))}')


def _cartao(i: int, v: Candidata, nomes: dict[str, str]) -> tuple[str, list[str]]:
    e, j = html.escape, v.job
    url = e(j["url"], quote=True)
    local = j.get("cidade") or j.get("uf") or ""
    if j.get("cidade") and j.get("uf"):
        local = f"{j['cidade']}, {j['uf']}"
    etiquetas = "".join(_etiqueta(x) for x in [local, MODALIDADE.get(j["modalidade"], ""),
                                                SENIORIDADE.get(j["senioridade"], "")] if x)
    req = [nomes.get(k, k) for k in v.requisitos]
    gaps = ", ".join(nomes.get(x["skill_id"], x["skill_id"]) for x in v.lacunas if x["importancia"] == "requisito")
    sem = ", ".join(nomes.get(x["skill_id"], x["skill_id"]) for x in v.sem_evidencia if x["importancia"] == "requisito")
    crit = " · ".join(f"{c['criterio']} {c['pontos']:g}/{c['maximo']}" for c in v.explicacao if c["criterio"] != "penalidade")
    fonte = FONTE.get(j["source"], j["source"])
    competencias = ("".join(_etiqueta(n, "#ede9ff", VIOLETA) for n in req) if req
                    else f'<span style="color:{TEXTO_SUAVE};font-size:13px">nenhuma identificada</span>')
    cartao = f"""
<tr><td style="padding:0 20px 14px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff;border:1px solid {LINHA};border-radius:14px">
<tr><td style="padding:18px 20px">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
    <td style="font-family:{MONO};font-size:12px;color:{TEXTO_SUAVE}">{i:02d} &nbsp;·&nbsp; {_fonte(j["source"])}</td>
    <td align="right" style="font-family:{MONO};font-size:12px;color:{VIOLETA};white-space:nowrap">
      <span style="display:inline-block;padding:3px 9px;border-radius:999px;background:{LILAS}">aderência <b>{v.score}</b>/100</span></td>
  </tr></table>
  <div style="margin:10px 0 4px;font-family:{SERIF};font-size:19px;line-height:25px;font-weight:600">
    <a href="{url}" style="color:{MARINHO};text-decoration:none">{e(j['titulo'])}</a></div>
  <div style="font-size:14px;color:{MARINHO};opacity:.85;margin-bottom:10px">{e(j.get("empresa") or "Empresa não informada")}</div>
  <div>{etiquetas}</div>
  <div style="font-family:{MONO};font-size:12px;color:{TEXTO_SUAVE};margin:6px 0 12px">publicada {_data_hora(j.get('publicada_em'))} &nbsp;·&nbsp; coletada {_data(j.get('primeira_observacao'))}</div>
  <div style="font-family:{MONO};font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{TEXTO_SUAVE};margin-bottom:6px">Competências pedidas</div>
  <div>{competencias}</div>
  {f'<div style="font-size:13px;margin-top:8px;color:{ALERTA}"><b>Lacunas:</b> {e(gaps)}</div>' if gaps else ''}
  {f'<div style="font-size:13px;margin-top:4px;color:{TEXTO_SUAVE}"><b>Sem evidência no perfil:</b> {e(sem)}</div>' if sem else ''}
  {f'<div style="font-family:{MONO};font-size:11px;color:{TEXTO_SUAVE};margin-top:8px">{e(crit)}</div>' if crit else ''}
  <table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:16px"><tr>
    <td style="border-radius:10px;background:{VIOLETA}"><a href="{url}" style="display:inline-block;padding:11px 18px;font-size:14px;font-weight:600;color:#ffffff;text-decoration:none">Abrir vaga para se candidatar &nbsp;↗</a></td>
  </tr></table>
</td></tr></table>
</td></tr>"""
    texto = [f"{i}. {j['titulo']} — {j.get('empresa') or 'empresa n/i'} ({MODALIDADE.get(j['modalidade'], '')}) · {fonte}",
             f"   Score {v.score}/100 · publicada {_data_hora(j.get('publicada_em'))} · "
             f"requisitos: {', '.join(req) or 'nenhuma identificada'}",
             f"   Lacunas: {gaps or '-'} · Sem evidência: {sem or '-'}", f"   {j['url']}", ""]
    return cartao, texto


def _linha(v: Candidata, ultima: bool = False) -> tuple[str, str]:
    """Uma linha por vaga: título com link e os dados essenciais. Enxuta para caber muitas no e-mail."""
    e, j = html.escape, v.job
    meta = " · ".join(x for x in [j.get("empresa") or "empresa n/i", j.get("cidade") or j.get("uf") or "",
                                  MODALIDADE.get(j["modalidade"], "") if j["modalidade"] != "nao_informada" else "",
                                  SENIORIDADE.get(j["senioridade"], "") if j["senioridade"] != "nao_informada" else "",
                                  _data_hora(j.get("publicada_em")), f"aderência {v.score}"] if x)
    borda = "" if ultima else f"border-bottom:1px solid {LILAS};"
    cor = COR_FONTE.get(j["source"], VIOLETA_VIVO)
    linha = (f'<tr><td style="padding:11px 18px;{borda}">'
             f'<a href="{e(j["url"], quote=True)}" style="color:{MARINHO};font-size:14px;font-weight:600;'
             f'text-decoration:none">{e(j["titulo"])}</a><br>'
             f'<span style="font-size:12px;color:{TEXTO_SUAVE}"><span style="color:{cor}">●</span> '
             f'{e(FONTE.get(j["source"], j["source"]))} · {e(meta)}</span></td></tr>')
    texto_meta = f"{FONTE.get(j['source'], j['source'])} · {meta}"
    return linha, f"- {j['titulo']} — {texto_meta}\n  {j['url']}"


def _titulo_secao(texto: str, nota: str = "") -> str:
    n = (f'<div style="font-size:12px;color:{TEXTO_SUAVE};margin-top:4px;'
         f'text-transform:none;letter-spacing:0">{html.escape(nota)}</div>') if nota else ""
    return (f'<tr><td style="padding:22px 20px 10px;font-family:{MONO};font-size:11px;font-weight:600;'
            f'letter-spacing:.16em;text-transform:uppercase;color:{VIOLETA}">'
            f'<span style="display:inline-block;width:7px;height:7px;background:{VIOLETA};margin-right:8px;'
            f'vertical-align:middle"></span>{html.escape(texto)}{n}</td></tr>')


def _lista(linhas: list[str]) -> str:
    """Agrupa as linhas compactas num bloco branco arredondado, como os cartões."""
    return (f'<tr><td style="padding:0 20px 6px"><table role="presentation" width="100%" cellspacing="0" '
            f'cellpadding="0" style="background:#ffffff;border:1px solid {LINHA};border-radius:14px">'
            f'{"".join(linhas)}</table></td></tr>')


def _saude(fontes: list[dict[str, Any]]) -> str:
    itens = []
    for f in fontes:
        ok = f["status_ultima_execucao"] == "ok"
        cor = "#16a34a" if ok else ALERTA
        itens.append(f'<span style="display:inline-block;margin:0 10px 4px 0;white-space:nowrap">'
                     f'<span style="color:{cor}">●</span> {html.escape(FONTE.get(f["fonte"], f["fonte"]))} '
                     f'{"ok" if ok else html.escape(str(f["status_ultima_execucao"]))}</span>')
    return "".join(itens) or "sem execuções"


def renderizar(vagas: list[Candidata], agora: datetime, nomes: dict[str, str],
               fontes: list[dict[str, Any]], cartoes: int = 10, excedentes: int = 0) -> tuple[str, str, str]:
    e = html.escape
    local = agora.astimezone(FUSO)
    dia = local.strftime("%d/%m/%Y")
    hoje = pd.Timestamp(agora).tz_convert(FUSO).normalize()
    do_dia = [v for v in vagas if v.secao == DO_DIA]
    atrasadas = [v for v in vagas if v.secao == ATRASADA]
    if do_dia:
        assunto = f"JobRadar {dia}: {len(do_dia)} vaga(s) publicada(s) ontem e hoje"
        manchete = f"{len(do_dia)} vaga{'s' if len(do_dia) > 1 else ''} publicada{'s' if len(do_dia) > 1 else ''} ontem e hoje"
    else:
        assunto = f"JobRadar {dia}: nenhuma vaga nova publicada ontem ou hoje"
        manchete = "Nenhuma vaga nova publicada ontem ou hoje"
    if atrasadas:
        assunto += f" + {len(atrasadas)} encontrada(s) agora"

    linhas, texto = [], [assunto, ""]
    destaque, resto = do_dia[:cartoes], do_dia[cartoes:]
    if destaque:
        linhas.append(_titulo_secao(f"As {len(destaque)} com maior aderência"))
        texto.append(f"== As {len(destaque)} com maior aderência ==")
        for i, v in enumerate(destaque, 1):
            c, t = _cartao(i, v, nomes)
            linhas.append(c)
            texto += t
    # "Do dia" sempre tem data de publicação (é o critério da seção).
    resto.sort(key=lambda v: _ts(v.job["publicada_em"]), reverse=True)
    de_hoje = [v for v in resto if _ts(v.job["publicada_em"]) >= hoje]
    de_ontem = [v for v in resto if _ts(v.job["publicada_em"]) < hoje]
    for grupo, rotulo, nota in ((de_hoje, "Demais publicadas hoje", ""), (de_ontem, "Demais publicadas ontem", ""),
                                (atrasadas, "Encontradas agora, publicadas antes",
                                 "A fonte demorou a mostrar estas vagas, ou a empresa entrou agora na coleta.")):
        if not grupo:
            continue
        linhas.append(_titulo_secao(f"{rotulo} ({len(grupo)})", nota))
        texto += ["", f"== {rotulo} ({len(grupo)}) =="]
        bloco = []
        for k, v in enumerate(grupo):
            h, t = _linha(v, ultima=k == len(grupo) - 1)
            bloco.append(h)
            texto.append(t)
        linhas.append(_lista(bloco))
    if not vagas:
        linhas.append(f'<tr><td style="padding:22px 20px;font-size:14px;line-height:21px;'
                      f'color:{MARINHO}">Nenhuma vaga nova acima do score mínimo publicada ontem ou hoje. '
                      f'As fontes foram consultadas normalmente (veja abaixo).</td></tr>')

    # Texto de prévia na caixa de entrada (fica oculto no corpo).
    primeira = (do_dia or atrasadas or [None])[0]
    previa = (f"Destaque: {primeira.job['titulo']} — {primeira.job.get('empresa') or 'empresa n/i'}"
              if primeira else "As fontes foram consultadas; nenhuma vaga nova hoje.")
    aviso = (f'<b style="color:{MARINHO}">Mais {excedentes} vaga(s) não couberam neste e-mail</b>; '
             f'veja todas em <a href="{URL_VAGAS}" style="color:{VIOLETA}">santosluzia.com</a>.<br><br>'
             if excedentes else "")
    corpo = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{e(assunto)}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&amp;family=Inter:wght@400;600&amp;family=IBM+Plex+Mono:wght@400;600&amp;display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:{PAPEL};color:{MARINHO};font-family:{SANS};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{PAPEL}">{e(previa)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{PAPEL}"><tr><td align="center" style="padding:0">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;font-family:{SANS}">
<tr><td style="padding:28px 24px 26px;background:{MARINHO};background-image:radial-gradient(circle at 100% 0%,rgba(132,102,255,.45),rgba(12,19,48,0) 60%)">
  <div style="font-family:{MONO};font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:{VIOLETA_VIVO}">{_pixels()}JobRadar · Engenharia de Dados</div>
  <div style="margin-top:14px;font-family:{SERIF};font-size:28px;line-height:33px;font-weight:600;color:{PAPEL}">{e(manchete)}</div>
  <div style="margin-top:8px;font-size:14px;color:#e2e1f6">{DIAS_SEMANA[local.weekday()].capitalize()}, {dia} · horário de São Paulo{f" · mais {len(atrasadas)} encontrada(s) agora" if atrasadas else ""}</div>
  <table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:18px"><tr>
    <td style="border:1px solid rgba(226,225,246,.35);border-radius:999px"><a href="{URL_VAGAS}" style="display:inline-block;padding:9px 16px;font-size:13px;color:{PAPEL};text-decoration:none">Ver todas as vagas no portfólio &nbsp;→</a></td>
  </tr></table>
</td></tr>
<tr><td style="height:6px;font-size:0;line-height:0">&nbsp;</td></tr>
{''.join(linhas)}
<tr><td style="padding:22px 24px 30px;font-size:12px;line-height:19px;color:{TEXTO_SUAVE}">
  {aviso}<div style="margin-bottom:8px"><span style="font-family:{MONO};letter-spacing:.12em;text-transform:uppercase;font-size:11px">Fontes</span><br>{_saude(fontes)}</div>
  Datas no horário de São Paulo. O score mede compatibilidade com o seu perfil; não é probabilidade de contratação.
  "Sem evidência" significa que a competência não está registrada no perfil, não que você não a tenha.
  <div style="margin-top:16px;padding-top:14px;border-top:1px solid {LINHA}">
    <a href="{URL_VAGAS}" style="color:{VIOLETA};text-decoration:none;font-weight:600">santosluzia.com</a> &nbsp;·&nbsp;
    <a href="{URL_PROJETO}" style="color:{TEXTO_SUAVE}">como o JobRadar funciona</a></div>
</td></tr></table>
</td></tr></table></body></html>"""
    if excedentes:
        texto += ["", f"Mais {excedentes} vaga(s) não couberam neste e-mail; veja todas em {URL_VAGAS}"]
    saude_txt = " | ".join(f"{f['fonte']}: {f['status_ultima_execucao']}" for f in fontes) or "sem execuções"
    texto += ["", f"Fontes: {saude_txt}", f"Todas as vagas: {URL_VAGAS}"]
    return assunto, corpo, "\n".join(texto)


def enviar_smtp(s: Settings, assunto: str, corpo_html: str, corpo_texto: str) -> None:
    host, user, pwd = s.env("SMTP_HOST"), s.env("SMTP_USER"), s.env("SMTP_PASSWORD")
    para = s.env("EMAIL_TO")
    if not (host and user and pwd and para):
        raise RuntimeError("defina SMTP_HOST, SMTP_USER, SMTP_PASSWORD e EMAIL_TO (ou use --dry-run)")
    porta = int(s.env("SMTP_PORT") or 587)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = assunto, s.env("EMAIL_FROM") or user, para
    msg.set_content(corpo_texto)
    msg.add_alternative(corpo_html, subtype="html")
    ctx = ssl.create_default_context()
    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=ctx, timeout=30) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=30) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(user, pwd)
            smtp.send_message(msg)


def registrar(lake: Lake, vagas: list[Candidata], run_id: str, agora: datetime) -> None:
    lake.append("meta/notifications", pd.DataFrame(
        [{"job_id": v.job["job_id"], "canal": CANAL, "enviada_em": agora, "run_id": run_id} for v in vagas]))

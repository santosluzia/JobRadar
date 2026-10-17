"""Relatório diário por e-mail (HTML + texto), com idempotência por vaga.

Seleção (a mesma regra da tela Vagas, filtro "Ontem e hoje"):
- do dia: relevantes, publicadas a partir de 00:00 de ontem (São Paulo) e ainda não enviadas;
- encontradas atrasadas: relevantes, vistas pela 1ª vez nesse mesmo período, mas publicadas antes
  (a fonte demorou a mostrar a vaga, ou a empresa entrou agora na coleta). Sem essa seção elas
  nunca seriam enviadas.
"Ainda não enviada" cobre o horário do e-mail (06:47): a vaga publicada hoje às 10h é coletada
amanhã, quando já é "de ontem", e entra uma única vez.

Layout: cartões completos para as `cartoes` de maior score do dia; o resto em lista compacta.
`max_vagas` protege contra o corte do Gmail (~100 KB de HTML); o excedente é avisado no rodapé
e NÃO é registrado.

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
ROTULO = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial", "nao_informada": "Modalidade n/i",
          "junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "estagio": "Estágio",
          "lideranca": "Liderança"}
FONTE = {"gupy": "Gupy", "adzuna": "Adzuna", "greenhouse": "Greenhouse", "lever": "Lever"}


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
    limite = int(cfg.get("max_vagas", 150))
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


def _cartao(i: int, v: Candidata, nomes: dict[str, str]) -> tuple[str, list[str]]:
    e, j = html.escape, v.job
    local = j.get("cidade") or j.get("uf") or ""
    meta = " · ".join(x for x in [e(j.get("empresa") or "Empresa não informada"), ROTULO.get(j["modalidade"], ""),
                                  e(local), ROTULO.get(j["senioridade"], "")] if x)
    req = ", ".join(nomes.get(k, k) for k in v.requisitos) or "nenhuma identificada"
    gaps = ", ".join(nomes.get(x["skill_id"], x["skill_id"]) for x in v.lacunas if x["importancia"] == "requisito")
    sem = ", ".join(nomes.get(x["skill_id"], x["skill_id"]) for x in v.sem_evidencia if x["importancia"] == "requisito")
    crit = "; ".join(f"{c['criterio']} {c['pontos']:g}/{c['maximo']}" for c in v.explicacao if c["criterio"] != "penalidade")
    fonte = FONTE.get(j["source"], j["source"])
    cartao = f"""
<tr><td style="padding:16px 20px;border-bottom:1px solid #e7e2d6">
  <div style="font-size:12px;color:#8a8170">{i:02d} · Score de aderência <b style="color:#1c1a17">{v.score}</b>/100 · {e(fonte)}</div>
  <div style="font-size:17px;font-weight:600;margin:4px 0 2px"><a href="{e(j['url'], quote=True)}" style="color:#1c1a17;text-decoration:none">{e(j['titulo'])}</a></div>
  <div style="font-size:14px;color:#4a453c">{meta}</div>
  <div style="font-size:13px;color:#4a453c;margin-top:8px">Publicada: {_data_hora(j.get('publicada_em'))} · Coletada: {_data(j.get('primeira_observacao'))}</div>
  <div style="font-size:13px;margin-top:6px"><b>Competências pedidas:</b> {e(req)}</div>
  {f'<div style="font-size:13px;margin-top:4px;color:#9a3412"><b>Lacunas:</b> {e(gaps)}</div>' if gaps else ''}
  {f'<div style="font-size:13px;margin-top:4px;color:#6b6457"><b>Sem evidência no perfil:</b> {e(sem)}</div>' if sem else ''}
  <div style="font-size:12px;color:#8a8170;margin-top:6px">{e(crit)}</div>
  <div style="margin-top:10px"><a href="{e(j['url'], quote=True)}" style="display:inline-block;background:#1c1a17;color:#f5f1e8;padding:8px 14px;border-radius:6px;text-decoration:none;font-size:13px">Abrir vaga para se candidatar</a></div>
</td></tr>"""
    texto = [f"{i}. {j['titulo']} — {j.get('empresa') or 'empresa n/i'} ({ROTULO.get(j['modalidade'], '')}) · {fonte}",
             f"   Score {v.score}/100 · publicada {_data_hora(j.get('publicada_em'))} · requisitos: {req}",
             f"   Lacunas: {gaps or '-'} · Sem evidência: {sem or '-'}", f"   {j['url']}", ""]
    return cartao, texto


def _linha(v: Candidata) -> tuple[str, str]:
    """Uma linha por vaga: título com link e os dados essenciais. Enxuta para caber muitas no e-mail."""
    e, j = html.escape, v.job
    meta = " · ".join(x for x in [j.get("empresa") or "empresa n/i", j.get("cidade") or j.get("uf") or "",
                                  ROTULO.get(j["modalidade"], ""), ROTULO.get(j["senioridade"], ""),
                                  FONTE.get(j["source"], j["source"]), _data_hora(j.get("publicada_em")),
                                  f"score {v.score}"] if x)
    linha = (f'<tr><td style="padding:7px 20px;border-bottom:1px solid #eee;font-size:13px">'
             f'<a href="{e(j["url"], quote=True)}" style="color:#1c1a17;font-weight:600">{e(j["titulo"])}</a>'
             f'<br><span style="color:#6b6457;font-size:12px">{e(meta)}</span></td></tr>')
    return linha, f"- {j['titulo']} — {meta}\n  {j['url']}"


def _titulo_secao(texto: str, nota: str = "") -> str:
    n = f'<div style="font-size:12px;color:#8a8170;font-weight:400;margin-top:2px">{html.escape(nota)}</div>' if nota else ""
    return (f'<tr><td style="padding:18px 20px 6px;font-size:14px;font-weight:700;color:#1c1a17;'
            f'border-bottom:2px solid #c9a227">{html.escape(texto)}{n}</td></tr>')


def renderizar(vagas: list[Candidata], agora: datetime, nomes: dict[str, str],
               fontes: list[dict[str, Any]], cartoes: int = 10, excedentes: int = 0) -> tuple[str, str, str]:
    e = html.escape
    dia = agora.astimezone(FUSO).strftime("%d/%m/%Y")
    hoje = pd.Timestamp(agora).tz_convert(FUSO).normalize()
    do_dia = [v for v in vagas if v.secao == DO_DIA]
    atrasadas = [v for v in vagas if v.secao == ATRASADA]
    if do_dia:
        assunto = f"JobRadar {dia}: {len(do_dia)} vaga(s) publicada(s) ontem e hoje"
    else:
        assunto = f"JobRadar {dia}: nenhuma vaga nova publicada ontem ou hoje"
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
        for v in grupo:
            h, t = _linha(v)
            linhas.append(h)
            texto.append(t)
    if not vagas:
        linhas.append('<tr><td style="padding:20px">Nenhuma vaga nova acima do score mínimo publicada ontem ou hoje. '
                      'As fontes foram consultadas normalmente (veja abaixo).</td></tr>')

    saude = " | ".join(f"{f['fonte']}: {f['status_ultima_execucao']}" for f in fontes) or "sem execuções"
    aviso = (f"<b>Mais {excedentes} vaga(s) não couberam neste e-mail</b>; veja a tela Vagas do painel.<br>"
             if excedentes else "")
    corpo = f"""<!doctype html><html><body style="margin:0;background:#f5f1e8;font-family:Arial,Helvetica,sans-serif;color:#1c1a17">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:0 auto;background:#fffdf8">
<tr><td style="padding:20px;background:#1c1a17;color:#f5f1e8">
  <div style="font-size:12px;letter-spacing:.08em;color:#c9a227">JOBRADAR</div>
  <div style="font-size:20px;font-weight:600">{e(assunto)}</div></td></tr>
{''.join(linhas)}
<tr><td style="padding:16px 20px;font-size:12px;color:#8a8170">
  {aviso}Fontes: {e(saude)}<br>Datas no horário de São Paulo. O score mede compatibilidade com o seu perfil; não é probabilidade de contratação.
  "Sem evidência" significa que a competência não está registrada no perfil, não que você não a tenha.
</td></tr></table></body></html>"""
    if excedentes:
        texto += ["", f"Mais {excedentes} vaga(s) não couberam neste e-mail; veja a tela Vagas do painel."]
    texto += ["", f"Fontes: {saude}"]
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

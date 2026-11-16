"""JobRadar — Diagnóstico Mensal de Career Intelligence (Etapa 7): e-mail com as 7 perguntas.

No dia/turno configurado (`private/radar.yaml → mensal`): grava o retrato do mês de cada objetivo em
`private/diagnosticos_mensais` (sempre, mesmo com o e-mail desativado — é o histórico) e envia o e-mail.
Um retrato/e-mail por mês e objetivo. Não lê ~/.jobradar; o log só recebe contagens.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..analytics.selection import FUSO
from ..evolucao import mensal as m
from ..settings import Settings
from ..storage import Lake
from . import email as em
from .radar import RadarConfig, _caixa, carregar_config

PERGUNTAS = ["Minha aderência ao mercado melhorou?", "Quais competências desenvolvi?",
             "Quais lacunas continuam relevantes?", "O que mudou nas exigências das empresas?",
             "Quais projetos agregariam mais valor?", "Meu currículo está demonstrando melhor minhas experiências?",
             "Quais objetivos profissionais estão mais compatíveis com meu perfil?"]


def devido(cfg: RadarConfig, agora: datetime, turno: int, hist: pd.DataFrame) -> tuple[bool, str]:
    mc = cfg.mensal
    local = agora.astimezone(FUSO)
    if turno != mc.turno:
        return False, f"fora do horário do diagnóstico mensal ({mc.horario})"
    if local.day != mc.dia:
        return False, f"o diagnóstico mensal sai no dia {mc.dia}"
    if not hist.empty and ((hist["mes"] == m.mes_referencia(agora)) & hist["status"].isin(["enviado", "gerado"])).any():
        return False, "diagnóstico deste mês já gerado"
    return True, "ok"


def montar(s: Settings, agora: datetime, hist: pd.DataFrame) -> dict[str, Any]:
    from ..transformations.skills import Taxonomy
    lake = Lake(s.lake)
    nomes = {k.id: k.nome for k in Taxonomy(s.skills).skills}
    retratos = m.retrato(s, agora)
    eventos = lake.read("private/study_events")
    ok = hist[hist["status"].isin(["enviado", "gerado"])] if not hist.empty else hist
    diags = []
    for r in retratos:
        ant = ok[(ok["objetivo_id"] == r["objetivo_id"]) & (ok["mes"] < r["mes"])].sort_values("mes") if not ok.empty else ok
        anterior = json.loads(ant.iloc[-1]["retrato"]) if len(ant) else None
        diags.append(m.diagnostico(r, anterior, s.scoring["aderencia"]["evidencia"],
                                   s.scoring["curriculo"]["pesos_evidencia"], nomes, eventos,
                                   int(s.scoring["recomendacoes"]["min_vagas_janela"])))
    return {"mes": m.mes_referencia(agora), "retratos": retratos, "diagnosticos": diags,
            "objetivos": m.objetivos_compativeis(retratos), "aviso": m.AVISO}


def renderizar(r: dict[str, Any], agora: datetime, fontes: list[dict[str, Any]]) -> tuple[str, str, str]:
    e = html.escape
    assunto = f"JobRadar — Diagnóstico Mensal de Career Intelligence · {r['mes']}"
    L, T = [], [assunto, ""]
    for d in r["diagnosticos"]:
        L.append(em._titulo_secao(f"{d['objetivo']} · {d['vagas_mes']} vagas-alvo no mês",
                                  "amostra pequena: leia como indício" if d["amostra_pequena"] else ""))
        T.append(f"#### {d['objetivo']} ({d['vagas_mes']} vagas-alvo no mês)")
        q1 = d["q1_aderencia"]
        if q1.get("variacao") is not None:
            p1 = (f"Aderência do perfil: {q1['antes']} → <b>{q1['agora']}</b> ({q1['variacao']:+.1f}). "
                  f"Efeito do mercado {q1['efeito_mercado']:+.1f} · efeito do seu perfil {q1['efeito_perfil']:+.1f}.")
        else:
            p1 = f"Aderência do perfil no mês: <b>{q1['agora']}</b>. {e(q1.get('aviso', ''))}"
        q2 = d["q2_desenvolvidas"]
        p2 = ", ".join(f"{x['nome']} ({x['de']} → {x['para']})" for x in q2["niveis_que_subiram"]) or ""
        if q2["progresso_registrado"]:
            p2 += ("; " if p2 else "") + "progresso: " + ", ".join(f"{x['nome']} → {x['para'].replace('_', ' ')}"
                                                                    for x in q2["progresso_registrado"][-6:])
        q3 = d["q3_lacunas"]
        p3 = (", ".join(f"{x['nome']} ({x['pct']:.0f}%)" for x in q3["continuam"]) or "nenhuma persistente")
        if q3["resolvidas"]:
            p3 += f"; saíram: {', '.join(q3['resolvidas'])}"
        if q3["novas"]:
            p3 += f"; novas: {', '.join(q3['novas'])}"
        q4 = d["q4_exigencias"]
        p4 = q4.get("aviso") or "; ".join(x for x in (
            "subiram: " + ", ".join(f"{y['nome']} {y['delta_pp']:+.0f} p.p." for y in q4["subiram"]) if q4["subiram"] else "",
            "caíram: " + ", ".join(f"{y['nome']} {y['delta_pp']:+.0f} p.p." for y in q4["cairam"]) if q4["cairam"] else "",
            "novas: " + ", ".join(q4["novas"]) if q4["novas"] else "") if x) or "sem mudanças de 5 p.p. ou mais"
        p5 = "<br>".join(f"<b>{e(x['nome'])}:</b> {e(x['projeto'])}" for x in d["q5_projetos"]) or "sem prioridades com amostra"
        q6 = d["q6_curriculo"]
        p6 = q6.get("aviso") or (f"Aderência do currículo: {q6.get('aderencia_curriculo_antes', '—')} → "
                                 f"<b>{q6['aderencia_curriculo']}</b>; declaradas sem evidência: "
                                 f"{q6.get('declaradas_antes', '—')} → {q6['declaradas_sem_evidencia']}.")
        respostas = [p1, e(p2) or "nenhuma mudança registrada no mês", e(p3), e(p4), p5, p6]
        for k, (pergunta, resp) in enumerate(zip(PERGUNTAS[:6], respostas), 1):
            L.append(_caixa(f'<span style="font-family:{em.MONO};font-size:11px;color:{em.VIOLETA}">{k}. '
                            f"{e(pergunta)}</span><br>{resp}"))
            T += [f"{k}. {pergunta}", "   " + html.unescape(resp.replace("<br>", "\n   ").replace("<b>", "").replace("</b>", ""))]
    L.append(em._titulo_secao("7. Quais objetivos profissionais estão mais compatíveis com meu perfil?"))
    T.append("7. Quais objetivos profissionais estão mais compatíveis com meu perfil?")
    linhas = "<br>".join(f"{k}. <b>{e(o['objetivo'])}</b>: perfil {o['perfil']} · currículo {o['curriculo'] if o['curriculo'] is not None else '—'}"
                         f" · {o['vagas_mes']} vagas no mês{' (amostra pequena)' if o['amostra_pequena'] else ''}"
                         for k, o in enumerate(r["objetivos"], 1))
    L.append(_caixa(linhas))
    T.append(html.unescape(linhas.replace("<br>", "\n").replace("<b>", "").replace("</b>", "")))
    corpo = em.moldura(assunto, "Seu diagnóstico do mês: aderência, lacunas e o que mudou no mercado.",
                       "JobRadar · Career Intelligence", f"Diagnóstico mensal · {r['mes']}",
                       f"{len(r['diagnosticos'])} objetivo(s) · gerado em {agora.astimezone(FUSO):%d/%m/%Y}", L, fontes,
                       rodape=e(r["aviso"]))
    return assunto, corpo, "\n".join(T + ["", r["aviso"]])


def enviar(s: Settings, agora: datetime, run_id: str, turno: int | None = None, dry_run: bool = False,
           forcar: bool = False, html_out: Path | None = None) -> dict[str, Any]:
    from ..analytics import market
    from .radar import turno_de
    lake = Lake(s.lake)
    cfg = carregar_config(s.lake)
    hist = lake.read("private/diagnosticos_mensais")
    ok, motivo = devido(cfg, agora, turno_de(agora) if turno is None else turno, hist)
    if not ok and not forcar and not dry_run:
        return {"enviado": False, "gerado": False, "motivo": motivo}
    r = montar(s, agora, hist)
    assunto, corpo, texto = renderizar(r, agora, market.fontes(market.carregar(lake)))
    contagem = {"objetivos": len(r["diagnosticos"])}
    if dry_run:
        if html_out:
            Path(html_out).write_text(corpo, encoding="utf-8")
        return {"enviado": False, "gerado": False, "motivo": "prévia (dry-run): nada gravado nem enviado", **contagem}
    status, erro = "gerado", None
    if cfg.mensal.ativo:
        try:
            em.enviar_smtp(s, assunto, corpo, texto)
            status = "enviado"
        except Exception as ex:      # o retrato fica gravado mesmo assim (é histórico); o envio é tentado de novo
            status, erro = "falha", type(ex).__name__
    lake.append("private/diagnosticos_mensais", pd.DataFrame([
        {"mes": x["mes"], "objetivo_id": x["objetivo_id"], "gerado_em": agora, "run_id": run_id, "status": status,
         "retrato": json.dumps(x, ensure_ascii=False), "erro": erro} for x in r["retratos"]]))
    if status == "falha":
        raise RuntimeError(f"falha no envio do diagnóstico mensal ({erro}); retrato gravado")
    return {"enviado": status == "enviado", "gerado": True, "motivo": "ok", **contagem}

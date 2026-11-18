"""Saúde da operação (Etapa 8, monitoramento): indicadores agregados e alertas configuráveis.

Só lê tabelas operacionais e de mercado (meta/*, silver/jobs, silver/job_skills): nada pessoal. Por isso
a saída pode ir para o resumo do GitHub Actions (público) e para o rodapé do Radar.

Indicadores: tempo de execução, volume, taxa de falha (7 e 30 dias), custo de IA (zero: a camada
semântica é local e não há API paga), qualidade da extração por fonte, duplicação, qualidade dos
indicadores (registros inválidos, vagas sem data/empresa), validações (contrato, taxonomia), qualidade e
nota por fonte e mudança de formato das respostas (analytics/qualidade_fontes.py, ADR 0013).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..storage import Lake, utcnow

PADRAO = {
    "horas_sem_sucesso": 14,          # 4 execuções por dia: mais de 2 turnos sem sucesso é anormal
    "taxa_falha_7d_max_pct": 25,
    "duracao_max_s": 900,             # o job tem timeout de 20 min
    "cobertura_extracao_min_pct": 50, # % das vagas recentes da fonte com ao menos uma competência técnica
    "invalidos_max_pct": 10,
    "falhas_seguidas_fonte": 3,       # a mesma fonte falhou nas últimas N execuções
    "janela_extracao_dias": 30,
    "cobertura_extracao_min_pct_por_fonte": {},   # fontes com descrição truncada (Adzuna) têm régua própria
    "janela_qualidade_dias": 30,      # qualidade e nota por fonte (ADR 0013)
    "horas_alerta_formato": 24,       # mudança grave de formato fica em alerta por esse tempo
}
CUSTO_IA_USD = 0.0   # nenhuma chamada paga: extração por regras + embeddings locais (ADR 0002)


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return {**PADRAO, **{k: v for k, v in (cfg or {}).items() if k in PADRAO and v is not None}}


def _pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


def _metricas(linha: pd.Series) -> dict[str, Any]:
    try:
        return json.loads(linha["metricas"]) if isinstance(linha["metricas"], str) else {}
    except ValueError:
        return {}


def indicadores(lake: Lake, agora: datetime | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    c = _cfg(cfg)
    agora = pd.Timestamp(agora or utcnow())
    runs = lake.read("meta/runs").sort_values("iniciada_em")
    src = lake.read("meta/source_runs")
    saida: dict[str, Any] = {"gerado_em": agora.isoformat(), "custo_ia_usd": CUSTO_IA_USD}

    # execução
    ok = runs[runs["status"].isin(["sucesso", "parcial"])]
    ult = runs.iloc[-1] if not runs.empty else None
    ult_ok = ok.iloc[-1] if not ok.empty else None
    saida["execucao"] = {
        "total": int(len(runs)),
        "ultima_status": None if ult is None else ult["status"],
        "ultima_duracao_s": None if ult is None else float(ult["duracao_s"] or 0),
        "duracao_mediana_7d_s": _mediana(runs, agora, 7, "duracao_s"),
        "horas_desde_ultimo_sucesso": None if ult_ok is None
        else round((agora - pd.Timestamp(ult_ok["finalizada_em"])).total_seconds() / 3600, 1),
        "taxa_falha_7d_pct": _taxa_falha(runs, agora, 7),
        "taxa_falha_30d_pct": _taxa_falha(runs, agora, 30),
    }

    # volume e duplicação (última execução)
    m = _metricas(ult) if ult is not None else {}
    jobs = lake.read("silver/jobs")
    saida["volume"] = {"observadas_ultima": m.get("observadas"), "novas_ultima": m.get("novas"),
                       "vagas_no_historico": int(len(jobs))}
    saida["duplicacao"] = {
        "entre_fontes_ultima": m.get("duplicatas_entre_fontes"),
        "nao_canonicas_pct": _pct(int((~jobs["is_canonica"].fillna(True).astype(bool)).sum()), len(jobs)),
    }

    # qualidade dos dados de entrada (7 dias)
    s7 = src[pd.to_datetime(src["finalizada_em"], utc=True) >= agora - timedelta(days=7)]
    can = jobs[jobs["is_canonica"].fillna(True).astype(bool)]
    saida["qualidade"] = {
        "invalidos_7d_pct": _pct(s7["invalidos"].sum(), s7["coletados"].sum()),
        "sem_data_publicacao_pct": _pct(int(can["publicada_em"].isna().sum()), len(can)),
        "sem_empresa_pct": _pct(int(can["empresa"].isna().sum()), len(can)),
    }

    # extração por fonte (vagas canônicas vistas pela 1ª vez na janela)
    sk = lake.read("silver/job_skills")
    tecnicas = sk[sk["tipo"].isna() | (sk["tipo"] == "tecnica")]
    por_vaga = tecnicas.groupby("job_id")["skill_id"].nunique()
    janela = can[pd.to_datetime(can["primeira_observacao"], utc=True) >= agora - timedelta(days=c["janela_extracao_dias"])]
    extracao = []
    for fonte, g in janela.groupby("source"):
        n = por_vaga.reindex(g["job_id"]).fillna(0)
        extracao.append({"fonte": fonte, "vagas": int(len(g)), "com_competencia_pct": _pct(int((n > 0).sum()), len(g)),
                         "competencias_por_vaga": round(float(n.mean()), 1) if len(g) else None})
    saida["extracao_por_fonte"] = extracao

    # fontes: falhas seguidas
    seguidas = {}
    for fonte, g in src.sort_values("finalizada_em").groupby("source"):
        n = 0
        for v in reversed(g["ok"].tolist()):
            if bool(v):
                break
            n += 1
        seguidas[fonte] = n
    saida["fontes_falhas_seguidas"] = seguidas

    # validações (7 dias, só as públicas: contrato e taxonomia)
    val = lake.read("meta/validacoes")
    v7 = val[pd.to_datetime(val["em"], utc=True) >= agora - timedelta(days=7)]
    saida["validacoes"] = {"7d": int(len(v7)), "falhas_7d": int((~v7["ok"].astype(bool)).sum()),
                           "artefatos_com_falha": sorted(v7.loc[~v7["ok"].astype(bool), "artefato"].unique().tolist())}

    # qualidade por fonte e formato das respostas (ADR 0013)
    from . import qualidade_fontes as qf
    saida["qualidade_fontes"] = qf.por_fonte(lake, agora, c["janela_qualidade_dias"])
    saida["formato_fontes"] = qf.situacao_schema(lake, agora, c["horas_alerta_formato"])
    return saida


def _janela(runs: pd.DataFrame, agora: pd.Timestamp, dias: int) -> pd.DataFrame:
    return runs[pd.to_datetime(runs["iniciada_em"], utc=True) >= agora - timedelta(days=dias)]


def _mediana(runs, agora, dias, col) -> float | None:
    j = _janela(runs, agora, dias)
    return round(float(j[col].median()), 1) if not j.empty else None


def _taxa_falha(runs, agora, dias) -> float | None:
    j = _janela(runs, agora, dias)
    return _pct(int((j["status"] == "falha").sum()), len(j))


def alertas(ind: dict[str, Any], cfg: dict[str, Any] | None = None) -> list[str]:
    """Mensagens curtas e agregadas (sem dado pessoal); lista vazia = tudo normal."""
    c = _cfg(cfg)
    a: list[str] = []
    e = ind["execucao"]
    if e["total"] and (e["horas_desde_ultimo_sucesso"] is None or e["horas_desde_ultimo_sucesso"] > c["horas_sem_sucesso"]):
        a.append(f"sem execução bem-sucedida há mais de {c['horas_sem_sucesso']} h")
    if (e["taxa_falha_7d_pct"] or 0) > c["taxa_falha_7d_max_pct"]:
        a.append(f"taxa de falha em 7 dias: {e['taxa_falha_7d_pct']}%")
    if (e["ultima_duracao_s"] or 0) > c["duracao_max_s"]:
        a.append(f"última execução demorou {e['ultima_duracao_s']:.0f} s")
    if (ind["qualidade"]["invalidos_7d_pct"] or 0) > c["invalidos_max_pct"]:
        a.append(f"registros inválidos em 7 dias: {ind['qualidade']['invalidos_7d_pct']}%")
    for fonte, n in ind["fontes_falhas_seguidas"].items():
        if n >= c["falhas_seguidas_fonte"]:
            a.append(f"fonte {fonte} falhou nas últimas {n} execuções")
    for x in ind["extracao_por_fonte"]:
        minimo = (c["cobertura_extracao_min_pct_por_fonte"] or {}).get(x["fonte"], c["cobertura_extracao_min_pct"])
        if x["vagas"] >= 10 and (x["com_competencia_pct"] or 0) < minimo:
            a.append(f"extração fraca em {x['fonte']}: {x['com_competencia_pct']}% das vagas com competência")
    if ind["validacoes"]["falhas_7d"]:
        a.append("validação falhou em 7 dias: " + ", ".join(ind["validacoes"]["artefatos_com_falha"]))
    for f in ind.get("formato_fontes") or []:
        if f["grave_recente"]:
            a.append(f"formato da fonte {f['fonte']} mudou ({f['grave_recente']})")
    return a


def markdown(ind: dict[str, Any], al: list[str]) -> str:
    e, q = ind["execucao"], ind["qualidade"]
    linhas = ["### JobRadar — saúde da operação", "",
              "⚠️ **Alertas:** " + "; ".join(al) if al else "✅ Nenhum alerta.", "",
              "| Indicador | Valor |", "|---|---|",
              f"| Execuções (total) | {e['total']} |",
              f"| Última execução | {e['ultima_status']} em {e['ultima_duracao_s']} s (mediana 7d: {e['duracao_mediana_7d_s']} s) |",
              f"| Horas desde o último sucesso | {e['horas_desde_ultimo_sucesso']} |",
              f"| Taxa de falha 7d / 30d | {e['taxa_falha_7d_pct']}% / {e['taxa_falha_30d_pct']}% |",
              f"| Observadas / novas (última) | {ind['volume']['observadas_ultima']} / {ind['volume']['novas_ultima']} |",
              f"| Duplicatas entre fontes (última) | {ind['duplicacao']['entre_fontes_ultima']} |",
              f"| Registros inválidos 7d | {q['invalidos_7d_pct']}% |",
              f"| Vagas sem data / sem empresa | {q['sem_data_publicacao_pct']}% / {q['sem_empresa_pct']}% |",
              f"| Validações 7d (falhas) | {ind['validacoes']['7d']} ({ind['validacoes']['falhas_7d']}) |",
              f"| Custo de IA | US$ {ind['custo_ia_usd']:.2f} |", ""]
    if ind["extracao_por_fonte"]:
        linhas += ["| Fonte | Vagas (janela) | Com competência | Competências/vaga |", "|---|---|---|---|"]
        linhas += [f"| {x['fonte']} | {x['vagas']} | {x['com_competencia_pct']}% | {x['competencias_por_vaga']} |"
                   for x in ind["extracao_por_fonte"]]
    if ind.get("qualidade_fontes") or ind.get("formato_fontes"):
        from . import qualidade_fontes as qf
        linhas += ["", qf.markdown(ind.get("qualidade_fontes") or [], ind.get("formato_fontes") or [])]
    return "\n".join(linhas)

"""Indicadores de mercado calculados a partir da silver/gold.

Todas as funções devolvem também o tamanho da amostra: a base coletada NÃO representa
o mercado inteiro, só as fontes e os termos configurados.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..storage import Lake


@dataclass
class Snapshot:
    jobs: pd.DataFrame          # todas as vagas (inclusive duplicatas não canônicas)
    canonicas: pd.DataFrame
    skills: pd.DataFrame
    monthly: pd.DataFrame
    runs: pd.DataFrame
    source_runs: pd.DataFrame
    issues: pd.DataFrame
    scores: pd.DataFrame


def carregar(lake: Lake) -> Snapshot:
    jobs = lake.read("silver/jobs")
    return Snapshot(
        jobs=jobs,
        canonicas=jobs[jobs["is_canonica"].fillna(False)].copy(),
        skills=lake.read("silver/job_skills"),
        monthly=lake.read("gold/skill_monthly"),
        runs=lake.read("meta/runs"),
        source_runs=lake.read("meta/source_runs"),
        issues=lake.read("silver/quality_issues"),
        scores=lake.read("gold/job_scores"),
    )


def _contagem(serie: pd.Series) -> list[dict[str, Any]]:
    vc = serie.fillna("nao_informada").value_counts()
    total = int(vc.sum()) or 1
    return [{"valor": str(k), "vagas": int(v), "percentual": round(100 * v / total, 1)} for k, v in vc.items()]


def ultima_execucao_ok(snap: Snapshot) -> dict[str, Any] | None:
    ok = snap.runs[snap.runs["status"].isin(["sucesso", "parcial"])]
    if ok.empty:
        return None
    r = ok.sort_values("finalizada_em").iloc[-1]
    return {"run_id": r["run_id"], "status": r["status"], "finalizada_em": r["finalizada_em"]}


def fontes(snap: Snapshot) -> list[dict[str, Any]]:
    if snap.source_runs.empty:
        return []
    sr = snap.source_runs.sort_values("finalizada_em")
    saida = []
    for nome, g in sr.groupby("source"):
        ult = g.iloc[-1]
        ok = g[g["ok"]]
        saida.append({
            "fonte": nome,
            "status_ultima_execucao": "ok" if ult["ok"] else "erro",
            "ultima_coleta_ok": ok["finalizada_em"].iloc[-1] if not ok.empty else None,
            "registros_ultima_execucao": int(ult["coletados"]),
            "vagas_no_historico": int((snap.jobs["source"] == nome).sum()),
        })
    return saida


def resumo(snap: Snapshot, agora: datetime) -> dict[str, Any]:
    c = snap.canonicas
    primeira = pd.to_datetime(c["primeira_observacao"], utc=True)
    sr = snap.source_runs
    coletados = int(sr["coletados"].sum()) if not sr.empty else 0
    invalidos = int(sr["invalidos"].sum()) if not sr.empty else 0
    return {
        "totais": {
            "vagas_observadas": int(len(c)),
            "ativas": int((c["status"] == "ativa").sum()),
            "status_desconhecido": int((c["status"] == "desconhecida").sum()),
            "encerradas": int((c["status"] == "encerrada").sum()),
            "novas_7_dias": int((primeira >= agora - timedelta(days=7)).sum()),
            "novas_30_dias": int((primeira >= agora - timedelta(days=30)).sum()),
            "duplicatas_entre_fontes": int((~snap.jobs["is_canonica"].fillna(False)).sum()),
        },
        "por_modalidade": _contagem(c["modalidade"]),
        "por_senioridade": _contagem(c["senioridade"]),
        "por_familia": _contagem(c["familia"]),
        "por_fonte": _contagem(c["source"]),
        "por_uf": _contagem(c["uf"])[:10],
        "qualidade": {
            "execucoes": int(len(snap.runs)),
            "execucoes_com_falha": int((snap.runs["status"] == "falha").sum()),
            "registros_coletados": coletados,
            "registros_invalidos": invalidos,
            "taxa_invalidos_pct": round(100 * invalidos / coletados, 2) if coletados else None,
            "vagas_sem_data_publicacao_pct": round(100 * c["publicada_em"].isna().mean(), 1) if len(c) else None,
            "vagas_sem_empresa_pct": round(100 * c["empresa"].isna().mean(), 1) if len(c) else None,
        },
    }


def frequencia_competencias(snap: Snapshot, mascara: pd.Series | None = None, top: int | None = None) -> pd.DataFrame:
    """% de vagas (canônicas, no recorte) que citam cada competência."""
    base = snap.canonicas if mascara is None else snap.canonicas[mascara.reindex(snap.canonicas.index, fill_value=False)]
    n = len(base)
    cols = ["skill_id", "vagas", "vagas_requisito", "percentual", "percentual_requisito", "n"]
    if not n:
        return pd.DataFrame(columns=cols)
    sk = snap.skills[snap.skills["job_id"].isin(base["job_id"])]
    g = sk.groupby("skill_id").agg(vagas=("job_id", "nunique"),
                                   vagas_requisito=("importancia", lambda x: int((x == "requisito").sum())))
    g["percentual"] = (100 * g["vagas"] / n).round(1)
    g["percentual_requisito"] = (100 * g["vagas_requisito"] / n).round(1)
    g["n"] = n
    g = g.reset_index().sort_values(["vagas", "skill_id"], ascending=[False, True])
    return g.head(top) if top else g


def tendencias_mensais(snap: Snapshot, familias: list[str] | None = None,
                       senioridades: list[str] | None = None) -> pd.DataFrame:
    """Série mensal: % das vagas observadas no mês que citam cada competência."""
    m = snap.monthly
    if m.empty:
        return pd.DataFrame(columns=["mes", "skill_id", "vagas_com_skill", "total_vagas", "percentual"])
    if familias:
        m = m[m["familia"].isin(familias)]
    if senioridades:
        m = m[m["senioridade"].isin(senioridades)]
    totais = m[m["skill_id"] == "__total__"].groupby("mes")["total_vagas"].sum()
    s = m[m["skill_id"] != "__total__"].groupby(["mes", "skill_id"], as_index=False)[["vagas_com_skill", "vagas_requisito"]].sum()
    s["total_vagas"] = s["mes"].map(totais).astype("int64")
    s["percentual"] = (100 * s["vagas_com_skill"] / s["total_vagas"]).round(1)
    return s.sort_values(["mes", "vagas_com_skill"], ascending=[True, False])

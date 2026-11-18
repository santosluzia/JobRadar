"""Retrato da classificação do cargo (ADR 0014): subfamílias, idioma das vagas e idiomas exigidos.

Base: vagas canônicas vistas pela primeira vez na janela. Os percentuais de idioma exigido usam as vagas das
famílias de dados (`familias`); as subfamílias de `outra` aparecem à parte, como cargos adjacentes.
Sempre com n; `amostra_pequena` quando o denominador fica abaixo de 30.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

AMOSTRA_MIN = 30


def _pct(parte: int, total: int) -> float | None:
    return round(100 * parte / total, 1) if total else None


def resumo(jobs: pd.DataFrame, agora: datetime, familias: list[str], dias: int = 30) -> dict:
    base = jobs[jobs["is_canonica"].fillna(False)
                & (pd.to_datetime(jobs["primeira_observacao"], utc=True) >= agora - timedelta(days=dias))]
    dados = base[base["familia"].isin(familias)]
    n = len(dados)

    sub = (dados.groupby(["familia", dados["subfamilia"].fillna("nao_calculada")]).size()
           .rename("vagas").reset_index().sort_values(["familia", "vagas"], ascending=[True, False]))
    adj = base[(base["familia"] == "outra") & ~base["subfamilia"].fillna("fora_de_dados").isin(["fora_de_dados"])]

    exig = [json.loads(v) if isinstance(v, str) and v else [] for v in dados["idiomas_exigidos"]]
    def conta(pred) -> int:
        return sum(1 for lista in exig if any(pred(e) for e in lista))
    niveis = pd.Series([e["nivel"] for lista in exig for e in lista if e["idioma"] == "en"]).value_counts()
    return {
        "janela_dias": dias,
        "vagas_dados": n,
        "amostra_pequena": n < AMOSTRA_MIN,
        "subfamilias": [{"familia": r.familia, "subfamilia": r.subfamilia, "vagas": int(r.vagas),
                         "pct_familia": _pct(int(r.vagas), int((dados["familia"] == r.familia).sum()))}
                        for r in sub.itertuples()],
        "adjacentes": {k: int(v) for k, v in adj["subfamilia"].value_counts().items()},
        "idioma_vaga": {k: {"vagas": int(v), "pct": _pct(int(v), n)}
                        for k, v in dados["idioma_vaga"].fillna("nao_calculado").value_counts().items()},
        "exige_ingles_pct": _pct(conta(lambda e: e["idioma"] == "en"), n),
        "exige_ingles_requisito_pct": _pct(conta(lambda e: e["idioma"] == "en" and e["importancia"] == "requisito"), n),
        "exige_ingles_inferido_pct": _pct(conta(lambda e: e["idioma"] == "en" and e["origem"] == "idioma_da_vaga"), n),
        "exige_espanhol_pct": _pct(conta(lambda e: e["idioma"] == "es"), n),
        "nivel_ingles": {k: int(v) for k, v in niveis.items()},
    }


def markdown(r: dict) -> str:
    aviso = " · **amostra pequena**" if r["amostra_pequena"] else ""
    linhas = [f"## Classificação do cargo — últimos {r['janela_dias']} dias",
              f"{r['vagas_dados']} vagas das famílias de dados{aviso}", "",
              "| Família | Subfamília | Vagas | % da família |", "|---|---|---|---|"]
    linhas += [f"| {s['familia']} | {s['subfamilia']} | {s['vagas']} | {s['pct_familia']}% |" for s in r["subfamilias"]]
    if r["adjacentes"]:
        linhas += ["", "Cargos adjacentes (família `outra`, fora do escopo): "
                   + ", ".join(f"{k} {v}" for k, v in r["adjacentes"].items())]
    linhas += ["", "Idioma da vaga: " + ", ".join(f"{k} {v['vagas']} ({v['pct']}%)" for k, v in r["idioma_vaga"].items()),
               f"Exigem inglês: {r['exige_ingles_pct']}% (como requisito {r['exige_ingles_requisito_pct']}%; "
               f"só pelo idioma da vaga {r['exige_ingles_inferido_pct']}%) · espanhol: {r['exige_espanhol_pct']}%"]
    if r["nivel_ingles"]:
        linhas.append("Nível de inglês pedido: " + ", ".join(f"{k} {v}" for k, v in r["nivel_ingles"].items()))
    return "\n".join(linhas)

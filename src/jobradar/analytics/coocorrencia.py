"""Coocorrência de competências técnicas: "quem pede A também pede B?".

Base = vagas canônicas com AO MENOS UMA competência técnica extraída. Vaga sem nenhuma competência
(trecho curto da Adzuna, por exemplo) não informa nada sobre pares e só inflaria o lift.

Para um par (A, B), com n = vagas da base, nA, nB = vagas com A, com B, e nAB = vagas com os dois:

- suporte   = nAB / n                  quão comum é o par
- confiança = nAB / nA  (A→B)          assimétrica: "das vagas que pedem A, quantas pedem B"
- lift      = nAB·n / (nA·nB)          > 1: aparecem juntas mais do que se fossem independentes
- jaccard   = nAB / (nA + nB − nAB)    sobreposição simétrica

Tudo isso descreve ASSOCIAÇÃO na amostra coletada. Não diz que uma competência causa ou exige a
outra, nem que aprender A "leva" a B. A confiança vem com intervalo de Wilson de 95%, e pares ou
segmentos abaixo dos mínimos saem marcados como amostra pequena.

Mesma menção não é par: "Azure Data Factory" casa azure e data_factory, "PySpark" casa python e
spark, "Snowflake" casa snowflake e data_warehouse. Na vaga, o par só conta se A tiver alguma
menção que não esteja colada numa menção de B, ou vice-versa (posições em silver/job_skills).
"""
from __future__ import annotations

import json
import math
from itertools import combinations

import pandas as pd

COLUNAS_PARES = ["job_id", "skill_a", "skill_b", "ambos_requisito"]


def _spans(valor) -> list[tuple[int, int, int]]:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)) or valor == "":
        return []
    return [tuple(p) for p in json.loads(valor)]


def _colado(x: tuple[int, int, int], y: tuple[int, int, int]) -> bool:
    """Mesma frase e trechos sobrepostos ou separados por no máximo um caractere."""
    return x[0] == y[0] and max(x[1], y[1]) <= min(x[2], y[2]) + 1


def _independente(pa: list, pb: list) -> bool:
    """A tem alguma menção que não está colada em nenhuma menção de B? Sem posição registrada
    (linha antiga ou achado semântico), a menção é tratada como independente."""
    if not pa or not pb:
        return True
    return any(not any(_colado(x, y) for y in pb) for x in pa)


def pares_por_vaga(skills: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por vaga e par de competências (skill_a < skill_b) que conta como coocorrência."""
    if skills.empty:
        return pd.DataFrame(columns=COLUNAS_PARES)
    cols = ["job_id", "skill_id", "importancia"] + (["posicoes"] if "posicoes" in skills.columns else [])
    linhas = []
    for job_id, g in skills[cols].drop_duplicates(["job_id", "skill_id"]).groupby("job_id", sort=False):
        if len(g) < 2:
            continue
        itens = sorted((r.skill_id, r.importancia, _spans(getattr(r, "posicoes", None))) for r in g.itertuples())
        for (a, ia, pa), (b, ib, pb) in combinations(itens, 2):
            if _independente(pa, pb) or _independente(pb, pa):
                linhas.append((job_id, a, b, ia == "requisito" and ib == "requisito"))
    return pd.DataFrame(linhas, columns=COLUNAS_PARES)


def wilson(sucessos: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Intervalo de Wilson (95%) para uma proporção, em %. Mais honesto que ±1,96·EP com n pequeno."""
    if total <= 0:
        return None, None
    p = sucessos / total
    den = 1 + z * z / total
    centro = (p + z * z / (2 * total)) / den
    meia = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return round(100 * max(centro - meia, 0), 1), round(100 * min(centro + meia, 1), 1)


def metricas(contagem: pd.DataFrame, marginais: dict[str, int], base: int, min_par: int = 10,
             min_base: int = 30) -> pd.DataFrame:
    """`contagem`: skill_a, skill_b, vagas_par[, vagas_par_requisito]. `marginais`: vagas com cada
    competência. `base`: vagas com ao menos uma competência. Ordena por lift (desc)."""
    saida = []
    for r in contagem.itertuples():
        na, nb, nab = int(marginais.get(r.skill_a, 0)), int(marginais.get(r.skill_b, 0)), int(r.vagas_par)
        if not (na and nb and base):
            continue
        ab_lo, ab_hi = wilson(nab, na)
        ba_lo, ba_hi = wilson(nab, nb)
        saida.append({
            "skill_a": r.skill_a, "skill_b": r.skill_b, "vagas_par": nab,
            "vagas_par_requisito": int(getattr(r, "vagas_par_requisito", 0) or 0),
            "vagas_a": na, "vagas_b": nb, "base": base,
            "suporte_pct": round(100 * nab / base, 1),
            "confianca_a_b_pct": round(100 * nab / na, 1), "confianca_a_b_ic": [ab_lo, ab_hi],
            "confianca_b_a_pct": round(100 * nab / nb, 1), "confianca_b_a_ic": [ba_lo, ba_hi],
            "lift": round(nab * base / (na * nb), 2),
            "jaccard": round(nab / (na + nb - nab), 3),
            "amostra_pequena": nab < min_par or base < min_base,
        })
    if not saida:
        return pd.DataFrame(columns=["skill_a", "skill_b", "vagas_par", "vagas_par_requisito", "vagas_a", "vagas_b",
                                     "base", "suporte_pct", "confianca_a_b_pct", "confianca_a_b_ic",
                                     "confianca_b_a_pct", "confianca_b_a_ic", "lift", "jaccard", "amostra_pequena"])
    return pd.DataFrame(saida).sort_values(["amostra_pequena", "lift", "vagas_par"],
                                           ascending=[True, False, False]).reset_index(drop=True)


def janela(canonicas: pd.DataFrame, skills: pd.DataFrame, mascara: pd.Series, min_par: int = 10,
           min_base: int = 30) -> pd.DataFrame:
    """Coocorrência nas vagas canônicas selecionadas por `mascara` (ex.: famílias de dados, 90 dias).
    `skills` deve vir de analytics.market.competencias (só técnicas)."""
    ids = set(canonicas.loc[mascara, "job_id"])
    sk = skills[skills["job_id"].isin(ids)]
    pares = pares_por_vaga(sk)
    cont = (pares.groupby(["skill_a", "skill_b"]).agg(vagas_par=("job_id", "nunique"),
                                                      vagas_par_requisito=("ambos_requisito", "sum"))
            .reset_index()) if not pares.empty else pd.DataFrame(columns=["skill_a", "skill_b", "vagas_par"])
    marginais = sk.groupby("skill_id")["job_id"].nunique().to_dict()
    return metricas(cont, marginais, sk["job_id"].nunique(), min_par, min_base)


def relacionadas(tabela: pd.DataFrame, skill_id: str, incluir_amostra_pequena: bool = False) -> pd.DataFrame:
    """Do ponto de vista de uma competência: "das vagas que pedem X, quantas também pedem Y"."""
    linhas = []
    for r in tabela.to_dict("records"):
        if r["amostra_pequena"] and not incluir_amostra_pequena:
            continue
        if skill_id not in (r["skill_a"], r["skill_b"]):
            continue
        direto = r["skill_a"] == skill_id
        linhas.append({"skill_id": r["skill_b"] if direto else r["skill_a"], "vagas_par": r["vagas_par"],
                       "confianca_pct": r["confianca_a_b_pct"] if direto else r["confianca_b_a_pct"],
                       "confianca_ic": r["confianca_a_b_ic"] if direto else r["confianca_b_a_ic"],
                       "lift": r["lift"], "amostra_pequena": r["amostra_pequena"]})
    return pd.DataFrame(linhas, columns=["skill_id", "vagas_par", "confianca_pct", "confianca_ic", "lift",
                                         "amostra_pequena"]).sort_values(
        ["confianca_pct", "lift"], ascending=False).reset_index(drop=True)

"""Fila de curadoria: termos frequentes nas vagas de dados que a taxonomia ainda não cobre.

Determinístico e sem IA. Para não afogar a fila em palavras genéricas ("experiência", "empresa"),
compara a frequência nas vagas das famílias de dados com a frequência nas demais vagas (lift):
termo genérico aparece igual nos dois grupos; termo técnico de dados aparece muito mais no primeiro.

A fila só SUGERE. Quem decide é a pessoa: aprovar = acrescentar padrão/conceito em
config/skills.yaml (e subir a versão); recusar = acrescentar em `candidatas.ignorar`.
Lift aqui é associação entre termo e grupo de vagas, não causa de nada.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta

import pandas as pd

from ..transformations.skills import Taxonomy

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#/.-]*[a-z0-9+#]|[a-z]")
_TOKEN_ORIGINAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#/.-]*[A-Za-z0-9+#]|[A-Za-z]")


def _maiusculas(texto: str, total: Counter, maiusc: Counter) -> None:
    """Conta, por token, quantas vezes ele aparece com inicial maiúscula NO MEIO da frase:
    é o sinal de nome de ferramenta/produto ("SAP", "Qlik", "Dataform") × palavra comum."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    for k, tok in enumerate(_TOKEN_ORIGINAL.findall(sem_acento)):
        chave = tok.lower()
        total[chave] += 1
        if k > 0 and tok[0].isupper():
            maiusc[chave] += 1


def _ngramas(texto: str, stop: set[str], cobertos: re.Pattern, n_max: int = 3) -> set[str]:
    """N-gramas do texto SEM o que a taxonomia já reconhece ("data lake", "power bi"): assim
    "lake" ou "power" não viram candidatos só por serem parte de um termo coberto."""
    saida = set()
    for pedaco in cobertos.sub("|", texto).split("|"):   # sub: as regex têm grupos, split os devolveria
        toks = _TOKEN.findall(pedaco)
        for n in range(1, n_max + 1):
            for i in range(len(toks) - n + 1):
                g = toks[i:i + n]
                if g[0] in stop or g[-1] in stop or any(t.isdigit() for t in g) or len(" ".join(g)) < 3:
                    continue
                saida.add(" ".join(g))
    return saida


def candidatas(jobs: pd.DataFrame, tax: Taxonomy, familias: list[str], agora: datetime, dias: int = 90,
               min_vagas: int = 5, min_lift: float = 2.0, limite: int = 40, min_nome: float = 0.5) -> pd.DataFrame:
    cfg = tax.config.candidatas
    stop = set(cfg.stopwords)
    ignorar = re.compile("|".join(f"(?:{p})" for p in cfg.ignorar) or r"$^")
    cobertos = re.compile("|".join(f"(?:{p.pattern})" for s in tax.todas for p in (*s.padroes, *s.conceitos)))
    primeira = pd.to_datetime(jobs["primeira_observacao"], utc=True)
    base = jobs[jobs["is_canonica"].fillna(False) & jobs["descricao"].notna() & (primeira >= agora - timedelta(days=dias))]
    grupos = {"dados": base[base["familia"].isin(familias)], "outras": base[~base["familia"].isin(familias)]}
    freq: dict[str, Counter] = {}
    exemplo: dict[str, str] = {}
    total, maiusc = Counter(), Counter()
    for nome, g in grupos.items():
        c = Counter()
        for j in g.itertuples():
            vistos = set()
            for u in tax.unidades(j.titulo, j.descricao)[1:]:   # [0] é o título: cargo, não competência
                if u.modo == "contexto" or u.formacao:
                    continue
                novos = _ngramas(u.norm, stop, cobertos) - vistos
                if nome == "dados":
                    _maiusculas(u.original, total, maiusc)
                    for t in novos:
                        exemplo.setdefault(t, u.original)
                vistos |= novos
            c.update(vistos)
        freq[nome] = c
    n_d, n_o = max(len(grupos["dados"]), 1), max(len(grupos["outras"]), 1)
    linhas = []
    for termo, v in freq["dados"].items():
        if v < min_vagas or ignorar.search(termo):
            continue
        # pelo menos um token com cara de nome próprio (ferramenta, produto, sigla)
        if not any(total[tk] >= 3 and maiusc[tk] / total[tk] >= min_nome for tk in termo.split() if tk not in stop):
            continue
        lift = (v / n_d) / ((freq["outras"].get(termo, 0) + 1) / (n_o + 2))
        if lift >= min_lift:
            linhas.append({"termo": termo, "vagas": v, "pct_vagas_dados": round(100 * v / n_d, 1),
                           "lift": round(lift, 1), "exemplo": exemplo.get(termo, "")[:160]})
    if not linhas:
        return pd.DataFrame(columns=["termo", "vagas", "pct_vagas_dados", "lift", "exemplo"])
    df = pd.DataFrame(linhas)
    df["_ordem"] = df["vagas"] * df["lift"].map(math.log)
    # Um termo contido em outro, com frequência parecida, é redundante ("dataform" × "dataform no projeto").
    # Ordem determinística (empate → termo mais curto primeiro): o resultado não depende do hash das strings.
    df = df.assign(_tam=df["termo"].str.len()).sort_values(["_ordem", "_tam", "termo"], ascending=[False, True, True])
    mantidos: list[dict] = []
    for r in df.drop(columns="_tam").to_dict("records"):
        if any((r["termo"] in m["termo"] or m["termo"] in r["termo"])
               and min(m["vagas"], r["vagas"]) >= 0.8 * max(m["vagas"], r["vagas"]) for m in mantidos):
            continue
        mantidos.append(r)
        if len(mantidos) >= limite:
            break
    return pd.DataFrame(mantidos).drop(columns="_ordem").reset_index(drop=True)

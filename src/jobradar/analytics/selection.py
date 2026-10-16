"""Filtro de relevância (RF02): decide quais vagas vão para o e-mail e para jobs.json."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..transformations.text import normalizar


def relevantes(jobs: pd.DataFrame, skills: pd.DataFrame, filtros: dict[str, Any], agora: datetime,
               max_dias_publicacao: int = 30) -> pd.Series:
    """Máscara booleana. Vagas fora do filtro continuam no histórico e nas análises de mercado."""
    if jobs.empty:
        return pd.Series(dtype=bool)
    m = jobs["is_canonica"].fillna(False) & (jobs["status"] != "encerrada")
    if filtros.get("familias"):
        m &= jobs["familia"].isin(filtros["familias"])
    if filtros.get("senioridades"):
        m &= jobs["senioridade"].isin(filtros["senioridades"])
    if filtros.get("modalidades"):
        m &= jobs["modalidade"].isin(filtros["modalidades"])

    locais = filtros.get("locais") or {}
    ufs, cidades = set(locais.get("ufs") or []), {normalizar(c) for c in locais.get("cidades") or []}
    if ufs or cidades:
        cidade = jobs["cidade"].map(normalizar)
        local_ok = (jobs["modalidade"] == "remoto") | jobs["uf"].isna() & cidade.eq("") \
            | jobs["uf"].isin(ufs) | cidade.isin(cidades)
        m &= local_ok

    pub = pd.to_datetime(jobs["publicada_em"], utc=True)
    m &= pub.isna() | (pub >= agora - timedelta(days=max_dias_publicacao))

    texto = (jobs["titulo"].fillna("") + " " + jobs["descricao"].fillna("")).map(normalizar)
    excl = [normalizar(p) for p in filtros.get("palavras_excludentes") or [] if p]
    if excl:
        m &= ~jobs["titulo"].fillna("").map(normalizar).str.contains("|".join(excl), regex=True)
    obrig = [normalizar(p) for p in filtros.get("palavras_obrigatorias") or [] if p]
    if obrig:
        m &= texto.str.contains("|".join(obrig), regex=True)
    tecs = set(filtros.get("tecnologias_interesse") or [])
    if tecs and filtros.get("exigir_tecnologia_interesse"):
        com_tec = set(skills.loc[skills["skill_id"].isin(tecs), "job_id"])
        m &= jobs["job_id"].isin(com_tec)
    return m.fillna(False)

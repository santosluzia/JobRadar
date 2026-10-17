"""Filtro de relevância (RF02): decide quais vagas vão para o e-mail e para jobs.json.
Também o recorte por data de publicação, compartilhado entre a tela Vagas e o e-mail."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ..transformations.text import normalizar

FUSO = ZoneInfo("America/Sao_Paulo")
# Dias de calendário (em São Paulo) contados para trás a partir de hoje; None = sem recorte.
PERIODOS: dict[str, int | None] = {"hoje": 0, "ontem_e_hoje": 1, "7_dias": 6, "30_dias": 29, "qualquer_data": None}


def inicio_periodo(periodo: str, agora: datetime) -> datetime | None:
    """Meia-noite (São Paulo) do primeiro dia do período. Ex.: ontem_e_hoje → 00:00 de ontem."""
    dias = PERIODOS[periodo]
    if dias is None:
        return None
    hoje = agora.astimezone(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    return hoje - timedelta(days=dias)


def publicadas_no_periodo(jobs: pd.DataFrame, periodo: str, agora: datetime) -> pd.Series:
    """Máscara booleana. Vaga sem data de publicação só entra em 'qualquer_data'."""
    inicio = inicio_periodo(periodo, agora)
    if inicio is None:
        return pd.Series(True, index=jobs.index)
    pub = pd.to_datetime(jobs["publicada_em"], utc=True, errors="coerce")
    return (pub >= inicio).fillna(False)


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

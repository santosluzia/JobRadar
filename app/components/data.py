"""Acesso aos dados para o painel (cache curto; o lake é a única fonte)."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from jobradar.analytics import market
from jobradar.scoring import Profile
from jobradar.settings import Settings, carregar
from jobradar.storage import Lake
from jobradar.transformations.skills import Taxonomy


@st.cache_resource
def settings() -> Settings:
    return carregar(lake=os.getenv("JOBRADAR_LAKE"))


@st.cache_data(ttl=60, show_spinner=False)
def _snapshot(lake_path: str, _versao: float) -> market.Snapshot:
    return market.carregar(Lake(Path(lake_path)))


def snapshot() -> market.Snapshot:
    s = settings()
    marcador = s.lake / "meta" / "runs.parquet"
    return _snapshot(str(s.lake), marcador.stat().st_mtime if marcador.exists() else 0.0)


def lake() -> Lake:
    return Lake(settings().lake)


def taxonomia() -> Taxonomy:
    return Taxonomy(settings().skills)


def perfil() -> Profile:
    return Profile.from_dict(settings().profile)


def nomes() -> dict[str, str]:
    return {k.id: k.nome for k in taxonomia().skills}


def estado_vazio() -> bool:
    snap = snapshot()
    if snap.runs.empty:
        st.info(
            "**Ainda não há dados no histórico.**\n\n"
            "1. Clone o repositório privado `jobradar-data` ao lado deste projeto.\n"
            "2. Defina `JOBRADAR_LAKE` no `.env` apontando para ele.\n"
            "3. Rode `jobradar run` (ou espere a execução diária do GitHub Actions e dê `git pull`).\n\n"
            f"Pasta lida agora: `{settings().lake}`"
        )
        return True
    return False


BADGE = {
    "observado": ("#1f6f43", "Dado observado"),
    "inferido": ("#8a6d1f", "Inferido pelo sistema"),
    "recomendacao": ("#4b3f8f", "Recomendação gerada"),
}


def badge(tipo: str) -> None:
    cor, texto = BADGE[tipo]
    st.markdown(f"<span style='background:{cor};color:#fff;padding:2px 8px;border-radius:10px;"
                f"font-size:0.75rem'>{texto}</span>", unsafe_allow_html=True)

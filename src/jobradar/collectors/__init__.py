"""Registro dos coletores: liga/desliga por config, sem alterar o pipeline."""
from __future__ import annotations

import logging

from ..empresas.catalogo import carregar_catalogo
from ..settings import Settings
from .adzuna import AdzunaCollector
from .ats import COLETORES_ATS, AshbyCollector, GreenhouseCollector, LeverCollector, SmartRecruitersCollector
from .base import Collector, CollectResult
from .gupy import GupyCollector

log = logging.getLogger(__name__)

__all__ = ["Collector", "CollectResult", "build_collectors", "GupyCollector", "AdzunaCollector",
           "GreenhouseCollector", "LeverCollector", "AshbyCollector", "SmartRecruitersCollector"]


def build_collectors(s: Settings) -> list[Collector]:
    coletores: list[Collector] = []
    if s.fonte("gupy").get("ativo"):
        coletores.append(GupyCollector(s.fonte("gupy")))
    if s.fonte("adzuna").get("ativo"):
        app_id, app_key = s.env("ADZUNA_APP_ID"), s.env("ADZUNA_APP_KEY")
        if app_id and app_key:
            coletores.append(AdzunaCollector(s.fonte("adzuna"), app_id, app_key))
        else:
            log.info("adzuna ativa no config, mas sem ADZUNA_APP_ID/ADZUNA_APP_KEY — ignorada")
    catalogo = carregar_catalogo(s.empresas)   # inválido = erro: a coleta não roda com catálogo quebrado
    for nome, cls in COLETORES_ATS.items():
        cfg = dict(s.fonte(nome))
        # Catálogo (empresas ativas) + lista antiga em sources.yaml, se houver; sem repetir quadro.
        cfg["empresas"] = list(dict.fromkeys([*catalogo.quadros_ativos(nome), *(cfg.get("empresas") or [])]))
        # Nome de exibição do catálogo: usado quando a API não informa a empresa (Ashby)
        cfg["nomes"] = {e.board: e.nome for e in catalogo.empresas if e.ats == nome and e.board}
        if cfg.get("ativo") and cfg["empresas"]:
            coletores.append(cls(cfg))
    return coletores

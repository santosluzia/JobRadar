"""Registro dos coletores: liga/desliga por config, sem alterar o pipeline."""
from __future__ import annotations

import logging

from ..settings import Settings
from .adzuna import AdzunaCollector
from .ats import GreenhouseCollector, LeverCollector
from .base import Collector, CollectResult
from .gupy import GupyCollector

log = logging.getLogger(__name__)

__all__ = ["Collector", "CollectResult", "build_collectors", "GupyCollector", "AdzunaCollector",
           "GreenhouseCollector", "LeverCollector"]


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
    for nome, cls in (("greenhouse", GreenhouseCollector), ("lever", LeverCollector)):
        cfg = s.fonte(nome)
        if cfg.get("ativo") and cfg.get("empresas"):
            coletores.append(cls(cfg))
    return coletores

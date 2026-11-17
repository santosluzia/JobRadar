"""Coletores de ATS (sistemas de recrutamento) com API pública por empresa.

Um módulo por plataforma; as regras de quadro inteiro, filtro por título e métricas por quadro ficam em
`comum.py`. As empresas consultadas vêm do catálogo (`config/empresas.yaml`, pacote `jobradar.empresas`).
"""
from .ashby import AshbyCollector
from .greenhouse import GreenhouseCollector
from .lever import LeverCollector
from .smartrecruiters import SmartRecruitersCollector

# Plataforma (valor de `ats` no catálogo) → coletor
COLETORES_ATS = {"greenhouse": GreenhouseCollector, "lever": LeverCollector, "ashby": AshbyCollector,
                 "smartrecruiters": SmartRecruitersCollector}

__all__ = ["AshbyCollector", "COLETORES_ATS", "GreenhouseCollector", "LeverCollector", "SmartRecruitersCollector"]

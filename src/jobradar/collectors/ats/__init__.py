"""Coletores de ATS (sistemas de recrutamento) com API pública por empresa.

Um módulo por plataforma; as regras de quadro inteiro, filtro por título e métricas por quadro ficam em
`comum.py`. As empresas consultadas vêm do catálogo (`config/empresas.yaml`, pacote `jobradar.empresas`).
"""
from .greenhouse import GreenhouseCollector
from .lever import LeverCollector

__all__ = ["GreenhouseCollector", "LeverCollector"]

"""Empresas monitoradas: catálogo curado (`config/empresas.yaml`) e situação da coleta por empresa."""
from .catalogo import COLETORES, Catalogo, Empresa, carregar_catalogo
from .situacao import situacao

__all__ = ["COLETORES", "Catalogo", "Empresa", "carregar_catalogo", "situacao"]

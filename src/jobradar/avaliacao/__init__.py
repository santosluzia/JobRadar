"""Avaliação da extração de competências contra um conjunto-ouro anotado por pessoa.

O conjunto-ouro vive no repositório PRIVADO (`<lake>/avaliacao/conjunto_ouro.yaml`): guarda o
texto das vagas (conteúdo de terceiros) e as anotações. Só métricas agregadas saem daqui.
"""
from .ouro import (CAMINHO_OURO, ClassificacaoOuro, ConjuntoOuro, IdiomaOuro, ItemOuro, amostrar,
                   amostrar_classificacao, carregar_ouro, salvar_ouro)
from .metricas import Metricas, avaliar, relatorio

__all__ = ["CAMINHO_OURO", "ClassificacaoOuro", "ConjuntoOuro", "IdiomaOuro", "ItemOuro", "Metricas", "amostrar",
           "amostrar_classificacao", "avaliar", "carregar_ouro", "relatorio", "salvar_ouro"]

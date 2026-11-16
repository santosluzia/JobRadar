"""Análise PRIVADA do currículo (Etapa 3): leitura local, estruturação por regras, versões,
diagnóstico por objetivo e sugestões fundamentadas.

Privacidade: tudo aqui roda na sua máquina e grava só em `$JOBRADAR_HOME` (padrão `~/.jobradar`),
fora de qualquer repositório git. O pipeline do CI e a publicação NÃO importam este pacote
(há teste garantindo isso). Decisões: docs/adr/0003-curriculo-privado.md.
"""
from .estrutura import Achado, Curriculo, Experiencia, Item, interpretar, reaplicar_edicoes
from .leitura import ArquivoInvalido, TextoCurriculo, ler

__all__ = ["Achado", "ArquivoInvalido", "Curriculo", "Experiencia", "Item", "TextoCurriculo", "interpretar",
           "ler", "reaplicar_edicoes"]

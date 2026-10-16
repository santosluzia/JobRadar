"""Mecanismo de entrega dos dados. Hoje: JSON estático. Amanhã, se houver requisito: uma API REST
que reutiliza analytics/ e storage/ sem tocar nos coletores e transformações."""
from .contract import SCHEMA_VERSION, schemas
from .exporter import ContractError, construir, exportar_schemas, publicar, validar

__all__ = ["SCHEMA_VERSION", "schemas", "construir", "validar", "publicar", "exportar_schemas", "ContractError"]

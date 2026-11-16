"""Resultado das validações por execução (Etapa 8, rastreabilidade): `meta/validacoes`.

Cada linha diz o que foi validado (contrato público, taxonomia, perfil, configuração do Radar), em qual
versão, se passou e quantos erros. O detalhe é curto e mascarado (nunca leva dado pessoal nem segredo):
para o perfil, só a quantidade de erros e o primeiro campo com problema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .seguranca import mascarar
from .storage import Lake, utcnow


PRIVADOS = {"perfil", "radar_config"}


def registrar(lake: Lake, run_id: str, artefato: str, versao: str | None, ok: bool, erros: int = 0,
              detalhe: str | None = None, agora: datetime | None = None) -> None:
    tabela = "private/validacoes" if artefato in PRIVADOS else "meta/validacoes"
    lake.append(tabela, pd.DataFrame([{
        "run_id": run_id, "artefato": artefato, "versao": versao, "ok": bool(ok), "erros": int(erros),
        "detalhe": mascarar(detalhe)[:300] if detalhe else None, "em": agora or utcnow()}]))


def _erros_pydantic(e: Exception) -> tuple[int, str]:
    erros = getattr(e, "errors", None)
    if callable(erros):
        lista = erros()
        primeiro = ".".join(str(x) for x in lista[0].get("loc", ())) if lista else ""
        return len(lista), f"campo: {primeiro}" if primeiro else type(e).__name__
    return 1, type(e).__name__


def validar_configuracoes(s, lake: Lake, run_id: str, incluir_privadas: bool, agora: datetime | None = None) -> list[dict[str, Any]]:
    """Taxonomia sempre; perfil e radar.yaml só no fluxo privado (o público não lê dados pessoais)."""
    from .transformations.skills import Taxonomy
    resultados = []
    checagens = [("taxonomia", lambda: Taxonomy(s.skills).versao)]
    if incluir_privadas:
        from .notifications.radar import carregar_config
        from .scoring import Profile
        checagens += [("perfil", lambda: Profile.from_dict(s.profile).hash),
                      ("radar_config", lambda: (carregar_config(s.lake), "private/radar.yaml")[1])]
    for nome, f in checagens:
        try:
            versao = f()
            registrar(lake, run_id, nome, str(versao), True, 0, None, agora)
            resultados.append({"artefato": nome, "ok": True})
        except Exception as e:
            causa = e.__cause__ or e
            n, det = _erros_pydantic(causa)
            registrar(lake, run_id, nome, None, False, n, det, agora)
            resultados.append({"artefato": nome, "ok": False, "erros": n})
    return resultados

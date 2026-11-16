"""Proteção de credenciais em mensagens (Etapa 8): nada de chave, senha ou token em log, erro ou resumo.

Hoje os coletores já montam as mensagens sem a query string, mas uma biblioteca pode incluir a URL
completa num erro futuro (a da Adzuna leva `app_key` na query). Este filtro é a segunda barreira:
mascara pares `chave=valor` sensíveis, cabeçalhos `Bearer …` e os VALORES dos secrets conhecidos do ambiente.
"""
from __future__ import annotations

import logging
import os
import re

SECRETS_DO_AMBIENTE = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "SMTP_PASSWORD", "SMTP_USER", "EMAIL_TO", "EMAIL_FROM",
                       "GH_TOKEN", "GITHUB_TOKEN")
_PARES = re.compile(r"(?i)\b(app_key|app_id|api[_-]?key|access[_-]?token|token|password|passwd|senha|secret)"
                    r"(\s*[=:]\s*|=)([^\s&'\"<>]+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
MASCARA = "***"


def mascarar(texto: object) -> str:
    t = str(texto)
    for nome in SECRETS_DO_AMBIENTE:
        valor = (os.getenv(nome) or "").strip()
        if len(valor) >= 4:
            t = t.replace(valor, MASCARA)
    t = _PARES.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASCARA}", t)
    return _BEARER.sub(lambda m: f"{m.group(1)} {MASCARA}", t)


class FiltroSegredos(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mascarar(record.getMessage())
            record.args = ()
        except Exception:   # nunca derrubar o log por causa do filtro
            pass
        return True


def instalar_filtro() -> None:
    raiz = logging.getLogger()
    for h in raiz.handlers:
        if not any(isinstance(f, FiltroSegredos) for f in h.filters):
            h.addFilter(FiltroSegredos())

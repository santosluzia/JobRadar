"""Contrato dos coletores.

Um coletor faz duas coisas, separadas de propósito:
- collect(): busca na fonte e devolve os registros exatamente como vieram (vão para a bronze);
- to_raw_job(): mapeia UM registro bruto para RawJob (entrada da silver).
Assim a silver pode ser reprocessada a partir da bronze sem chamar a fonte de novo.
"""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..models import RawJob

log = logging.getLogger(__name__)
USER_AGENT = "JobRadar/1.0 (observatorio pessoal de vagas; github.com/santosluzia/jobradar)"
# Teto de espera entre tentativas. Retry-After acima disso não é esperado: o quadro é dado como falho
# nesta execução (esperar minutos estouraria o tempo do job e a próxima execução tenta de novo).
ESPERA_MAX_S = 60.0
JITTER = 0.25   # até +25% no backoff exponencial, para requisições não baterem juntas


def retry_after(valor: str | None, padrao: float, agora: datetime | None = None) -> float:
    """Retry-After em segundos ou em data HTTP (RFC 9110). Ausente ou inválido → `padrao`."""
    if not valor:
        return padrao
    try:
        return max(0.0, float(valor))
    except ValueError:
        pass
    try:
        quando = parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        return padrao
    if quando is None:
        return padrao
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return max(0.0, (quando - (agora or datetime.now(timezone.utc))).total_seconds())


@dataclass
class CollectResult:
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    requests: int = 0
    retries: int = 0
    duplicates_in_source: int = 0
    errors: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    # Fontes que listam o quadro inteiro de uma empresa (Greenhouse, Lever): quadro → ids de TODAS as
    # vagas listadas, antes de qualquer filtro. Só entram quadros lidos por completo; é a evidência
    # usada para encerrar as vagas que saíram do quadro.
    quadros: dict[str, list[str]] = field(default_factory=dict)
    # Métricas por quadro/empresa (fontes de ATS): ok, completo, vagas listadas e mantidas no filtro,
    # requisições, retentativas, duração e erro. Viram `meta/board_runs` (última coleta por empresa).
    por_quadro: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


class SourceError(RuntimeError):
    pass


class Collector(ABC):
    name = "base"
    # Campos do registro bruto que to_raw_job usa: se um deles some ou cai muito, o formato da fonte
    # mudou (collectors/assinatura.py, ADR 0013). Caminho no formato de `assinatura.caminhos`.
    CAMPOS_ESSENCIAIS: tuple[str, ...] = ()

    def __init__(self, cfg: dict[str, Any], client: httpx.Client | None = None):
        self.cfg = cfg
        self.pause = float(cfg.get("pausa_segundos", 1.0))
        self.client = client or httpx.Client(timeout=30, follow_redirects=True,
                                             headers={"User-Agent": USER_AGENT})

    def _get(self, url: str, params: dict[str, Any] | None, result: CollectResult,
             attempts: int = 3) -> httpx.Response:
        """GET com retry exponencial (com jitter) para 429/5xx/timeouts, respeitando Retry-After em segundos
        ou em data HTTP. 4xx (exceto 429) não é repetido. Retry-After acima de ESPERA_MAX_S encerra as
        tentativas: o quadro fica como falho nesta execução."""
        for i in range(1, attempts + 1):
            result.requests += 1
            espera = float(2**i) * (1 + random.uniform(0, JITTER))
            try:
                resp = self.client.get(url, params=params)
            except httpx.TransportError as e:
                erro: Exception = e
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    erro = SourceError(f"HTTP {resp.status_code}")
                    espera = retry_after(resp.headers.get("retry-after"), espera)
                    if espera > ESPERA_MAX_S:
                        raise SourceError(f"{self.name}: HTTP {resp.status_code} com Retry-After de "
                                          f"{espera:.0f}s (acima de {ESPERA_MAX_S:.0f}s)")
                elif resp.status_code >= 400:
                    raise SourceError(f"HTTP {resp.status_code} em {url}")
                else:
                    return resp
            if i == attempts:
                raise SourceError(f"{self.name}: falhou após {attempts} tentativas ({erro})")
            result.retries += 1
            log.warning("%s: %s, nova tentativa em %.0fs", self.name, erro, espera)
            time.sleep(min(espera, ESPERA_MAX_S) if self.pause else 0)
        raise AssertionError("inalcançável")

    def _sleep(self) -> None:
        if self.pause:
            time.sleep(self.pause)

    @staticmethod
    def dedupe(records: list[dict[str, Any]], key: str, result: CollectResult) -> list[dict[str, Any]]:
        vistos: dict[str, dict[str, Any]] = {}
        for r in records:
            k = str(r.get(key) or id(r))
            if k in vistos:
                result.duplicates_in_source += 1
            vistos.setdefault(k, r)
        return list(vistos.values())

    @abstractmethod
    def collect(self, termos: list[str]) -> CollectResult: ...

    @abstractmethod
    def to_raw_job(self, record: dict[str, Any]) -> RawJob: ...

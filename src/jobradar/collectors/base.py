"""Contrato dos coletores.

Um coletor faz duas coisas, separadas de propósito:
- collect(): busca na fonte e devolve os registros exatamente como vieram (vão para a bronze);
- to_raw_job(): mapeia UM registro bruto para RawJob (entrada da silver).
Assim a silver pode ser reprocessada a partir da bronze sem chamar a fonte de novo.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..models import RawJob

log = logging.getLogger(__name__)
USER_AGENT = "JobRadar/1.0 (observatorio pessoal de vagas; github.com/santosluzia/jobradar)"


@dataclass
class CollectResult:
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    requests: int = 0
    retries: int = 0
    duplicates_in_source: int = 0
    errors: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


class SourceError(RuntimeError):
    pass


class Collector(ABC):
    name = "base"

    def __init__(self, cfg: dict[str, Any], client: httpx.Client | None = None):
        self.cfg = cfg
        self.pause = float(cfg.get("pausa_segundos", 1.0))
        self.client = client or httpx.Client(timeout=30, follow_redirects=True,
                                             headers={"User-Agent": USER_AGENT})

    def _get(self, url: str, params: dict[str, Any] | None, result: CollectResult,
             attempts: int = 3) -> httpx.Response:
        """GET com retry exponencial para 429/5xx/timeouts. 4xx (exceto 429) não é repetido."""
        for i in range(1, attempts + 1):
            result.requests += 1
            espera = float(2**i)
            try:
                resp = self.client.get(url, params=params)
            except httpx.TransportError as e:
                erro: Exception = e
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    erro = SourceError(f"HTTP {resp.status_code}")
                    try:
                        espera = float(resp.headers.get("retry-after", espera))
                    except ValueError:
                        pass
                elif resp.status_code >= 400:
                    raise SourceError(f"HTTP {resp.status_code} em {url}")
                else:
                    return resp
            if i == attempts:
                raise SourceError(f"{self.name}: falhou após {attempts} tentativas ({erro})")
            result.retries += 1
            log.warning("%s: %s, nova tentativa em %.0fs", self.name, erro, espera)
            time.sleep(min(espera, 60) if self.pause else 0)
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

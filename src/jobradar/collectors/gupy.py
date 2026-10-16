"""Gupy — endpoint JSON consumido pelo portal público portal.gupy.io (sem login).

Limitação documentada: não é uma API oficial. O formato pode mudar sem aviso, por isso:
URLs alternativas configuráveis, validação de schema na silver e alerta de fonte na execução.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..models import RawJob
from ..transformations.text import html_para_texto
from .base import Collector, CollectResult, SourceError

log = logging.getLogger(__name__)

MODALIDADE = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial"}


class GupyCollector(Collector):
    name = "gupy"

    def _termo(self, url: str, termo: str, result: CollectResult) -> list[dict[str, Any]]:
        limite = int(self.cfg.get("limite_por_termo", 100))
        registros: list[dict[str, Any]] = []
        offset, pagina = 0, min(limite, 100)
        while offset < limite:
            corpo = self._get(url, {"jobName": termo, "limit": pagina, "offset": offset}, result).json()
            if not isinstance(corpo, dict) or "data" not in corpo:
                raise SourceError("gupy: resposta sem o campo 'data' (formato mudou?)")
            dados = corpo["data"] or []
            registros.extend(dados)
            total = (corpo.get("pagination") or {}).get("total", len(dados))
            offset += pagina
            if not dados or offset >= total:
                break
            self._sleep()
        return registros

    def collect(self, termos: list[str]) -> CollectResult:
        urls = self.cfg.get("urls") or []
        ultimo = None
        for url in urls:
            result = CollectResult(self.name, params={"url": url, "termos": termos})
            try:
                todos: list[dict[str, Any]] = []
                for termo in termos:
                    todos.extend(self._termo(url, termo, result))
                    self._sleep()
                result.records = self.dedupe(todos, "id", result)
                return result
            except (SourceError, ValueError) as e:
                ultimo = e
                log.warning("gupy: %s indisponível (%s)", url, e)
        result = CollectResult(self.name, params={"termos": termos})
        result.errors.append(f"todas as URLs falharam: {ultimo}")
        return result

    def to_raw_job(self, r: dict[str, Any]) -> RawJob:
        modalidade = MODALIDADE.get(r.get("workplaceType") or "")
        if not modalidade and r.get("isRemoteWork"):
            modalidade = "remoto"
        return RawJob(
            source=self.name,
            source_job_id=str(r["id"]) if r.get("id") is not None else None,
            url=r.get("jobUrl") or r.get("applyUrl") or "",
            title=r.get("name") or "",
            company=r.get("careerPageName"),
            location_raw=", ".join(p for p in [r.get("city"), r.get("state")] if p) or None,
            city=r.get("city") or None,
            state=r.get("state") or None,
            country=r.get("country") or None,
            modality_raw=modalidade,
            published_at=r.get("publishedDate"),
            deadline_at=_data(r.get("applicationDeadline")),
            description=html_para_texto(r.get("description")),
            extra={"type": r.get("type"), "disabilities": r.get("disabilities")},
        )


def _data(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None

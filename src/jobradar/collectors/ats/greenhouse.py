"""Greenhouse — Job Board API pública, consultada empresa por empresa.

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Devolve TODAS as vagas da empresa, com `meta.total` para conferir se a lista veio inteira.
Regras de quadro e de filtro por título: collectors/ats/comum.py.
"""
from __future__ import annotations

from typing import Any

from ...models import RawJob
from ...transformations.text import html_para_texto
from ..base import Collector, CollectResult, SourceError
from .comum import aplicar_filtro, medindo, registrar_quadro


class GreenhouseCollector(Collector):
    name = "greenhouse"
    URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def collect(self, termos: list[str]) -> CollectResult:
        empresas = self.cfg.get("empresas") or []
        result = CollectResult(self.name, params={"empresas": empresas})
        todos = []
        for token in empresas:
            with medindo(result, token):
                corpo = self._get(self.URL.format(token=token), {"content": "true"}, result).json()
                vagas = corpo.get("jobs") if isinstance(corpo, dict) else None
                if not isinstance(vagas, list):
                    raise SourceError("resposta sem a lista 'jobs' (formato mudou?)")
                for job in vagas:
                    job["_board"] = token
                    todos.append(job)
                registrar_quadro(result, token, vagas, (corpo.get("meta") or {}).get("total"))
            self._sleep()
        result.records = self.dedupe(aplicar_filtro(self.cfg, todos, "title", result, "_board"), "id", result)
        return result

    def to_raw_job(self, r: dict[str, Any]) -> RawJob:
        local = (r.get("location") or {}).get("name")
        return RawJob(
            source=self.name,
            source_job_id=str(r.get("id")),
            url=r.get("absolute_url") or "",
            title=r.get("title") or "",
            company=r.get("company_name") or r.get("_board"),
            location_raw=local,
            modality_raw="remoto" if local and "remot" in local.lower() else None,
            published_at=r.get("first_published") or r.get("updated_at"),
            description=html_para_texto(r.get("content")),
            board=r.get("_board"),
            extra={"board": r.get("_board")},
        )

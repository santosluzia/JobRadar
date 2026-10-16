"""Greenhouse e Lever — APIs públicas de job boards, consultadas empresa por empresa.

Greenhouse: GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Lever:      GET https://api.lever.co/v0/postings/{empresa}?mode=json
Ambas devolvem TODAS as vagas da empresa; o filtro de relevância acontece na silver.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import RawJob
from ..transformations.text import html_para_texto
from .base import Collector, CollectResult, SourceError


class GreenhouseCollector(Collector):
    name = "greenhouse"
    URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def collect(self, termos: list[str]) -> CollectResult:
        empresas = self.cfg.get("empresas") or []
        result = CollectResult(self.name, params={"empresas": empresas})
        todos = []
        for token in empresas:
            try:
                corpo = self._get(self.URL.format(token=token), {"content": "true"}, result).json()
                for job in corpo.get("jobs", []):
                    job["_board"] = token
                    todos.append(job)
            except (SourceError, ValueError) as e:
                result.errors.append(f"{token}: {e}")
            self._sleep()
        result.records = self.dedupe(todos, "id", result)
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
            extra={"board": r.get("_board")},
        )


class LeverCollector(Collector):
    name = "lever"
    URL = "https://api.lever.co/v0/postings/{empresa}"
    MODALIDADE = {"remote": "remoto", "hybrid": "hibrido", "onsite": "presencial"}

    def collect(self, termos: list[str]) -> CollectResult:
        empresas = self.cfg.get("empresas") or []
        result = CollectResult(self.name, params={"empresas": empresas})
        todos = []
        for empresa in empresas:
            try:
                for job in self._get(self.URL.format(empresa=empresa), {"mode": "json"}, result).json():
                    job["_empresa"] = empresa
                    todos.append(job)
            except (SourceError, ValueError) as e:
                result.errors.append(f"{empresa}: {e}")
            self._sleep()
        result.records = self.dedupe(todos, "id", result)
        return result

    def to_raw_job(self, r: dict[str, Any]) -> RawJob:
        cat = r.get("categories") or {}
        criado = r.get("createdAt")
        return RawJob(
            source=self.name,
            source_job_id=r.get("id"),
            url=r.get("hostedUrl") or r.get("applyUrl") or "",
            title=r.get("text") or "",
            company=r.get("_empresa"),
            location_raw=cat.get("location"),
            modality_raw=self.MODALIDADE.get(r.get("workplaceType") or ""),
            published_at=datetime.fromtimestamp(criado / 1000, tz=timezone.utc) if criado else None,
            description=r.get("descriptionPlain") or html_para_texto(r.get("description")),
            extra={"team": cat.get("team"), "commitment": cat.get("commitment")},
        )

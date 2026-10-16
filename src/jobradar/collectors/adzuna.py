"""Adzuna — API oficial (developer.adzuna.com), exige app_id/app_key.

Limitação: a Adzuna entrega só um trecho da descrição e o link passa por redirecionamento dela.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..models import RawJob
from ..transformations.text import html_para_texto, normalizar
from .base import Collector, CollectResult, SourceError

BASE = "https://api.adzuna.com/v1/api/jobs/{pais}/search/{pagina}"


class AdzunaCollector(Collector):
    name = "adzuna"

    def __init__(self, cfg: dict[str, Any], app_id: str, app_key: str, client: httpx.Client | None = None):
        super().__init__(cfg, client)
        self.app_id, self.app_key = app_id, app_key

    def collect(self, termos: list[str]) -> CollectResult:
        pais = self.cfg.get("pais", "br")
        result = CollectResult(self.name, params={"pais": pais, "termos": termos})
        todos: list[dict[str, Any]] = []
        try:
            for termo in termos:
                corpo = self._get(BASE.format(pais=pais, pagina=1), {
                    "app_id": self.app_id, "app_key": self.app_key,
                    "what_phrase": termo,
                    "results_per_page": int(self.cfg.get("resultados_por_pagina", 50)),
                    "max_days_old": int(self.cfg.get("max_dias", 30)),
                    "sort_by": "date",
                }, result).json()
                todos.extend(corpo.get("results", []))
                self._sleep()
        except (SourceError, ValueError) as e:
            result.errors.append(str(e))
        result.records = self.dedupe(todos, "id", result)
        return result

    def to_raw_job(self, r: dict[str, Any]) -> RawJob:
        local = (r.get("location") or {}).get("display_name")
        area = (r.get("location") or {}).get("area") or []
        texto = normalizar(f"{r.get('title', '')} {r.get('description', '')}")
        modalidade = "remoto" if ("remoto" in texto or "home office" in texto or "remote" in texto) else None
        return RawJob(
            source=self.name,
            source_job_id=str(r["id"]) if r.get("id") else None,
            url=r.get("redirect_url") or "",
            title=html_para_texto(r.get("title")) or "",
            company=(r.get("company") or {}).get("display_name"),
            location_raw=local,
            city=area[-1] if len(area) >= 3 else None,
            state=area[1] if len(area) >= 2 else None,
            country=area[0] if area else None,
            modality_raw=modalidade,
            published_at=r.get("created"),
            description=html_para_texto(r.get("description")),
            extra={"contract_type": r.get("contract_type"), "salary_is_predicted": r.get("salary_is_predicted")},
        )

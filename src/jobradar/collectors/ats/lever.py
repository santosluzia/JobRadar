"""Lever — Postings API pública, consultada empresa por empresa.

GET https://api.lever.co/v0/postings/{empresa}?mode=json
Devolve TODAS as vagas publicadas da empresa (sem total informado: quadro vazio é o único sinal de
lista suspeita). Regras de quadro e de filtro por título: collectors/ats/comum.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models import RawJob
from ...transformations.text import html_para_texto
from ..base import Collector, CollectResult, SourceError
from .comum import aplicar_filtro, medindo, registrar_quadro


class LeverCollector(Collector):
    name = "lever"
    URL = "https://api.lever.co/v0/postings/{empresa}"
    MODALIDADE = {"remote": "remoto", "hybrid": "hibrido", "onsite": "presencial"}

    def collect(self, termos: list[str]) -> CollectResult:
        empresas = self.cfg.get("empresas") or []
        result = CollectResult(self.name, params={"empresas": empresas})
        todos = []
        for empresa in empresas:
            with medindo(result, empresa):
                vagas = self._get(self.URL.format(empresa=empresa), {"mode": "json"}, result).json()
                if not isinstance(vagas, list):
                    raise SourceError("resposta não é uma lista de vagas (formato mudou?)")
                for job in vagas:
                    job["_empresa"] = empresa
                    todos.append(job)
                registrar_quadro(result, empresa, vagas)
            self._sleep()
        result.records = self.dedupe(aplicar_filtro(self.cfg, todos, "text", result, "_empresa"), "id", result)
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
            board=r.get("_empresa"),
            extra={"team": cat.get("team"), "commitment": cat.get("commitment")},
        )

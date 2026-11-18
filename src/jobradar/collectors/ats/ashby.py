"""Ashby — Public Job Posting API, consultada empresa por empresa.

GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true
(developers.ashbyhq.com/docs/public-job-posting-api; conferido em 2026-11-17)

Devolve TODAS as vagas publicadas do quadro, sem total informado (quadro vazio é o único sinal de lista
suspeita, como no Lever). Campos usados: id, title, location, address.postalAddress, workplaceType,
descriptionPlain/descriptionHtml, publishedAt, jobUrl, applyUrl, isListed e employmentType.
- A tabela de campos da documentação não lista `id`, mas a resposta traz o UUID da vaga; sem ele, o id
  sai do último trecho de `jobUrl` (…/{quadro}/{uuid}).
- `isListed: false` = vaga só acessível por link direto: conta como presente no quadro (não encerra),
  mas não entra na coleta.
- `compensation` (com includeCompensation) fica na bronze; a normalização de salário é um passo próprio.
Regras de quadro e de filtro por título: collectors/ats/comum.py.
"""
from __future__ import annotations

from typing import Any

from ...models import RawJob
from ...transformations.text import html_para_texto
from ..base import Collector, CollectResult, SourceError
from .comum import aplicar_filtro, medindo, registrar_quadro


def _id(job: dict[str, Any]) -> str | None:
    if job.get("id"):
        return str(job["id"])
    url = (job.get("jobUrl") or "").rstrip("/")
    return url.rsplit("/", 1)[-1] if url else None


class AshbyCollector(Collector):
    name = "ashby"
    CAMPOS_ESSENCIAIS = ("id", "title", "jobUrl", "descriptionPlain", "location", "publishedAt")
    URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"
    MODALIDADE = {"Remote": "remoto", "Hybrid": "hibrido", "OnSite": "presencial"}

    def collect(self, termos: list[str]) -> CollectResult:
        empresas = self.cfg.get("empresas") or []
        nomes = self.cfg.get("nomes") or {}
        result = CollectResult(self.name, params={"empresas": empresas})
        todos, nao_listadas = [], 0
        for board in empresas:
            with medindo(result, board):
                corpo = self._get(self.URL.format(board=board), {"includeCompensation": "true"}, result).json()
                vagas = corpo.get("jobs") if isinstance(corpo, dict) else None
                if not isinstance(vagas, list):
                    raise SourceError("resposta sem a lista 'jobs' (formato mudou?)")
                for job in vagas:
                    job["id"] = _id(job)
                    if job.get("isListed") is False:
                        nao_listadas += 1
                        continue
                    job["_board"], job["_empresa_nome"] = board, nomes.get(board)
                    todos.append(job)
                registrar_quadro(result, board, vagas)
            self._sleep()
        result.params["nao_listadas"] = nao_listadas
        result.records = self.dedupe(aplicar_filtro(self.cfg, todos, "title", result, "_board"), "id", result)
        return result

    def to_raw_job(self, r: dict[str, Any]) -> RawJob:
        end = (r.get("address") or {}).get("postalAddress") or {}
        return RawJob(
            source=self.name,
            source_job_id=r.get("id"),
            url=r.get("jobUrl") or r.get("applyUrl") or "",
            title=r.get("title") or "",
            company=r.get("_empresa_nome") or r.get("_board"),
            location_raw=r.get("location"),
            city=end.get("addressLocality") or None,
            state=end.get("addressRegion") or None,
            country=end.get("addressCountry") or None,
            # sem workplaceType, isRemote ainda diz se é remota (não diz se é presencial)
            modality_raw=self.MODALIDADE.get(r.get("workplaceType") or "") or ("remoto" if r.get("isRemote") is True else None),
            published_at=r.get("publishedAt"),
            description=(r.get("descriptionPlain") or html_para_texto(r.get("descriptionHtml")) or "")[:20000] or None,
            board=r.get("_board"),
            extra={"employment_type": r.get("employmentType"), "department": r.get("department")},
        )

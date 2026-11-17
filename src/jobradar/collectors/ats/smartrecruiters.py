"""SmartRecruiters — Posting API pública (sem autenticação para vagas públicas), empresa por empresa.

GET https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings?limit=100&offset=N&destination=PUBLIC
GET https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings/{postingId}
(developers.smartrecruiters.com/reference/v1listpostings e v1getposting; conferido em 2026-11-17)

- A listagem é paginada (`limit` máximo 100, `offset`, `totalFound`) e NÃO traz a descrição: ela vem do
  detalhe de cada vaga (`jobAd.sections`), que só é buscado para as vagas que passam no filtro de título.
- Quadro completo = todas as páginas lidas e `totalFound` igual ao número de vagas listadas. Os ids de
  todas as vagas (antes do filtro) são a evidência de encerramento, como no Greenhouse.
- Detalhe que falha: a vaga fica fora desta coleta (sem link de candidatura não há registro válido) e
  conta em `detalhes_com_erro`; continua no quadro, então não é encerrada.
- `compensation` (min, max, currency, period) fica na bronze; a normalização de salário é um passo próprio.
Regras de quadro e de filtro por título: collectors/ats/comum.py.
"""
from __future__ import annotations

from typing import Any

from ...models import RawJob
from ...transformations.text import html_para_texto
from ..base import Collector, CollectResult, SourceError
from .comum import aplicar_filtro, medindo, registrar_quadro

SECOES = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def descricao(detalhe: dict[str, Any] | None) -> str | None:
    """Seções do anúncio, cada uma com o título que a própria empresa deu (a extração de competências
    reconhece "Qualifications", "Requisitos" etc. como cabeçalho e trata o texto sobre a empresa como contexto)."""
    secoes = ((detalhe or {}).get("jobAd") or {}).get("sections") or {}
    partes = []
    for chave in SECOES:
        s = secoes.get(chave) or {}
        texto = html_para_texto(s.get("text"))
        if texto:
            partes.append(f"{s.get('title') or ''}:\n{texto}" if s.get("title") else texto)
    return "\n\n".join(partes)[:20000] or None   # mesmo limite dos outros coletores


class SmartRecruitersCollector(Collector):
    name = "smartrecruiters"
    URL = "https://api.smartrecruiters.com/v1/companies/{board}/postings"
    PAGINA = 100

    def _listar(self, board: str, result: CollectResult) -> tuple[list[dict[str, Any]], int | None]:
        vagas: list[dict[str, Any]] = []
        offset, total = 0, None
        while True:
            corpo = self._get(self.URL.format(board=board),
                              {"limit": self.PAGINA, "offset": offset, "destination": "PUBLIC"}, result).json()
            pagina = corpo.get("content") if isinstance(corpo, dict) else None
            if not isinstance(pagina, list) or not isinstance(corpo.get("totalFound"), int):
                raise SourceError("resposta sem 'content'/'totalFound' (formato mudou?)")
            total = corpo["totalFound"]
            vagas.extend(pagina)
            offset += self.PAGINA
            if not pagina or offset >= total:
                return vagas, total
            self._sleep()

    def collect(self, termos: list[str]) -> CollectResult:
        empresas = self.cfg.get("empresas") or []
        nomes = self.cfg.get("nomes") or {}
        result = CollectResult(self.name, params={"empresas": empresas})
        todos = []
        for board in empresas:
            with medindo(result, board):
                vagas, total = self._listar(board, result)
                for job in vagas:
                    job["_board"], job["_empresa_nome"] = board, nomes.get(board)
                    todos.append(job)
                registrar_quadro(result, board, vagas, total)
            self._sleep()
        mantidas = self.dedupe(aplicar_filtro(self.cfg, todos, "name", result, "_board"), "id", result)
        result.records, erros = [], 0
        for job in mantidas:
            try:
                if job.get("id") is None:
                    raise ValueError("vaga sem id na listagem")
                det = self._get(f"{self.URL.format(board=job['_board'])}/{job['id']}", None, result).json()
                if not isinstance(det, dict):
                    raise ValueError("detalhe fora do formato")
            except (SourceError, ValueError):
                erros += 1
                m = result.por_quadro.get(job["_board"])
                if m is not None:
                    m["vagas_mantidas"] -= 1
            else:
                job["_detalhe"] = det
                result.records.append(job)
            self._sleep()   # pausa também depois de erro: falhas seguidas não viram rajada de requisições
        result.params["detalhes_com_erro"] = erros
        return result

    def to_raw_job(self, r: dict[str, Any]) -> RawJob:
        det = r.get("_detalhe") or {}
        loc = det.get("location") or r.get("location") or {}
        if loc.get("remote"):
            modalidade = "remoto"
        elif loc.get("hybrid"):
            modalidade = "hibrido"
        elif "remote" in loc or "hybrid" in loc:
            modalidade = "presencial"   # a fonte informa as duas como falsas
        else:
            modalidade = None
        pais = loc.get("country")
        return RawJob(
            source=self.name,
            source_job_id=str(r["id"]) if r.get("id") is not None else None,
            url=det.get("postingUrl") or det.get("applyUrl") or "",
            title=r.get("name") or "",
            company=(r.get("company") or {}).get("name") or r.get("_empresa_nome") or r.get("_board"),
            location_raw=loc.get("fullLocation") or ", ".join(p for p in (loc.get("city"), loc.get("region")) if p) or None,
            city=loc.get("city") or None,
            state=loc.get("region") or None,
            country=pais.upper() if isinstance(pais, str) else None,
            modality_raw=modalidade,
            published_at=r.get("releasedDate"),
            description=descricao(det),
            board=r.get("_board"),
            extra={"experience_level": (r.get("experienceLevel") or {}).get("label"),
                   "type_of_employment": (r.get("typeOfEmployment") or {}).get("label")},
        )

"""Adzuna — API oficial (developer.adzuna.com), exige app_id/app_key.

Limitação: a Adzuna entrega só um trecho da descrição e o link passa por redirecionamento dela.

Uma chamada por termo (página 1, as mais recentes primeiro). `termos_so_no_titulo` usa `title_only`;
os demais usam `what_phrase` (a expressão no título ou na descrição). Erro num termo não interrompe os
outros; 3 termos seguidos com erro encerram a fonte nesta execução (fora do ar ou chave recusada).
`title_only` não aparece na página de exemplos da documentação; o comportamento foi conferido ao vivo
em 2026-11-18 (todos os títulos devolvidos contêm as palavras do termo).
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
    MAX_ERROS_SEGUIDOS = 3

    def __init__(self, cfg: dict[str, Any], app_id: str, app_key: str, client: httpx.Client | None = None):
        super().__init__(cfg, client)
        self.app_id, self.app_key = app_id, app_key

    def collect(self, termos: list[str]) -> CollectResult:
        pais = self.cfg.get("pais", "br")
        result = CollectResult(self.name, params={"pais": pais, "termos": termos})
        todos: list[dict[str, Any]] = []
        falhos: list[str] = []
        seguidos = 0
        # Termos de tecnologia/conceito ("banco de dados", "sql server"…) aparecem na descrição de vagas de
        # qualquer área: para eles a busca é só no título (`title_only`, todas as palavras no título). Os
        # nomes de cargo ("analista de dados") seguem com `what_phrase`, que também acha pela descrição.
        so_titulo = {normalizar(t) for t in self.cfg.get("termos_so_no_titulo") or []}
        result.params["termos_so_no_titulo"] = [t for t in termos if normalizar(t) in so_titulo]
        for i, termo in enumerate(termos):
            # Erro num termo (503 da Adzuna, sobretudo de madrugada) não interrompe os demais: antes, um
            # 503 no 2º termo deixava a execução sem os outros 18.
            try:
                corpo = self._get(BASE.format(pais=pais, pagina=1), {
                    "app_id": self.app_id, "app_key": self.app_key,
                    ("title_only" if normalizar(termo) in so_titulo else "what_phrase"): termo,
                    "results_per_page": int(self.cfg.get("resultados_por_pagina", 50)),
                    "max_days_old": int(self.cfg.get("max_dias", 30)),
                    "sort_by": "date",
                }, result).json()
                if not isinstance(corpo, dict) or not isinstance(corpo.get("results", []), list):
                    raise SourceError("resposta sem a lista 'results' (formato mudou?)")
                todos.extend(corpo.get("results", []))
            except (SourceError, ValueError) as e:
                falhos.append(termo)
                result.errors.append(f"{termo}: {e}")
                seguidos += 1
                if seguidos >= self.MAX_ERROS_SEGUIDOS:   # fonte fora do ar ou chave recusada: não insiste
                    result.errors.append(f"{self.MAX_ERROS_SEGUIDOS} termos seguidos com erro; "
                                         f"{len(termos) - i - 1} termos não consultados")
                    break
            else:
                seguidos = 0
            self._sleep()
        result.params["termos_com_erro"] = falhos
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

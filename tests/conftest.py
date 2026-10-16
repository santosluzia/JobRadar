"""Fixtures: respostas simuladas das fontes (os testes nunca acessam a internet)."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import yaml

from jobradar.collectors import AdzunaCollector, GreenhouseCollector, GupyCollector
from jobradar.settings import CONFIG_DIR, carregar

AGORA = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)


def iso(dias_atras: float, base: datetime = AGORA) -> str:
    return (base - timedelta(days=dias_atras)).isoformat().replace("+00:00", "Z")


def gupy_jobs(base: datetime = AGORA) -> list[dict]:
    return [
        {"id": 101, "name": "Engenheira de Dados Jr - Vaga Afirmativa para Mulheres", "careerPageName": "KPMG",
         "city": "São Paulo", "state": "São Paulo", "country": "Brasil", "workplaceType": "hybrid",
         "isRemoteWork": False, "jobUrl": "https://kpmg.gupy.io/job/101?jobBoardSource=gupy_portal",
         "publishedDate": iso(0.5, base), "applicationDeadline": "2026-12-31",
         "description": "<p><b>Requisitos:</b></p><ul><li>Python e SQL</li><li>Spark e Databricks</li></ul>"
                        "<p><b>Diferenciais:</b></p><ul><li>Airflow</li><li>Azure Data Factory</li></ul>"},
        {"id": 102, "name": "Engenheiro de Dados Sênior", "careerPageName": "Banco X",
         "city": "São Paulo", "state": "São Paulo", "workplaceType": "remote", "isRemoteWork": True,
         "jobUrl": "https://bancox.gupy.io/job/102", "publishedDate": iso(1, base),
         "description": "Kafka, Spark, Scala e liderança técnica."},
        {"id": 103, "name": "Data Engineer Pleno", "careerPageName": "Fintech Y",
         "city": "", "state": "", "workplaceType": "remote", "isRemoteWork": True,
         "jobUrl": "https://fintechy.gupy.io/job/103", "publishedDate": iso(2, base),
         "description": "Requisitos: Python, SQL, dbt e Airflow. Experiência com AWS (S3, Glue)."},
        {"id": 104, "name": "Engenheiro de Software", "careerPageName": "Varejo Z",
         "city": "Osasco", "state": "SP", "workplaceType": "on-site",
         "jobUrl": "https://varejoz.gupy.io/job/104", "publishedDate": iso(3, base),
         "description": "Construção de pipelines de dados com Spark, Airflow e Databricks; modelagem em data lake."},
        {"id": 105, "name": "x", "careerPageName": "Registro inválido", "jobUrl": "", "publishedDate": iso(0, base)},
    ]


def adzuna_jobs(base: datetime = AGORA) -> list[dict]:
    return [
        # Mesma vaga da Fintech Y vinda de agregador → deve virar duplicata não canônica
        {"id": "a1", "title": "Data Engineer Pleno", "company": {"display_name": "Fintech Y"},
         "location": {"display_name": "Brasil", "area": ["Brasil"]},
         "redirect_url": "https://www.adzuna.com.br/land/ad/a1?utm_source=api", "created": iso(2, base),
         "description": "Python, SQL, dbt, Airflow. Trabalho remoto."},
        {"id": "a2", "title": "Analytics Engineer Júnior", "company": {"display_name": "Varejo W"},
         "location": {"display_name": "Barueri, São Paulo", "area": ["Brasil", "São Paulo", "Barueri"]},
         "redirect_url": "https://www.adzuna.com.br/land/ad/a2", "created": iso(4, base),
         "description": "SQL, dbt e Power BI. Home office."},
    ]


class FakeSources:
    """Roteador de respostas falsas; permite derrubar fontes e trocar o conteúdo entre execuções."""

    def __init__(self):
        self.gupy = gupy_jobs()
        self.adzuna = adzuna_jobs()
        self.greenhouse = {"jobs": [{
            "id": 9001, "title": "Data Engineer (Remote, LATAM)", "absolute_url": "https://boards.greenhouse.io/acme/jobs/9001",
            "location": {"name": "Remote - Brazil"}, "updated_at": iso(1), "company_name": "Acme",
            "content": "&lt;p&gt;Requirements: Python, SQL, Spark, Airflow.&lt;/p&gt;"}]}
        self.falhar: set[str] = set()
        self.chamadas: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request)
        host = request.url.host
        for nome in self.falhar:
            if nome in host:
                return httpx.Response(503)
        if "gupy" in host:
            offset = int(request.url.params.get("offset", 0))
            dados = copy.deepcopy(self.gupy) if offset == 0 else []
            return httpx.Response(200, json={"data": dados, "pagination": {"total": len(self.gupy)}})
        if "adzuna" in host:
            return httpx.Response(200, json={"results": copy.deepcopy(self.adzuna)})
        if "greenhouse" in host:
            return httpx.Response(200, json=copy.deepcopy(self.greenhouse))
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def collectors(self, s):
        c = self.client()
        cols = [GupyCollector(s.fonte("gupy"), client=c),
                AdzunaCollector(s.fonte("adzuna"), "id", "key", client=c),
                GreenhouseCollector({"empresas": ["acme"]}, client=c)]
        for col in cols:
            col.pause = 0
        return cols


PERFIL_TESTE = {
    "objetivo": {"familias": ["engenharia_dados", "analytics_engineering"], "senioridades": ["junior", "pleno"],
                 "modalidades": ["remoto", "hibrido"], "locais": {"ufs": ["SP"], "cidades": ["sao paulo"]}},
    "competencias": [
        {"skill": "sql", "nivel": "profissional", "evidencias": ["Oracle em projetos corporativos"]},
        {"skill": "python", "nivel": "projeto"},
        {"skill": "databricks", "nivel": "em_desenvolvimento"},
        {"skill": "kafka", "nivel": "nao_dominada"},
    ],
}


@pytest.fixture
def fake() -> FakeSources:
    return FakeSources()


@pytest.fixture
def settings(tmp_path: Path):
    lake = tmp_path / "lake"
    (lake / "private").mkdir(parents=True)
    (lake / "private" / "profile.yaml").write_text(yaml.safe_dump(PERFIL_TESTE), encoding="utf-8")
    s = carregar(lake=lake, config_dir=CONFIG_DIR)
    s.termos.clear()
    s.termos.extend(["engenheiro de dados", "data engineer"])  # 2 termos = duplicatas por termo
    return s

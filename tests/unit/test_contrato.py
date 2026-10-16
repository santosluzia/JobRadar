import copy
import json

import pytest

from jobradar.publishing import ContractError, schemas, validar
from jobradar.settings import ROOT


def test_schemas_versionados_estao_em_dia_com_o_codigo():
    for nome, sch in schemas().items():
        for pasta in (ROOT / "docs" / "contracts" / "v1", ROOT / "src" / "jobradar" / "publishing" / "schemas"):
            arquivo = pasta / f"{nome}.schema.json"
            assert json.loads(arquivo.read_text()) == sch, f"rode `jobradar contract export` ({arquivo})"


def _doc_jobs():
    return {"schema_version": "1.0.0", "dataset": "jobs", "generated_at": "2026-10-16T10:00:00Z", "run_id": "r",
            "data_window": {"start": None, "end": None},
            "coverage": {"sources": [], "observations": 1, "note": "x"},
            "data": {"selection": {"window_days": 30, "limit": 300, "total_relevant": 1,
                                   "sort": "published_at_desc", "criteria": "x"},
                     "items": [{"id": "a" * 40, "title": "Data Engineer", "company": None, "city": None,
                                "state": "SP", "modality": "remoto", "seniority": "pleno", "family": "engenharia_dados",
                                "source": "gupy", "url": "https://x.gupy.io/job/1", "published_at": None,
                                "first_seen_at": "2026-10-16T10:00:00Z", "last_seen_at": "2026-10-16T10:00:00Z",
                                "status": "ativa", "skills": ["sql"], "required_skills": ["sql"]}]}}


def test_documento_valido_passa():
    validar({"jobs": _doc_jobs()})


@pytest.mark.parametrize("mutacao", [
    lambda d: d["data"]["items"][0].update(description="texto completo da vaga"),  # campo proibido
    lambda d: d["data"]["items"][0].update(score=80),                             # dado pessoal
    lambda d: d["data"]["items"][0].pop("url"),                                   # campo obrigatório
    lambda d: d["data"]["items"][0].update(modality="home"),                      # enum fechado
    lambda d: d["data"]["items"][0].update(url="http://inseguro"),                # só https
    lambda d: d.update(generated_at="ontem"),                                     # formato de data
    lambda d: d["data"]["items"].append(copy.deepcopy(d["data"]["items"][0])),    # id duplicado
])
def test_documento_invalido_e_barrado(mutacao):
    d = _doc_jobs()
    mutacao(d)
    with pytest.raises(ContractError):
        validar({"jobs": d})

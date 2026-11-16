"""Etapa 2 no pipeline e no contrato: gold/skill_pairs incremental e skill-trends 1.1.0."""
import copy
from datetime import timedelta

import pytest

from jobradar import pipeline
from jobradar.publishing import ContractError, construir, validar
from jobradar.publishing.contract import SCHEMA_VERSION
from jobradar.storage import Lake
from jobradar.transformations.skills import Taxonomy

from ..conftest import AGORA


def test_gold_de_pares_e_base_da_coocorrencia(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    pares = lake.read("gold/skill_pairs")
    assert not pares.empty and (pares["skill_a"] < pares["skill_b"]).all()
    assert (pares["vagas_par_requisito"] <= pares["vagas_par"]).all()
    # Python + SQL aparecem juntos em vagas de engenharia de dados da fixture
    assert ((pares["skill_a"] == "python") & (pares["skill_b"] == "sql")).any()
    tot = lake.read("gold/skill_monthly").query("skill_id == '__total__'")
    assert (tot["vagas_com_competencia"] <= tot["total_vagas"]).all() and tot["vagas_com_competencia"].notna().all()
    assert not set(pares["skill_a"]) & {s.id for s in Taxonomy(settings.skills).nao_tecnicas}

    antes = pares.copy()
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    assert rep.meses_recalculados == []                       # nada mudou: pares intactos
    assert lake.read("gold/skill_pairs").equals(antes)


def test_pares_aparecem_para_lake_antigo_sem_a_tabela(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    (settings.lake / "gold" / "skill_pairs.parquet").unlink()     # lake gravado antes da Etapa 2
    pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    assert not lake.read("gold/skill_pairs").empty


def test_contrato_1_1_publica_coocorrencia_e_aceita_documento_1_0(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    settings.scoring = copy.deepcopy(settings.scoring)
    settings.scoring["recomendacoes"]["min_vagas_janela"] = 2     # fixture pequena
    settings.scoring["coocorrencia"]["min_vagas_par"] = 1
    docs = construir(settings, AGORA, "r1")
    validar(docs)
    assert SCHEMA_VERSION == "1.1.0" and docs["skill-trends"]["schema_version"] == "1.1.0"
    co = docs["skill-trends"]["data"]["co_occurrence"]
    assert co["base"] > 0 and co["pairs"] and co["rank"] == "jaccard"
    tecnicas = Taxonomy(settings.skills).ids_tecnicos
    assert all({p["skill_a"], p["skill_b"]} <= tecnicas for p in co["pairs"])
    assert set(co["pairs"][0]) == {"skill_a", "skill_b", "jobs_both", "jobs_both_required", "jobs_a", "jobs_b",
                                    "support_pct", "confidence_a_b_pct", "confidence_a_b_ci", "confidence_b_a_pct",
                                    "confidence_b_a_ci", "lift", "jaccard"}

    # consumidor de 1.0.0 (sem o campo) continua válido: o campo é opcional
    antigo = copy.deepcopy(docs["skill-trends"])
    antigo["schema_version"] = "1.0.0"
    del antigo["data"]["co_occurrence"]
    validar({"skill-trends": antigo})

    # campo extra dentro do par é barrado (nada além do contrato sai para o público)
    docs["skill-trends"]["data"]["co_occurrence"]["pairs"][0]["perfil_hash"] = "x"
    with pytest.raises(ContractError):
        validar({"skill-trends": docs["skill-trends"]})


def test_amostra_pequena_nao_publica_pares(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    co = construir(settings, AGORA, "r1")["skill-trends"]["data"]["co_occurrence"]
    assert co["low_sample"] is True and co["pairs"] == []        # fixture tem menos de 30 vagas

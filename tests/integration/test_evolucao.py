"""Etapa 4 no fluxo inteiro: plano por objetivo, prioridade explicável, corte de prioritárias,
progresso que recalcula score e plano, e privacidade."""
import copy
from datetime import timedelta

import pytest

from jobradar import pipeline
from jobradar.evolucao import servico
from jobradar.evolucao.plano import CLASSES
from jobradar.evolucao.progresso import atualizar
from jobradar.publishing import construir, publicar
from jobradar.storage import Lake

from ..conftest import AGORA

# 40 vagas de engenharia de dados (júnior), com competências em frequências diferentes
FREQ = {"AWS": 32, "Airflow": 28, "dbt": 24, "Kafka": 20, "Docker": 16, "Terraform": 12, "Redis": 1}


def _vagas():
    vagas = []
    for i in range(40):
        extras = [k for k, n in FREQ.items() if i < n]
        vagas.append({"id": 7000 + i, "name": "Engenheiro de Dados Júnior", "careerPageName": f"Empresa {i}",
                      "workplaceType": "remote", "jobUrl": f"https://v{i}.gupy.io/job/{i}", "publishedDate": None,
                      "description": "Requisitos: SQL, Python, " + ", ".join(extras) + "."})
    return vagas


@pytest.fixture
def grande(settings, fake):
    fake.gupy = _vagas()
    fake.adzuna, fake.greenhouse = [], {"jobs": []}
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    return settings


def test_plano_classes_sem_sobreposicao_e_corte_de_prioritarias(grande):
    p = servico.planos(grande, agora=AGORA)[0]
    assert not p["amostra_pequena"]
    todas = [i["skill_id"] for itens in p["classes"].values() for i in itens]
    assert len(todas) == len(set(todas))                      # cada competência numa classe só
    assert set(p["classes"]) == set(CLASSES)
    prio = [i["skill_id"] for i in p["prioritarias"]]
    cfg = grande.scoring["evolucao"]
    assert 0 < len(prio) <= cfg["max_prioritarias"]           # NÃO recomenda todas as lacunas
    assert "aws" in prio and "redis" not in prio
    fora = {i["skill_id"]: i["motivo"] for i in p["classes"]["baixa_relevancia"]}
    assert "redis" in fora and "abaixo de" in fora["redis"]
    assert p["classes"]["consolidada"] == [] and {"sql"} <= {i["skill_id"] for i in p["classes"]["declarada_sem_evidencia"]}
    for i in p["prioritarias"]:                                # decomposição soma a prioridade
        assert sum(i["decomposicao"].values()) == pytest.approx(i["prioridade"], abs=0.005)
        r = i["recomendacao"]
        assert r["vagas"] > 0 and r["por_que"] and r["cargos"] and r["conteudo_e_sugestao"] is True
        assert r["estudar"] and r["projeto"]                   # conteúdo de config/evolucao.yaml
    # mais frequente vem antes (AWS 80% > Airflow 70% …)
    assert prio.index("aws") < prio.index("airflow") if "airflow" in prio else True


def test_progresso_recalcula_score_e_plano(grande, fake):
    lake = Lake(grande.lake)
    antes = servico.planos(grande, agora=AGORA)[0]
    sc_antes = lake.read("gold/job_scores").set_index("job_id")["score"]
    r = atualizar(lake, "aws", "demonstrada_em_projeto", "github.com/exemplo/aws")
    assert r["nivel_no_perfil"] == "projeto"
    depois = servico.planos(grande, agora=AGORA)[0]
    assert "aws" not in [i["skill_id"] for i in depois["prioritarias"]]
    assert "aws" in [i["skill_id"] for i in depois["classes"]["demonstrada_projeto"]]
    assert depois["aderencia"]["perfil"]["valor"] > antes["aderencia"]["perfil"]["valor"]
    pipeline.run(grande, fake.collectors(grande), run_id="r2", agora=AGORA + timedelta(hours=6))
    sc_depois = lake.read("gold/job_scores").set_index("job_id")["score"]
    assert (sc_depois.loc[sc_antes.index] >= sc_antes).all() and (sc_depois.loc[sc_antes.index] > sc_antes).any()
    # curso concluído não vira experiência profissional
    atualizar(lake, "kafka", "concluido", evidencia="certificado")
    k = next(i for itens in servico.planos(grande, agora=AGORA)[0]["classes"].values() for i in itens
             if i["skill_id"] == "kafka")
    assert k["classe"] == "em_desenvolvimento" and k["nivel_perfil"] == "em_desenvolvimento"
    assert list(lake.read("private/study_events")["para"]) == ["demonstrada_em_projeto", "em_estudo"]


def test_plano_separado_por_objetivo(grande):
    grande.profile = copy.deepcopy(grande.profile)
    grande.profile["objetivos"] = [{"id": "eng", "nome": "Engenharia", "familias": ["engenharia_dados"]},
                                   {"id": "bi", "nome": "Análise", "familias": ["analise_dados"]}]
    grande.profile.pop("objetivo", None)
    planos = {p["objetivo_id"]: p for p in servico.planos(grande, agora=AGORA)}
    assert set(planos) == {"eng", "bi"}
    assert planos["eng"]["vagas_alvo"] == 40 and planos["bi"]["vagas_alvo"] == 0
    assert planos["bi"]["amostra_pequena"] and planos["bi"]["prioritarias"] == []


def test_plano_fica_so_na_pasta_privada(grande, tmp_path):
    p = servico.planos(grande, salvar=True, agora=AGORA)[0]
    assert servico.historico()[0]["prioritarias"] == [i["skill_id"] for i in p["prioritarias"]]
    publicar(construir(grande, AGORA, "r1"), tmp_path / "pub", "r1", AGORA)
    publico = b"".join(f.read_bytes() for f in (tmp_path / "pub").rglob("*") if f.is_file())
    assert b"prioritaria" not in publico and b"recomendacao" not in publico
    assert not list(grande.lake.rglob("evolucao"))           # nada de plano dentro do lake (git)

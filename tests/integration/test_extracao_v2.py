"""Etapa 1 no pipeline inteiro: rastreabilidade, versão da taxonomia, separação técnica × não técnica
e camada semântica (ligada só aqui, com codificador falso — nada é baixado)."""
import copy
from datetime import timedelta

import numpy as np

from jobradar import pipeline
from jobradar.publishing import construir
from jobradar.storage import Lake
from jobradar.transformations.skills import Taxonomy

from ..conftest import AGORA


def test_competencias_gravam_metodo_evidencia_e_versao(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake, versao = Lake(settings.lake), Taxonomy(settings.skills).versao
    sk = lake.read("silver/job_skills")
    assert sk["metodo"].isin(["termo", "conceito"]).all()
    assert (sk["taxonomia_versao"] == versao).all() and sk["confianca"].notna().all()
    assert sk["evidencia"].notna().all()
    assert (lake.read("silver/jobs")["taxonomia_versao"] == versao).all()
    # evidência é a frase original da vaga, não o texto normalizado
    ev = sk[(sk["skill_id"] == "kafka")]["evidencia"].iloc[0]
    assert "Kafka" in ev


def test_troca_de_taxonomia_nao_vira_mudanca_de_requisito_e_reextrair_alinha(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    nova = copy.deepcopy(settings.skills)
    nova["versao"] = "9.0.0"
    aws = next(c for c in nova["competencias"] if c["id"] == "aws")
    aws["padroes"] = ["amazon web services"]          # a régua mudou: "AWS (S3, Glue)" deixa de casar
    settings.skills = nova
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    assert rep.requisitos_alterados == 0              # a vaga não mudou; a taxonomia mudou

    r = pipeline.reextrair(settings, agora=AGORA + timedelta(days=1))
    lake = Lake(settings.lake)
    jobs = lake.read("silver/jobs")
    assert r["vagas_reextraidas"] == 0                # r2 já gravou tudo na 9.0.0
    assert (jobs["taxonomia_versao"] == "9.0.0").all()
    assert "aws" not in set(lake.read("gold/skill_monthly")["skill_id"])

    # vaga gravada numa versão antiga é reprocessada, uma vez só
    lake.write("silver/jobs", jobs.assign(taxonomia_versao=None))
    assert pipeline.reextrair(settings)["vagas_reextraidas"] == len(jobs)
    assert pipeline.reextrair(settings)["vagas_reextraidas"] == 0


def test_comportamentais_ficam_fora_da_gold_do_score_e_do_publico(settings, fake):
    fake.gupy[1]["description"] += " Boa comunicação, trabalho em equipe e inglês avançado."
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake, tax = Lake(settings.lake), Taxonomy(settings.skills)
    sk = lake.read("silver/job_skills")
    assert {"comunicacao", "trabalho_equipe", "ingles"} <= set(sk["skill_id"])     # ficam na silver (privado)
    nao_tecnicas = {s.id for s in tax.nao_tecnicas}
    assert not nao_tecnicas & set(lake.read("gold/skill_monthly")["skill_id"])
    assert not any(n in e for e in lake.read("gold/job_scores")["explicacao"] for n in nao_tecnicas)
    docs = construir(settings, AGORA, "r1")
    publicas = {t["id"] for t in docs["skill-trends"]["data"]["taxonomy"]}
    assert publicas == tax.ids_tecnicos
    for item in docs["jobs"]["data"]["items"]:
        assert set(item["skills"]) <= tax.ids_tecnicos


def test_camada_semantica_ligada_e_incremental(settings, fake, monkeypatch):
    def falso(_cfg, _cache=None):
        vocab = ["qualidade", "consist", "pipeline", "ingest", "monitor"]
        return lambda textos: np.array([[float(v in t.lower()) for v in vocab] for t in textos])
    monkeypatch.setattr("jobradar.semantic.modelo.carregar_codificador", falso)
    cfg = copy.deepcopy(settings.skills)
    cfg["extracao"]["semantica"]["ativa"] = True
    cfg["extracao"]["gold_hibrida"] = True
    settings.skills = cfg
    fake.gupy[3]["description"] += " Assegurar a consistência e a qualidade das bases entregues."
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    sem = lake.read("silver/job_skills_semantica")
    assert rep.vagas_enriquecidas == 6                # canônicas com descrição
    assert "qualidade_dados" in set(sem["skill_id"].dropna())
    assert "qualidade_dados" in set(lake.read("gold/skill_monthly")["skill_id"])   # gold híbrida
    rep2 = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    assert rep2.vagas_enriquecidas == 0               # nada mudou: nada é reprocessado

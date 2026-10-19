"""Contrato público, idempotência do e-mail, candidaturas e recomendações."""
import json
from datetime import timedelta

import pandas as pd
import pytest

from jobradar import pipeline
from jobradar.analytics import market
from jobradar.applications import atualizar_candidatura, atualizar_estudo
from jobradar.analytics.selection import inicio_periodo
from jobradar.notifications import candidatas, registrar, renderizar, selecionar
from jobradar.publishing import ContractError, construir, publicar
from jobradar.recommendations import recomendar
from jobradar.scoring import Profile
from jobradar.storage import Lake
from jobradar.transformations.skills import Taxonomy

from ..conftest import AGORA


@pytest.fixture
def populado(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    return settings


def test_contrato_publicado_e_valido_e_sem_dados_privados(populado, tmp_path):
    destino = publicar(construir(populado, AGORA, "r1"), tmp_path / "pub", "r1", AGORA)
    manifest = json.loads((destino / "manifest.json").read_text())
    assert {f["dataset"] for f in manifest["files"]} == {"jobs", "skill-trends", "market-summary"}
    jobs = json.loads((destino / "jobs.json").read_text())
    texto = json.dumps(jobs)
    for proibido in ("descricao", "description", "score", "lacunas", "observacoes", "Requisitos:"):
        assert proibido not in texto
    titulos = [j["title"] for j in jobs["data"]["items"]]
    assert "Engenheiro de Dados Sênior" not in titulos  # fora do filtro de senioridade
    trends = json.loads((destino / "skill-trends.json").read_text())
    assert trends["data"]["current"]["low_sample"] is True  # amostra pequena é sinalizada


def test_falha_de_validacao_mantem_versao_anterior(populado, tmp_path):
    pub = tmp_path / "pub"
    publicar(construir(populado, AGORA, "r1"), pub, "r1", AGORA)
    anterior = (pub / "v1" / "manifest.json").read_text()
    docs = construir(populado, AGORA, "r2")
    docs["jobs"]["data"]["items"][0]["description"] = "vazamento"
    with pytest.raises(ContractError):
        publicar(docs, pub, "r2", AGORA)
    assert (pub / "v1" / "manifest.json").read_text() == anterior


def test_email_e_idempotente(populado):
    lake = Lake(populado.lake)
    vagas = candidatas(populado, AGORA)
    assert vagas and all(v.score >= populado.filtros["score_minimo"] for v in vagas)
    registrar(lake, vagas, "r1", AGORA)
    assert candidatas(populado, AGORA) == []  # reexecução não reenvia
    pipeline.run(populado, [], run_id="r2", agora=AGORA + timedelta(hours=1))
    assert candidatas(populado, AGORA) == []


def test_envio_que_falha_nao_registra(populado, monkeypatch):
    from jobradar import cli

    def quebra(*a, **k):
        raise ConnectionError("smtp fora do ar")
    monkeypatch.setattr("jobradar.notifications.enviar_smtp", quebra)
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", quebra)

    class A:
        dry_run, html_out, run_id, pular_se_vazio = False, None, "r1", False
    assert cli.cmd_notify(A, populado) == cli.EXIT_NOTIFICACAO
    assert Lake(populado.lake).read("meta/notifications").empty


def test_pular_se_vazio_nao_envia_sem_vaga_nova(populado, monkeypatch):
    from jobradar import cli
    enviados = []
    monkeypatch.setattr("jobradar.notifications.enviar_smtp", lambda *a, **k: enviados.append(a))
    monkeypatch.setattr(cli, "utcnow", lambda: AGORA)
    registrar(Lake(populado.lake), candidatas(populado, AGORA), "r1", AGORA)

    class A:
        dry_run, html_out, run_id, pular_se_vazio = False, None, "r2", True
    assert cli.cmd_notify(A, populado) == 0
    assert enviados == []
    A.pular_se_vazio = False
    assert cli.cmd_notify(A, populado) == 0
    assert len(enviados) == 1  # sem a flag vale enviar_quando_vazio (true): manda o e-mail vazio


def test_email_separa_publicadas_ontem_e_hoje_das_encontradas_atrasadas(populado):
    vagas = candidatas(populado, AGORA)
    inicio = inicio_periodo("ontem_e_hoje", AGORA)
    do_dia = [v for v in vagas if v.secao == "do_dia"]
    atrasadas = [v for v in vagas if v.secao == "atrasada"]
    assert do_dia and atrasadas
    assert all(pd.Timestamp(v.job["publicada_em"]) >= inicio for v in do_dia)
    assert all(pd.Timestamp(v.job["publicada_em"]) < inicio for v in atrasadas)
    assert [v.score for v in do_dia] == sorted((v.score for v in do_dia), reverse=True)
    assert vagas.index(do_dia[-1]) < vagas.index(atrasadas[0])  # do dia primeiro


def test_email_cartoes_para_as_melhores_e_lista_compacta_para_o_resto(populado):
    vagas = candidatas(populado, AGORA)
    n_dia = sum(v.secao == "do_dia" for v in vagas)
    assunto, corpo, texto = renderizar(vagas, AGORA, {}, [], cartoes=1)
    assert f"{n_dia} vaga(s) publicada(s) ontem e hoje" in assunto and "encontrada(s) agora" in assunto
    assert corpo.count("Abrir vaga para se candidatar") == 1
    assert "Encontradas agora, publicadas antes" in corpo and "Demais publicadas" in corpo
    assert all(v.job["url"] in texto for v in vagas)


def test_email_respeita_max_vagas_e_avisa_o_excedente(populado):
    populado.sources["notificacoes"]["max_vagas"] = 1
    vagas, excedentes = selecionar(populado, AGORA)
    assert len(vagas) == 1 and excedentes >= 1
    _, corpo, _ = renderizar(vagas, AGORA, {}, [], excedentes=excedentes)
    assert f"Mais {excedentes} vaga(s) não couberam" in corpo


def test_email_html_escapa_conteudo_de_terceiros(populado):
    vagas = candidatas(populado, AGORA)
    vagas[0].job["titulo"] = "<script>alert(1)</script>"
    _, corpo, texto = renderizar(vagas, AGORA, {}, [])
    assert "<script>" not in corpo and "&lt;script&gt;" in corpo
    assert "não é probabilidade de contratação" in corpo


def test_candidatura_registra_historico(populado):
    lake = Lake(populado.lake)
    jid = lake.read("silver/jobs")["job_id"].iloc[0]
    atualizar_candidatura(lake, jid, "salva")
    atualizar_candidatura(lake, jid, "candidatado", "enviei o currículo v3")
    ev = lake.read("private/application_events")
    assert ev[["de", "para"]].values.tolist() == [["nova", "salva"], ["salva", "candidatado"]]
    with pytest.raises(ValueError):
        atualizar_candidatura(lake, jid, "contratada!")


def test_progresso_de_estudo(populado):
    lake = Lake(populado.lake)
    atualizar_estudo(lake, "databricks", "em_andamento", inicio="2026-10-01")
    atualizar_estudo(lake, "databricks", "concluido", conclusao="2026-12-10", evidencia="certificado")
    p = lake.read("private/study_progress").iloc[0]
    assert (p["status"], p["inicio"], p["conclusao"]) == ("concluido", "2026-10-01", "2026-12-10")


def _populacao_grande(settings, fake, n_por_janela=35):
    """Gera vagas sintéticas em duas janelas para testar regras de confiança."""
    base = []
    for i in range(n_por_janela):
        base.append({"id": 5000 + i, "name": "Engenheiro de Dados Pleno", "careerPageName": f"Empresa {i}",
                     "workplaceType": "remote", "jobUrl": f"https://e{i}.gupy.io/job/{i}",
                     "publishedDate": None, "description": "Requisitos: SQL e Python" + (" e Kafka" if i % 2 else "")})
    fake.gupy = base
    pipeline.run(settings, fake.collectors(settings), run_id="antigo", agora=AGORA - timedelta(days=120))
    novas = []
    for i in range(n_por_janela):
        novas.append({"id": 6000 + i, "name": "Engenheiro de Dados Júnior", "careerPageName": f"Outra {i}",
                      "workplaceType": "remote", "jobUrl": f"https://o{i}.gupy.io/job/{i}",
                      "publishedDate": None, "description": "Requisitos: SQL, Python, Kafka e dbt"})
    fake.gupy = novas
    pipeline.run(settings, fake.collectors(settings), run_id="novo", agora=AGORA)


def test_recomendacoes_com_amostra_suficiente_e_tendencia(settings, fake):
    _populacao_grande(settings, fake)
    recs = {r.skill_id: r for r in recomendar(market.carregar(Lake(settings.lake)), Profile.from_dict(settings.profile),
                                                Taxonomy(settings.skills), settings.scoring["recomendacoes"],
                                                settings.filtros, AGORA)}
    assert recs["kafka"].classe == "lacuna_prioritaria"        # nao_dominada + 100% das vagas recentes
    assert recs["kafka"].tendencia == "alta" and recs["kafka"].variacao_pp > 40
    assert recs["dbt"].classe == "lacuna_prioritaria"          # sem evidência, mas muito pedida
    assert recs["sql"].classe == "consolidada"
    assert recs["databricks"].classe == "em_desenvolvimento"
    assert "não significa que você não saiba" in recs["dbt"].justificativa


def test_recomendacao_com_amostra_pequena_nunca_vira_prioridade(populado):
    recs = recomendar(market.carregar(Lake(populado.lake)), Profile.from_dict(populado.profile),
                      Taxonomy(populado.skills), populado.scoring["recomendacoes"], populado.filtros, AGORA)
    assert not [r for r in recs if r.classe == "lacuna_prioritaria"]
    assert all(r.tendencia == "inconclusiva" for r in recs)

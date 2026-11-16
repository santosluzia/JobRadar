"""Etapa 5 — JobRadar — Seu Radar Profissional: configuração, horário, conteúdo, duplicidade, falhas,
ação do dia sem repetição e privacidade. O SMTP é sempre falso."""
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from jobradar import pipeline
from jobradar.cli import main
from jobradar.curriculo import servico as cv_servico
from jobradar.evolucao import resumo_cv
from jobradar.evolucao.progresso import atualizar
from jobradar.notifications import radar
from jobradar.storage import Lake
from jobradar.transformations.skills import Taxonomy

from ..conftest import AGORA, iso   # AGORA = 16/10/2026 07:00 em SP (turno da manhã)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "curriculo_ficticio.txt"
FREQ = {"AWS": 32, "Airflow": 28, "dbt": 24, "Kafka": 20, "Docker": 16, "Terraform": 12}


def _vagas(publicadas_agora: int = 6):
    vagas = []
    for i in range(40):
        extras = [k for k, n in FREQ.items() if i < n]
        vagas.append({"id": 8000 + i, "name": "Engenheiro de Dados Júnior", "careerPageName": f"Empresa {i}",
                      "workplaceType": "remote", "jobUrl": f"https://r{i}.gupy.io/job/{i}",
                      "publishedDate": iso(0.1) if i < publicadas_agora else None,
                      "description": "Requisitos: SQL, Python, " + ", ".join(extras) + "."})
    return vagas


@pytest.fixture
def radar_lake(settings, fake):
    fake.gupy = _vagas()
    fake.adzuna, fake.greenhouse = [], {"jobs": []}
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    settings.filtros["score_minimo"] = 0
    return settings


@pytest.fixture
def smtp(monkeypatch):
    enviados = []
    falso = lambda s, a, h, t: enviados.append((a, h, t))  # noqa: E731
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", falso)
    monkeypatch.setattr("jobradar.notifications.enviar_smtp", falso)     # o notify comum importa daqui
    return enviados


def _config(s, **kw):
    p = s.lake / "private" / "radar.yaml"
    p.write_text(yaml.safe_dump(kw), encoding="utf-8")


# ---------------------------------------------------------------- configuração e horário
def test_configuracao_padrao_e_invalida(tmp_path):
    assert radar.carregar_config(tmp_path).turno == 1                  # 06:00 → manhã
    assert radar.RadarConfig(horario="18:10").turno == 3 and radar.RadarConfig(horario="23:50").turno == 0
    for ruim in ({"horario": "25:00"}, {"dias_semana": []}, {"frequencia": "mensal"}, {"limite": 3},
                 {"limite_itens": 0}):
        with pytest.raises(ValidationError):
            radar.RadarConfig.model_validate(ruim)


@pytest.mark.parametrize("cfg,quando,motivo", [
    ({"ativo": False}, AGORA, "desativado"),
    ({"horario": "18:00"}, AGORA, "fora do horário"),
    ({"dias_semana": ["seg"]}, AGORA, "não está em dias_semana"),                   # 16/10/2026 é sexta
    ({"frequencia": "dias_uteis"}, AGORA + timedelta(days=1), "fim de semana"),
])
def test_quando_o_radar_nao_sai(cfg, quando, motivo):
    ok, m = radar.devido(radar.RadarConfig(**cfg), quando, radar.turno_de(quando), pd.DataFrame(), "principal")
    assert not ok and motivo in m


# ---------------------------------------------------------------- conteúdo e envio
def test_radar_completo_com_quatro_blocos(radar_lake, smtp):
    r = radar.enviar(radar_lake, AGORA, "r1", turno=1)
    assert r["enviado"] and len(smtp) == 1
    assunto, corpo, texto = smtp[0]
    assert assunto.startswith("JobRadar — Seu Radar Profissional")
    for bloco in ("1. O que mudou no mercado", "2. Como isso se relaciona", "4. Recomendação do dia"):
        assert bloco in texto
    assert "vagas-alvo analisadas" in texto and "Amostra insuficiente para tendência" in texto   # sem tendência inventada
    assert "https://r0.gupy.io/job/0" in corpo                          # links das vagas novas
    assert len(corpo.encode()) < 100_000                                 # cabe no Gmail
    lake = Lake(radar_lake.lake)
    env = lake.read("private/radar_envios")
    assert list(env["status"]) == ["enviado"] and env["acao_tipo"].notna().all()
    assert len(lake.read("meta/notifications")) == r["vagas"] > 0       # vagas do Radar não voltam no e-mail comum


def test_duplicidade_e_falha_de_envio(radar_lake, smtp, monkeypatch):
    def falha(*a):
        raise ConnectionError("smtp fora")
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", falha)
    with pytest.raises(ConnectionError):
        radar.enviar(radar_lake, AGORA, "r1", turno=1)
    lake = Lake(radar_lake.lake)
    assert list(lake.read("private/radar_envios")["status"]) == ["falha"]
    assert lake.read("meta/notifications").empty                       # nada registrado: tenta de novo
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", lambda *a: smtp.append(a))
    assert radar.enviar(radar_lake, AGORA + timedelta(hours=1), "r2", turno=1)["enviado"]
    r = radar.enviar(radar_lake, AGORA + timedelta(hours=2), "r3", turno=1)
    assert not r["enviado"] and "já enviado" in r["motivo"] and len(smtp) == 1


def test_acao_do_dia_nao_se_repete_entre_dias(radar_lake, smtp):
    lake = Lake(radar_lake.lake)
    acoes = []
    for d in range(3):
        radar.enviar(radar_lake, AGORA + timedelta(days=d), f"r{d}", turno=1)
        acoes.append(tuple(lake.read("private/radar_envios").iloc[-1][["acao_tipo", "acao_skill"]]))
    assert len(set(acoes)) == 3                                         # três dias, três ações diferentes


def _item(sid, classe, progresso=None, prioridade=0.5, nivel_cv="sem_evidencia", pct=30.0):
    return {"skill_id": sid, "nome": sid.upper(), "classe": classe, "progresso": progresso, "prioridade": prioridade,
            "nivel_curriculo": nivel_cv, "pct": pct, "baixa_relevancia": False}


def test_acao_do_dia_respeita_o_progresso():
    vazio = pd.DataFrame(columns=["enviado_em", "acao_tipo", "acao_skill"])
    plano = {"prioritarias": [_item("aws", "prioritaria", prioridade=0.6)],
             "classes": {"em_desenvolvimento": [], "declarada_sem_evidencia": []}}
    a = radar.escolher_acao(plano, {}, vazio, com_resumo_cv=False)
    assert (a["tipo"], a["skill_id"]) == ("estudar", "aws")
    # em estudo → prática (nunca "estude" de novo); em prática → publicar o projeto
    for progresso, tipo in (("em_estudo", "atividade"), ("em_pratica", "projeto")):
        plano = {"prioritarias": [], "classes": {"em_desenvolvimento": [_item("aws", "em_desenvolvimento", progresso)],
                                                 "declarada_sem_evidencia": []}}
        assert radar.escolher_acao(plano, {}, vazio, com_resumo_cv=False)["tipo"] == tipo
    # já recomendada no período → outra ação; sem alternativa → nenhuma (não repete)
    plano = {"prioritarias": [_item("aws", "prioritaria", prioridade=0.6), _item("dbt", "prioritaria", prioridade=0.4)],
             "classes": {"em_desenvolvimento": [], "declarada_sem_evidencia": []}}
    hist = pd.DataFrame([{"enviado_em": AGORA, "acao_tipo": "estudar", "acao_skill": "aws"}])
    assert radar.escolher_acao(plano, {}, hist, com_resumo_cv=False)["skill_id"] == "dbt"
    hist = pd.concat([hist, pd.DataFrame([{"enviado_em": AGORA, "acao_tipo": "estudar", "acao_skill": "dbt"}])])
    assert radar.escolher_acao(plano, {}, hist, com_resumo_cv=False) is None
    # "documentar" só com o resumo do currículo (sem ele não dá para saber o que o currículo mostra)
    plano = {"prioritarias": [], "classes": {"em_desenvolvimento": [],
                                             "declarada_sem_evidencia": [_item("sql", "declarada_sem_evidencia")]}}
    assert radar.escolher_acao(plano, {}, vazio, com_resumo_cv=False) is None
    assert radar.escolher_acao(plano, {}, vazio, com_resumo_cv=True)["tipo"] == "documentar"


def test_notify_no_turno_do_radar_envia_o_radar(radar_lake, smtp, monkeypatch):
    monkeypatch.setattr("jobradar.cli.utcnow", lambda: AGORA)
    monkeypatch.setattr("jobradar.cli.carregar", lambda lake=None: radar_lake)
    with pytest.raises(SystemExit) as fim:
        main(["notify", "--turno", "manha"])
    assert fim.value.code == 0 and smtp[-1][0].startswith("JobRadar — Seu Radar Profissional")
    with pytest.raises(SystemExit):
        main(["notify", "--turno", "tarde"])                            # outro turno: e-mail comum de vagas
    assert len(smtp) == 2 and smtp[1][0].startswith("JobRadar 16/10/2026")


def test_resumo_do_curriculo_so_tem_niveis_e_log_so_contagens(radar_lake, smtp, capsys):
    canario = "CANARIO-RADAR-91d2"
    texto = FIXTURE.read_text(encoding="utf-8").replace("Empresa Fictícia S.A.", f"Empresa {canario}")
    cv = cv_servico.importar(texto.encode(), "cv.txt", Taxonomy(radar_lake.skills))
    destino = resumo_cv.gravar(radar_lake.lake, cv.versao_id, cv.criado_em.isoformat(), cv.taxonomia_versao, cv.niveis())
    conteudo = destino.read_text(encoding="utf-8")
    assert canario not in conteudo and "Empresa" not in conteudo and "python" in conteudo
    with pytest.raises(ValueError):
        resumo_cv.gravar(radar_lake.lake, "v", "d", "t", {"python": "expert"})
    r = radar.enviar(radar_lake, AGORA, "r1", turno=1)
    assert r["enviado"]
    assert canario not in smtp[0][1]                                     # nem no e-mail: o resumo não tem texto
    lake_bytes = b"".join(p.read_bytes() for p in radar_lake.lake.rglob("*") if p.is_file())
    assert canario.encode() not in lake_bytes
    assert resumo_cv.remover(radar_lake.lake) and resumo_cv.carregar(radar_lake.lake) is None


def test_radar_nao_le_a_pasta_privada_local():
    """No CI não existe ~/.jobradar: o Radar só pode usar o RESUMO de níveis que você compartilhou."""
    fonte = (Path(__file__).resolve().parents[2] / "src" / "jobradar" / "notifications" / "radar.py").read_text(encoding="utf-8")
    assert "JOBRADAR_HOME" not in fonte and "versoes" not in fonte and "pasta_privada" not in fonte


def test_banco_de_talentos_nunca_vira_oportunidade(radar_lake):
    """Banco de Talentos é cadastro de currículos, não vaga: o bloco 3 passa para a próxima candidata."""
    cfg = radar.carregar_config(radar_lake.lake)
    vazio = Lake(radar_lake.lake).read("private/radar_envios")
    antes = radar.montar(radar_lake, AGORA, cfg, vazio)["oportunidade"]
    assert antes, "o cenário precisa ter uma oportunidade para o teste fazer sentido"
    lake = Lake(radar_lake.lake)
    jobs = lake.read("silver/jobs")
    jobs.loc[jobs["job_id"] == antes["job_id"], "titulo"] = "[Banco de Talentos] " + antes["titulo"]
    lake.write("silver/jobs", jobs)
    depois = radar.montar(radar_lake, AGORA, cfg, vazio)["oportunidade"]
    assert depois is None or (depois["job_id"] != antes["job_id"] and not radar.banco_de_talentos(depois["titulo"]))


@pytest.mark.parametrize("titulo, esperado", [
    ("[Banco de Talentos] Engenheiro de Dados", True), ("Banco de talento - Dados", True),
    ("Data Engineer - Talent Pool", True), ("Talent Community | Analytics", True),
    ("Engenheiro de Dados Pleno", False), ("Analista de Banco de Dados", False), (None, False)])
def test_reconhece_banco_de_talentos(titulo, esperado):
    assert radar.banco_de_talentos(titulo) is esperado

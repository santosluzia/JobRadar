"""Etapa 6 — Relatório Semanal de Evolução Profissional: 10 seções, 3 oportunidades, comparações só com
amostra, acompanhamento da semana anterior, versões do resumo do currículo, duplicidade, falhas e privacidade."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobradar import pipeline
from jobradar.cli import main
from jobradar.evolucao import resumo_cv
from jobradar.evolucao.progresso import atualizar
from jobradar.notifications import radar, semanal
from jobradar.storage import Lake

from ..conftest import AGORA, iso   # AGORA = sexta, 16/10/2026, 07:00 em SP

FREQ = {"AWS": 32, "Airflow": 28, "dbt": 24, "Kafka": 20, "Docker": 16, "Terraform": 12}
SECOES = ["1. Resumo do mercado", "2. Vagas analisadas", "3. Competências mais exigidas", "4. Competências em crescimento",
          "5. Combinações de competências relevantes", "6. Comparação com o seu perfil", "7. Lacunas prioritárias", "8. Melhorias recomendadas no currículo",
          "9. Projetos sugeridos", "10. Progresso das recomendações anteriores", "As 3 principais oportunidades"]


@pytest.fixture
def lake_semanal(settings, fake):
    fake.gupy = [{"id": 9000 + i, "name": "Engenheiro de Dados Júnior", "careerPageName": f"Empresa {i}",
                  "workplaceType": "remote", "jobUrl": f"https://s{i}.gupy.io/job/{i}", "publishedDate": iso(1),
                  "description": "Requisitos: SQL, Python, " + ", ".join(k for k, n in FREQ.items() if i < n) + "."}
                 for i in range(40)]
    fake.adzuna, fake.greenhouse = [], {"jobs": []}
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    (settings.lake / "private" / "radar.yaml").write_text(
        yaml.safe_dump({"semanal": {"dia": "sex", "horario": "06:00"}}), encoding="utf-8")
    return settings


@pytest.fixture
def smtp(monkeypatch):
    enviados = []
    falso = lambda s, a, h, t: enviados.append((a, h, t))  # noqa: E731
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", falso)
    monkeypatch.setattr("jobradar.notifications.enviar_smtp", falso)
    return enviados


def test_configuracao_e_quando_sai():
    cfg = radar.RadarConfig()
    assert (cfg.semanal.dia, cfg.semanal.turno) == ("seg", 2)              # segunda, 12:00
    with pytest.raises(ValidationError):
        radar.RadarConfig.model_validate({"semanal": {"dia": "segunda"}})
    vazio = semanal.pd.DataFrame()
    assert not semanal.devido(cfg, AGORA, 2, vazio, "x")[0]                 # sexta: não é segunda
    sexta = radar.RadarConfig(semanal={"dia": "sex", "horario": "06:00"})
    assert semanal.devido(sexta, AGORA, 1, vazio, "x")[0]
    assert not semanal.devido(sexta, AGORA, 2, vazio, "x")[0]               # turno errado
    assert not semanal.devido(radar.RadarConfig(semanal={"ativo": False}), AGORA, 2, vazio, "x")[0]


def test_relatorio_com_dez_secoes_e_tres_oportunidades(lake_semanal, smtp):
    r = semanal.enviar(lake_semanal, AGORA, "r1", turno=1)
    assert r["enviado"] and len(smtp) == 1
    assunto, corpo, texto = smtp[0]
    assert assunto.startswith("JobRadar — Relatório Semanal de Evolução Profissional")
    for s in SECOES:
        assert s in texto, s
    assert texto.count("   Projeto:") <= 3                                  # 3 oportunidades, não uma lista
    assert "amostra insuficiente" in texto                                  # semana anterior vazia: sem comparação
    assert "mercado" in texto and len(corpo.encode()) < 100_000
    hist = Lake(lake_semanal.lake).read("private/relatorios_semanais")
    assert list(hist["status"]) == ["enviado"] and len(json.loads(hist.iloc[0]["oportunidades"])) == 3
    # um por semana
    r2 = semanal.enviar(lake_semanal, AGORA + timedelta(hours=1), "r2", turno=1)
    assert not r2["enviado"] and "já enviado" in r2["motivo"]


def test_semana_seguinte_acompanha_progresso_e_versoes_do_curriculo(lake_semanal, smtp):
    lake = Lake(lake_semanal.lake)
    resumo_cv.gravar(lake_semanal.lake, "v1", "2026-10-01", "2.0.0", {"python": "declarada", "sql": "comprovada"})
    semanal.enviar(lake_semanal, AGORA, "r1", turno=1)
    primeira = json.loads(lake.read("private/relatorios_semanais").iloc[0]["oportunidades"])
    atualizar(lake, primeira[0], "em_estudo", agora=AGORA + timedelta(days=2))           # avançou numa delas
    resumo_cv.gravar(lake_semanal.lake, "v2", "2026-10-20", "2.0.0", {"python": "comprovada", "sql": "comprovada",
                                                                      "docker": "projeto"})
    hist = lake.read("private/relatorios_semanais")
    r = semanal.montar(lake_semanal, AGORA + timedelta(days=7), radar.carregar_config(lake_semanal.lake), hist)
    prog = {x["nome"].lower(): x for x in r["s10_progresso"] if x["origem"] == "relatorio anterior"}
    assert len(prog) == 3 and sum(x["avancou"] for x in prog.values()) == 1
    cmp_ = r["s8_curriculo"]["comparacao"]
    assert cmp_["subiram"] == {"python": ["declarada", "comprovada"]} and cmp_["novas"] == {"docker": "projeto"}
    repetidas = [o for o in r["oportunidades"] if o["skill_id"] in primeira]
    assert repetidas and all(o["semanas_seguidas"] == 2 for o in repetidas)
    assert r["s6_perfil"]["antes"] is not None                              # compara com a semana passada


def test_falha_de_envio_fica_registrada_e_nao_conta(lake_semanal, smtp, monkeypatch):
    def falha(*a):
        raise ConnectionError("smtp fora")
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", falha)
    with pytest.raises(ConnectionError):
        semanal.enviar(lake_semanal, AGORA, "r1", turno=1)
    assert list(Lake(lake_semanal.lake).read("private/relatorios_semanais")["status"]) == ["falha"]
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", lambda *a: smtp.append(a))
    assert semanal.enviar(lake_semanal, AGORA + timedelta(hours=1), "r2", turno=1)["enviado"]


def test_notify_envia_o_semanal_no_turno_dele_sem_tirar_o_email_do_turno(lake_semanal, smtp, monkeypatch):
    monkeypatch.setattr("jobradar.cli.utcnow", lambda: AGORA)
    monkeypatch.setattr("jobradar.cli.carregar", lambda lake=None: lake_semanal)
    (lake_semanal.lake / "private" / "radar.yaml").write_text(
        yaml.safe_dump({"ativo": False, "semanal": {"dia": "sex", "horario": "06:00"}}), encoding="utf-8")
    with pytest.raises(SystemExit) as fim:
        main(["notify", "--turno", "manha"])
    assert fim.value.code == 0
    assuntos = [a for a, *_ in smtp]
    assert any(a.startswith("JobRadar — Relatório Semanal") for a in assuntos)
    assert any(a.startswith("JobRadar 16/10/2026") for a in assuntos)      # o e-mail do turno continua


def test_semanal_nao_le_a_pasta_privada_local():
    fonte = (Path(__file__).resolve().parents[2] / "src" / "jobradar" / "notifications" / "semanal.py").read_text(encoding="utf-8")
    assert "JOBRADAR_HOME" not in fonte and "versoes." not in fonte and "pasta_privada" not in fonte

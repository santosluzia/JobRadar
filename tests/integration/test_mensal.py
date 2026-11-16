"""Etapa 7 — Diagnóstico mensal no fluxo: retrato gravado uma vez por mês, e-mail com as 7 perguntas,
falha de envio sem perder o retrato, prévia sem gravar e privacidade."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from jobradar import pipeline
from jobradar.notifications import mensal
from jobradar.storage import Lake

from ..conftest import AGORA, iso

DIA_1 = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)   # 01/11/2026, 12:00 em SP (turno da tarde)


@pytest.fixture
def lake_mensal(settings, fake):
    fake.gupy = [{"id": 9500 + i, "name": "Engenheiro de Dados Júnior", "careerPageName": f"E{i}",
                  "workplaceType": "remote", "jobUrl": f"https://m{i}.gupy.io/job/{i}", "publishedDate": iso(1),
                  "description": "Requisitos: SQL, Python" + (", AWS" if i % 2 else "") + "."} for i in range(40)]
    fake.adzuna, fake.greenhouse = [], {"jobs": []}
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=DIA_1 - timedelta(days=3))
    return settings


@pytest.fixture
def smtp(monkeypatch):
    enviados = []
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", lambda s, a, h, t: enviados.append((a, h, t)))
    return enviados


def test_retrato_e_email_uma_vez_por_mes(lake_mensal, smtp):
    r = mensal.enviar(lake_mensal, DIA_1, "r1", turno=2)
    assert r["enviado"] and r["gerado"] and len(smtp) == 1
    assunto, corpo, texto = smtp[0]
    assert assunto.startswith("JobRadar — Diagnóstico Mensal")
    for pergunta in mensal.PERGUNTAS:
        assert pergunta in texto
    assert "garantia de empregabilidade" in texto
    hist = Lake(lake_mensal.lake).read("private/diagnosticos_mensais")
    assert list(hist["mes"]) == ["2026-10"] and list(hist["status"]) == ["enviado"]
    assert "niveis_perfil" in hist.iloc[0]["retrato"] and "Requisitos" not in hist.iloc[0]["retrato"]   # só agregados
    r2 = mensal.enviar(lake_mensal, DIA_1 + timedelta(hours=1), "r2", turno=2)
    assert not r2["enviado"] and "já gerado" in r2["motivo"]


def test_email_desativado_ainda_grava_o_retrato(lake_mensal, smtp):
    (lake_mensal.lake / "private" / "radar.yaml").write_text(yaml.safe_dump({"mensal": {"ativo": False}}), encoding="utf-8")
    r = mensal.enviar(lake_mensal, DIA_1, "r1", turno=2)
    assert r["gerado"] and not r["enviado"] and smtp == []
    assert list(Lake(lake_mensal.lake).read("private/diagnosticos_mensais")["status"]) == ["gerado"]


def test_falha_de_envio_mantem_o_retrato_e_tenta_de_novo(lake_mensal, smtp, monkeypatch):
    def falha(*a):
        raise ConnectionError("smtp fora")
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", falha)
    with pytest.raises(RuntimeError, match="retrato gravado"):
        mensal.enviar(lake_mensal, DIA_1, "r1", turno=2)
    assert list(Lake(lake_mensal.lake).read("private/diagnosticos_mensais")["status"]) == ["falha"]
    monkeypatch.setattr("jobradar.notifications.email.enviar_smtp", lambda *a: smtp.append(a))
    assert mensal.enviar(lake_mensal, DIA_1 + timedelta(hours=1), "r2", turno=2)["enviado"]


def test_fora_do_dia_e_previa_nao_gravam(lake_mensal, smtp, tmp_path):
    assert not mensal.enviar(lake_mensal, DIA_1 + timedelta(days=1), "r1", turno=2)["gerado"]
    r = mensal.enviar(lake_mensal, DIA_1, "r1", turno=2, dry_run=True, html_out=tmp_path / "m.html")
    assert not r["gerado"] and (tmp_path / "m.html").exists() and smtp == []
    assert Lake(lake_mensal.lake).read("private/diagnosticos_mensais").empty


def test_segundo_mes_compara_com_o_primeiro(lake_mensal, smtp, fake):
    mensal.enviar(lake_mensal, DIA_1, "r1", turno=2)
    # mês seguinte: vagas novas, agora pedindo mais AWS e dbt (o mercado mudou)
    fake.gupy = [{"id": 9700 + i, "name": "Engenheiro de Dados Júnior", "careerPageName": f"N{i}",
                  "workplaceType": "remote", "jobUrl": f"https://n{i}.gupy.io/job/{i}", "publishedDate": None,
                  "description": "Requisitos: SQL, AWS, dbt."} for i in range(40)]
    pipeline.run(lake_mensal, fake.collectors(lake_mensal), run_id="r2", agora=DIA_1 + timedelta(days=20))
    hist = Lake(lake_mensal.lake).read("private/diagnosticos_mensais")
    r = mensal.montar(lake_mensal, DIA_1 + timedelta(days=30), hist)
    q1 = r["diagnosticos"][0]["q1_aderencia"]
    assert r["diagnosticos"][0]["anterior"] == "2026-10" and q1["variacao"] is not None
    assert q1["efeito_mercado"] + q1["efeito_perfil"] == pytest.approx(q1["variacao"], abs=0.11)


def test_mensal_nao_le_a_pasta_privada_local():
    raiz = Path(__file__).resolve().parents[2] / "src" / "jobradar"
    for arq in ("notifications/mensal.py", "evolucao/mensal.py"):
        fonte = (raiz / arq).read_text(encoding="utf-8")
        assert "JOBRADAR_HOME" not in fonte and "versoes" not in fonte and "pasta_privada" not in fonte

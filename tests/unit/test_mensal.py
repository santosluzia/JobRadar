"""Etapa 7 — regras do diagnóstico mensal (puras)."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from jobradar.evolucao import mensal as m

PESOS = {"profissional": 1.0, "projeto": 0.75, "em_desenvolvimento": 0.4, "nao_dominada": 0.0, "sem_evidencia": 0.0}
PESOS_CV = {"comprovada": 1.0, "projeto": 0.75, "declarada": 0.5, "parcial": 0.4}
NOMES = {"sql": "SQL", "aws": "AWS", "dbt": "dbt", "kafka": "Kafka"}


def _retrato(mes, demanda, niveis, pct, prioritarias, n=40, cv=None, decl=0, gerado="2026-11-01T15:00:00+00:00"):
    return {"mes": mes, "gerado_em": gerado, "objetivo_id": "eng", "objetivo": "Engenharia", "vagas_mes": n,
            "amostra_pequena": n < 30, "aderencia_perfil": None, "aderencia_curriculo": None, "demanda": demanda,
            "pct": pct, "pct_requisito": pct, "niveis_perfil": niveis, "niveis_curriculo": cv or {},
            "classes": {"declarada_sem_evidencia": ["x"] * decl}, "prioritarias": prioritarias, "projetos": [], "progresso": {}}


def test_mes_de_referencia():
    assert m.mes_referencia(datetime(2026, 12, 1, 15, tzinfo=timezone.utc)) == "2026-11"   # dia 1 fecha o anterior
    assert m.mes_referencia(datetime(2026, 12, 15, 15, tzinfo=timezone.utc)) == "2026-12"


def test_decomposicao_soma_a_variacao_total():
    antes = _retrato("2026-10", {"sql": 0.5, "aws": 0.5}, {"sql": "profissional"}, {"sql": 50, "aws": 50}, ["aws"])
    agora = _retrato("2026-11", {"sql": 0.2, "aws": 0.6, "dbt": 0.2}, {"sql": "profissional", "aws": "projeto"},
                     {"sql": 20, "aws": 60, "dbt": 20}, ["dbt"])
    q1 = m.diagnostico(agora, antes, PESOS, PESOS_CV, NOMES, pd.DataFrame(), 30)["q1_aderencia"]
    assert q1["antes"] == 50.0                                   # só SQL coberto, metade da demanda
    assert q1["efeito_mercado"] == pytest.approx(20.0 - 50.0)    # mesmo perfil, mercado pede menos SQL
    assert q1["efeito_perfil"] == pytest.approx(65.0 - 20.0)     # AWS em projeto cobre 0,75 × 0,6
    assert q1["efeito_mercado"] + q1["efeito_perfil"] == pytest.approx(q1["variacao"])


def test_respostas_com_e_sem_mes_anterior():
    eventos = pd.DataFrame([{"skill_id": "aws", "para": "em_estudo", "em": pd.Timestamp("2026-11-10", tz="UTC")}])
    primeiro = m.diagnostico(_retrato("2026-11", {"sql": 1}, {}, {"sql": 50}, ["aws"]), None, PESOS, PESOS_CV, NOMES,
                             eventos, 30)
    assert "primeiro retrato" in primeiro["q1_aderencia"]["aviso"] and "aviso" in primeiro["q4_exigencias"]
    assert "sem resumo" in primeiro["q6_curriculo"]["aviso"] and "garantia" in primeiro["aviso"]
    antes = _retrato("2026-10", {"sql": 1}, {"aws": "nao_dominada"}, {"sql": 40, "kafka": 20}, ["aws", "kafka"],
                     cv={"sql": "declarada"}, decl=3)
    agora = _retrato("2026-11", {"sql": 1}, {"aws": "em_desenvolvimento"}, {"sql": 50, "dbt": 10}, ["aws", "dbt"],
                     cv={"sql": "comprovada"}, decl=1)
    d = m.diagnostico(agora, antes, PESOS, PESOS_CV, NOMES, eventos, 30)
    assert d["q2_desenvolvidas"]["niveis_que_subiram"] == [{"nome": "AWS", "de": "nao_dominada", "para": "em_desenvolvimento"}]
    assert d["q2_desenvolvidas"]["progresso_registrado"] == [{"nome": "AWS", "para": "em_estudo"}]
    assert [x["nome"] for x in d["q3_lacunas"]["continuam"]] == ["AWS"]
    assert d["q3_lacunas"]["resolvidas"] == ["Kafka"] and d["q3_lacunas"]["novas"] == ["dbt"]
    q4 = d["q4_exigencias"]
    assert {x["nome"] for x in q4["subiram"]} == {"SQL", "dbt"} and [x["nome"] for x in q4["cairam"]] == ["Kafka"]
    q6 = d["q6_curriculo"]
    assert q6["variacao"] == 50.0 and (q6["declaradas_antes"], q6["declaradas_sem_evidencia"]) == (3, 1)


def test_sem_amostra_nao_compara_exigencias():
    antes = _retrato("2026-10", {"sql": 1}, {}, {"sql": 40}, [], n=12)
    d = m.diagnostico(_retrato("2026-11", {"sql": 1}, {}, {"sql": 80}, []), antes, PESOS, PESOS_CV, NOMES, pd.DataFrame(), 30)
    assert "sem amostra" in d["q4_exigencias"]["aviso"]


def test_objetivos_mais_compativeis_poe_amostra_pequena_por_ultimo():
    r = m.objetivos_compativeis([{"objetivo": "A", "objetivo_id": "a", "aderencia_perfil": 80, "aderencia_curriculo": None,
                                  "vagas_mes": 5, "amostra_pequena": True},
                                 {"objetivo": "B", "objetivo_id": "b", "aderencia_perfil": 40, "aderencia_curriculo": 30,
                                  "vagas_mes": 90, "amostra_pequena": False}])
    assert [x["objetivo"] for x in r] == ["B", "A"]

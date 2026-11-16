import json

import pandas as pd
import pytest

from jobradar.analytics.coocorrencia import metricas, pares_por_vaga, relacionadas, wilson
from jobradar.settings import CONFIG_DIR, _yaml
from jobradar.transformations.skills import Taxonomy, linhas

TAX = Taxonomy(_yaml(CONFIG_DIR / "skills.yaml"))


def _sk(job, skill, pos=None, imp="requisito"):
    return {"job_id": job, "skill_id": skill, "importancia": imp, "posicoes": json.dumps(pos) if pos else None}


def _pares(rows):
    p = pares_por_vaga(pd.DataFrame(rows))
    return {(r.skill_a, r.skill_b) for r in p.itertuples()}


def test_metricas_conferem_com_conta_feita_a_mao():
    # base 10 vagas; A em 5, B em 4, os dois em 2
    m = metricas(pd.DataFrame([{"skill_a": "a", "skill_b": "b", "vagas_par": 2, "vagas_par_requisito": 1}]),
                 {"a": 5, "b": 4}, base=10, min_par=2, min_base=10).iloc[0]
    assert m.suporte_pct == 20.0
    assert (m.confianca_a_b_pct, m.confianca_b_a_pct) == (40.0, 50.0)   # assimétrica
    assert m.lift == 1.0                                                 # 2·10/(5·4): independentes
    assert m.jaccard == pytest.approx(2 / 7, abs=1e-3)
    assert not m.amostra_pequena


def test_amostra_pequena_por_par_ou_por_base():
    cont = pd.DataFrame([{"skill_a": "a", "skill_b": "b", "vagas_par": 3}])
    assert metricas(cont, {"a": 5, "b": 4}, base=100, min_par=10).iloc[0].amostra_pequena
    assert metricas(cont, {"a": 5, "b": 4}, base=20, min_par=2, min_base=30).iloc[0].amostra_pequena


def test_wilson():
    lo, hi = wilson(5, 10)
    assert (lo, hi) == pytest.approx((23.7, 76.3), abs=0.1)
    assert wilson(0, 0) == (None, None)
    assert wilson(10, 10)[1] == 100.0 and wilson(0, 10)[0] == 0.0


def test_mesma_mencao_nao_vira_par():
    # "PySpark" sozinho: python e spark no mesmo trecho
    assert _pares([_sk("j", "python", [[1, 0, 7]]), _sk("j", "spark", [[1, 0, 7]])]) == set()
    # "PySpark e Python": python também aparece sozinho
    assert _pares([_sk("j", "python", [[1, 0, 7], [1, 10, 16]]), _sk("j", "spark", [[1, 0, 7]])]) == {("python", "spark")}
    # "Azure Data Factory": trechos colados (um espaço entre eles)
    assert _pares([_sk("j", "azure", [[1, 0, 5]]), _sk("j", "data_factory", [[1, 6, 18]])]) == set()
    # Azure citado de novo em outra frase
    assert _pares([_sk("j", "azure", [[1, 0, 5], [3, 0, 5]]), _sk("j", "data_factory", [[1, 6, 18]])]) == {("azure", "data_factory")}
    # sem posição (linha antiga, achado semântico): conta
    assert _pares([_sk("j", "sql"), _sk("j", "python")]) == {("python", "sql")}


def test_mesma_mencao_com_a_taxonomia_de_verdade():
    def pares(desc):
        return _pares(linhas("j", TAX.extrair("Engenheiro de Dados", desc), "r", TAX.versao))
    p = pares("Requisitos:\nAzure Data Factory e PySpark.")
    assert ("azure", "data_factory") not in p and ("python", "spark") not in p
    p = pares("Requisitos:\nAzure Data Factory e PySpark.\nPython, Azure Synapse e Snowflake.")
    assert {("azure", "data_factory"), ("python", "spark")} <= p
    assert ("data_warehouse", "snowflake") not in p                     # só "Snowflake": mesma menção


def test_par_requisito_so_quando_os_dois_sao_requisito():
    p = pares_por_vaga(pd.DataFrame([_sk("j", "sql"), _sk("j", "dbt", imp="desejavel"), _sk("j", "python")]))
    req = {(r.skill_a, r.skill_b): r.ambos_requisito for r in p.itertuples()}
    assert req == {("dbt", "sql"): False, ("dbt", "python"): False, ("python", "sql"): True}


def test_relacionadas_olha_do_ponto_de_vista_da_competencia():
    tab = metricas(pd.DataFrame([{"skill_a": "airflow", "skill_b": "dbt", "vagas_par": 20},
                                 {"skill_a": "airflow", "skill_b": "sql", "vagas_par": 30}]),
                   {"airflow": 40, "dbt": 25, "sql": 90}, base=100)
    rel = relacionadas(tab, "dbt")
    assert list(rel["skill_id"]) == ["airflow"] and rel.iloc[0].confianca_pct == 80.0   # 20/25
    assert list(relacionadas(tab, "airflow")["skill_id"]) == ["sql", "dbt"]             # 75% > 50%

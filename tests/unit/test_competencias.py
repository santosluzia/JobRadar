import copy

import pandas as pd
import pytest
from pydantic import ValidationError

from jobradar.settings import CONFIG_DIR, _yaml
from jobradar.transformations.skills import Taxonomy, efetivas, recortar, so_tecnicas
from jobradar.transformations.text import normalizar

CFG = _yaml(CONFIG_DIR / "skills.yaml")
TAX = Taxonomy(CFG)


def _imp(titulo, desc):
    return {m.skill_id: m.importancia for m in TAX.extrair(titulo, desc)}


def _achados(titulo, desc):
    return {m.skill_id: m for m in TAX.extrair(titulo, desc)}


# ---------------------------------------------------------------- comportamento herdado (v1)
def test_secoes_requisito_e_desejavel():
    r = _imp("Engenheira de Dados", "Requisitos:\nPython e SQL\nSpark\nDiferenciais:\nDatabricks\ndbt\nQualificações:\nAirflow")
    assert r["python"] == r["sql"] == r["spark"] == "requisito"
    assert r["databricks"] == r["dbt"] == "desejavel"
    assert r["airflow"] == "requisito"  # marcador de requisito reabre a seção


def test_diferencial_na_mesma_linha():
    r = _imp("Data Engineer", "Experiência com SQL.\nConhecimento em AWS será um diferencial.")
    assert r["sql"] == "requisito" and r["aws"] == "desejavel"


def test_titulo_conta_como_requisito_e_requisito_vence_desejavel():
    r = _imp("Engenheiro de Dados Databricks", "Diferenciais:\nDatabricks")
    assert r["databricks"] == "requisito"


def test_falsos_positivos_comuns():
    r = _imp("Desenvolvedor JavaScript", "React e JavaScript")
    assert "java" not in r


def test_taxonomia_tem_ids_unicos():
    ids = [s.id for s in TAX.todas]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- taxonomia versionada e validada
def test_taxonomia_tem_versao_semantica():
    assert TAX.versao.count(".") == 2 and TAX.versao != "1.0.0"


@pytest.mark.parametrize("estrago", [
    lambda c: c["competencias"].append(copy.deepcopy(c["competencias"][0])),          # id repetido
    lambda c: c["competencias"][0]["padroes"].append("(sem fechar"),                  # regex inválida
    lambda c: c["competencias"][0].update(tipo="soft"),                              # tipo fora do enum
    lambda c: c["extracao"]["semantica"].update(ativa=True, revisao="main"),         # modelo sem revisão fixa
    lambda c: c.update(campo_desconhecido=1),                                        # erro de digitação no YAML
])
def test_taxonomia_invalida_e_recusada(estrago):
    cfg = copy.deepcopy(CFG)
    estrago(cfg)
    with pytest.raises(ValidationError):
        Taxonomy(cfg)


def test_tecnicas_separadas_das_comportamentais():
    assert all(s.tipo == "tecnica" for s in TAX.skills)
    assert {"comunicacao", "ingles"} <= {s.id for s in TAX.nao_tecnicas}
    a = _achados("Analista", "Requisitos:\nBoa comunicação e inglês avançado.\nSQL.")
    assert a["comunicacao"].tipo == "comportamental" and a["ingles"].tipo == "idioma" and a["sql"].tipo == "tecnica"


# ---------------------------------------------------------------- método, confiança e evidência
def test_conceito_tem_metodo_confianca_e_evidencia():
    a = _achados("Engenheiro de Dados", "Responsabilidades:\nConstruir pipelines escaláveis em ambiente de nuvem.")
    etl = a["etl"]
    assert (etl.metodo, etl.confianca) == ("conceito", "media")
    assert "pipelines escaláveis" in etl.evidencia     # frase ORIGINAL, com acento


def test_termo_vence_conceito():
    a = _achados("Data Engineer", "Requisitos:\nExperiência com ETL e pipelines escaláveis.")
    assert (a["etl"].metodo, a["etl"].confianca) == ("termo", "alta")


def test_evidencia_longa_e_recortada_em_volta_do_achado():
    frase = "Atuar " + "com diversas responsabilidades administrativas e operacionais " * 8 + "usando Kubernetes no dia a dia."
    a = _achados("Engenheiro", "Requisitos:\n" + frase)
    ev = a["kubernetes"].evidencia
    assert "Kubernetes" in ev and len(ev) <= 245 and ev.startswith("…")


def test_recortar_com_acentos_mantem_o_trecho_certo():
    original = "É desejável conhecimento em governança " + "x" * 300 + " e também em Snowflake avançado."
    norm = normalizar(original)
    i = norm.index("snowflake")
    assert "Snowflake" in recortar(original, norm, i, i + len("snowflake"))


# ---------------------------------------------------------------- seções e contexto
def test_texto_institucional_nao_gera_competencia():
    desc = ("Somos uma empresa que aplica inteligência artificial em nossos processos.\n"
            "Requisitos:\nPython e SQL.\n"
            "Benefícios:\nCurso de Power BI e plano de saúde.")
    r = _imp("Engenheiro de Dados", desc)
    assert {"python", "sql"} <= set(r) and "ia_ml" not in r and "power_bi" not in r


def test_descricao_da_gupy_em_uma_linha_so():
    desc = ("A Empresa X é líder em varejo e usa inteligência artificial.Responsabilidades e atribuiçõesDesenvolver "
            "pipelines de dados.Requisitos e qualificaçõesRequisitos obrigatórios:- SQL;- Python.Diferenciais:- Docker;"
            "- Terraform.Informações adicionaisVale-refeição;Plano de saúde")
    r = _imp("Engenheiro de Dados", desc)
    assert r["sql"] == r["python"] == r["etl"] == "requisito"
    assert r["docker"] == r["terraform"] == "desejavel"
    assert "ia_ml" not in r                                  # estava no texto sobre a empresa


def test_cabecalho_colado_sem_dois_pontos():
    r = _imp("Engenheiro de Dados", "Requisitos e qualificações\nSQL avançado e áreas de negócio.DiferenciaisPython.")
    assert r["sql"] == "requisito" and r["python"] == "desejavel"


def test_abertura_que_descreve_a_vaga_conta():
    desc = "Estamos buscando uma pessoa para construir nosso data lake.\nRequisitos:\nSQL"
    assert "data_lake" in _imp("Data Developer", desc)


def test_formacao_nao_vira_competencia_que_e_nome_de_curso():
    assert "estatistica" not in _imp("Analista", "Requisitos:\nGraduação em Estatística ou Computação.\nSQL.")
    assert "estatistica" in _imp("Analista", "Requisitos:\nConhecimento em estatística aplicada.")


@pytest.mark.parametrize("texto,nao_deve", [
    ("Modelagem dimensional (Star Schema, Snowflake).", "snowflake"),
    ("Automação com GitHub Actions.", "git"),
    ("Experiência com Oracle Cloud Infrastructure.", "oracle"),
    ("Analisar grandes volumes de dados de vendas.", "processamento_distribuido"),
    ("Garantir rastreabilidade e governança das decisões de crédito, governança de regras.", "governanca"),
    ("Apresentar indicadores para a liderança da empresa.", "lideranca"),
])
def test_falsos_positivos_corrigidos_na_v2(texto, nao_deve):
    assert nao_deve not in _imp("Analista", "Requisitos:\n" + texto)


# ---------------------------------------------------------------- consumo: só técnicas contam
def test_so_tecnicas_e_efetivas():
    regras = pd.DataFrame([
        {"job_id": "a", "skill_id": "sql", "importancia": "requisito", "tipo": "tecnica"},
        {"job_id": "a", "skill_id": "comunicacao", "importancia": "requisito", "tipo": "comportamental"},
        {"job_id": "b", "skill_id": "python", "importancia": "requisito", "tipo": None},   # linha antiga
    ])
    sem = pd.DataFrame([
        {"job_id": "a", "skill_id": "etl", "importancia": "requisito", "tipo": "tecnica"},
        {"job_id": "a", "skill_id": "sql", "importancia": "requisito", "tipo": "tecnica"},   # já achado por regra
        {"job_id": "c", "skill_id": None, "importancia": None, "tipo": None},              # vaga sem achado
    ])
    assert set(so_tecnicas(regras)["skill_id"]) == {"sql", "python"}
    assert len(efetivas(regras, sem, hibrida=False)) == 2
    h = efetivas(regras, sem, hibrida=True)
    assert sorted(h["skill_id"]) == ["etl", "python", "sql"]
    assert h.loc[h["skill_id"] == "etl", "metodo"].item() == "embedding"

import pytest

from jobradar.scoring import Profile, calcular
from jobradar.settings import CONFIG_DIR, _yaml

CFG = _yaml(CONFIG_DIR / "scoring.yaml")["aderencia"]
PERFIL = Profile.from_dict({
    "objetivo": {"familias": ["engenharia_dados"], "senioridades": ["junior", "pleno"],
                 "modalidades": ["remoto", "hibrido"], "locais": {"ufs": ["SP"]}},
    "competencias": [{"skill": "sql", "nivel": "profissional"}, {"skill": "python", "nivel": "projeto"},
                     {"skill": "kafka", "nivel": "nao_dominada"}],
})
JOB = {"titulo": "Engenheira de Dados Jr", "familia": "engenharia_dados", "senioridade": "junior",
       "modalidade": "remoto", "uf": "SP", "cidade": "São Paulo"}


def req(*ids, imp="requisito"):
    return [{"skill_id": i, "importancia": imp} for i in ids]


def test_score_explicavel_e_soma_coerente():
    r = calcular(JOB, req("sql", "python"), PERFIL, CFG)
    assert 0 <= r.score <= 100
    assert {e["criterio"] for e in r.explicacao} == {"familia", "competencias", "senioridade", "modalidade_local"}
    assert r.score == round(sum(e["pontos"] for e in r.explicacao))


def test_falta_de_evidencia_e_diferente_de_nao_dominada():
    r = calcular(JOB, req("kafka", "spark"), PERFIL, CFG)
    assert [x["skill_id"] for x in r.lacunas] == ["kafka"]
    assert [x["skill_id"] for x in r.sem_evidencia] == ["spark"]


def test_mais_evidencia_aumenta_score():
    fraco = calcular(JOB, req("spark", "airflow"), PERFIL, CFG).score
    forte = calcular(JOB, req("sql", "python"), PERFIL, CFG).score
    assert forte > fraco


def test_desejavel_pesa_menos_que_requisito():
    so_req = calcular(JOB, req("sql") + req("spark"), PERFIL, CFG).score
    spark_desejavel = calcular(JOB, req("sql") + req("spark", imp="desejavel"), PERFIL, CFG).score
    assert spark_desejavel > so_req


def test_penalidades_senior_familia_outra_e_palavra_excludente():
    base = calcular(JOB, req("sql"), PERFIL, CFG).score
    assert calcular({**JOB, "senioridade": "senior"}, req("sql"), PERFIL, CFG).score < base
    assert calcular({**JOB, "familia": "outra"}, req("sql"), PERFIL, CFG).score < base - 20
    assert calcular({**JOB, "titulo": "Estágio em Dados"}, req("sql"), PERFIL, CFG, ["estagio"]).score <= base - 30


def test_presencial_fora_da_regiao_pontua_menos():
    sp = calcular({**JOB, "modalidade": "hibrido"}, req("sql"), PERFIL, CFG).score
    rj = calcular({**JOB, "modalidade": "hibrido", "uf": "RJ", "cidade": "Rio de Janeiro"}, req("sql"), PERFIL, CFG).score
    assert sp > rj


def test_perfil_com_nivel_invalido_falha_cedo():
    with pytest.raises(ValueError):
        Profile.from_dict({"competencias": [{"skill": "sql", "nivel": "expert"}]})

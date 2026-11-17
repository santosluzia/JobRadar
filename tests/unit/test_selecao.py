from datetime import datetime, timezone

import pandas as pd

from jobradar.analytics.selection import inicio_periodo, publicadas_no_periodo

# 17/10/2026 06:47 em São Paulo (UTC-3)
AGORA = datetime(2026, 10, 17, 9, 47, tzinfo=timezone.utc)


def test_inicio_do_periodo_e_meia_noite_de_sao_paulo():
    assert inicio_periodo("hoje", AGORA).isoformat() == "2026-10-17T00:00:00-03:00"
    assert inicio_periodo("ontem_e_hoje", AGORA).isoformat() == "2026-10-16T00:00:00-03:00"
    assert inicio_periodo("7_dias", AGORA).isoformat() == "2026-10-11T00:00:00-03:00"
    assert inicio_periodo("qualquer_data", AGORA) is None


def test_publicadas_no_periodo_usa_o_dia_de_sao_paulo():
    jobs = pd.DataFrame({"publicada_em": [
        "2026-10-17T05:00:00Z",   # 02:00 de hoje em SP
        "2026-10-17T01:00:00Z",   # 22:00 de ontem em SP (já é 17/10 em UTC)
        "2026-10-16T02:59:00Z",   # 23:59 de anteontem em SP
        None,
    ]})
    assert publicadas_no_periodo(jobs, "hoje", AGORA).tolist() == [True, False, False, False]
    assert publicadas_no_periodo(jobs, "ontem_e_hoje", AGORA).tolist() == [True, True, False, False]
    assert publicadas_no_periodo(jobs, "qualquer_data", AGORA).tolist() == [True, True, True, True]


def test_relevantes_inclui_titulo_generico_que_pede_competencias_de_dados():
    from jobradar.analytics.selection import relevantes
    jobs = pd.DataFrame([
        {"job_id": "a", "titulo": "Analista de Sistemas", "familia": "outra"},
        {"job_id": "b", "titulo": "Operador de Caixa", "familia": "outra"},
        {"job_id": "c", "titulo": "Desenvolvedor Java", "familia": "outra"},
        {"job_id": "d", "titulo": "DBA", "familia": "administracao_dados"},
    ]).assign(is_canonica=True, status="ativa", senioridade="pleno", modalidade="remoto", uf="SP", cidade="",
              publicada_em=None, descricao="")
    skills = pd.DataFrame([{"job_id": j, "skill_id": s} for j in "abc" for s in ("sql", "oracle", "plsql")
                           if not (j == "c" and s != "sql")])
    regra = {"min_competencias": 3, "competencias": ["sql", "oracle", "plsql"]}
    filtros = {"familias": ["administracao_dados"]}
    assert list(jobs[relevantes(jobs, skills, filtros, AGORA)].job_id) == ["d"]
    filtros["incluir_por_competencias"] = True
    assert list(jobs[relevantes(jobs, skills, filtros, AGORA, regra_competencias=regra)].job_id) == ["a", "d"]


def test_filtro_de_local_nao_deixa_passar_presencial_ou_hibrida_de_outro_pais():
    from jobradar.analytics.selection import relevantes
    jobs = pd.DataFrame([
        {"job_id": "sp", "modalidade": "hibrido", "uf": "SP", "pais_iso": "BR"},
        {"job_id": "sem_local", "modalidade": "presencial", "uf": None, "pais_iso": None},
        {"job_id": "lisboa", "modalidade": "hibrido", "uf": None, "pais_iso": "PT"},
        {"job_id": "remota_pt", "modalidade": "remoto", "uf": None, "pais_iso": "PT"},   # elegibilidade: PR G
        {"job_id": "rj", "modalidade": "presencial", "uf": "RJ", "pais_iso": "BR"},
    ]).assign(is_canonica=True, status="ativa", senioridade="pleno", familia="engenharia_dados", cidade="",
              titulo="Data Engineer", publicada_em=None, descricao="")
    filtros = {"locais": {"ufs": ["SP"], "cidades": ["sao paulo"]}}
    m = relevantes(jobs, pd.DataFrame(columns=["job_id", "skill_id"]), filtros, AGORA)
    assert list(jobs[m].job_id) == ["sp", "sem_local", "remota_pt"]

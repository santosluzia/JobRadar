from jobradar.settings import CONFIG_DIR, _yaml
from jobradar.transformations.skills import Taxonomy

TAX = Taxonomy(_yaml(CONFIG_DIR / "skills.yaml"))


def _imp(titulo, desc):
    return {m.skill_id: m.importancia for m in TAX.extrair(titulo, desc)}


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
    ids = [s.id for s in TAX.skills]
    assert len(ids) == len(set(ids))

from jobradar.models import Familia, Modalidade, Senioridade
from jobradar.transformations import normalize as n
from jobradar.transformations.text import html_para_texto, normalizar, url_canonica


def test_normalizar_remove_acentos_e_espacos():
    assert normalizar("  Engenheira   de Dados  JÚNIOR ") == "engenheira de dados junior"


def test_url_canonica_remove_rastreamento_e_preserva_parametros_da_candidatura():
    a = url_canonica("https://Empresa.gupy.io/job/1/?utm_source=x&jobBoardSource=gupy_portal&step=2#topo")
    b = url_canonica("https://empresa.gupy.io/job/1?step=2")
    assert a == b == "https://empresa.gupy.io/job/1?step=2"


def test_html_greenhouse_escapado_vira_texto():
    assert html_para_texto("&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;") == "Python & SQL"


def test_senioridade_por_titulo_e_por_descricao():
    assert n.senioridade("Engenheiro de Dados Sr", None) == (Senioridade.senior, "titulo")
    assert n.senioridade("Data Engineer II", None) == (Senioridade.pleno, "titulo")
    assert n.senioridade("Tech Lead de Dados", None)[0] == Senioridade.lideranca
    assert n.senioridade("Analista de Dados", "Nível: Júnior") == (Senioridade.junior, "descricao")
    assert n.senioridade("Analista de Dados", None) == (Senioridade.nao_informada, "nao_informada")
    assert n.senioridade("[Job-32215] Engenheiro de Dados Master, Brazil", None)[0] == Senioridade.senior
    assert n.senioridade("Analista de Master Data Management", None)[0] == Senioridade.nao_informada


def test_modalidade_registra_origem():
    assert n.modalidade("remoto", "x", None) == (Modalidade.remoto, "fonte")
    assert n.modalidade(None, "Data Engineer - Híbrido", None) == (Modalidade.hibrido, "titulo")
    assert n.modalidade(None, "Data Engineer", "Trabalho 100% remoto") == (Modalidade.remoto, "descricao")


def test_uf_por_nome_sigla_e_texto_livre():
    assert n.uf("São Paulo", None) == "SP"
    assert n.uf(None, "Barueri, SP") == "SP"
    assert n.uf(None, "Belo Horizonte, Minas Gerais") == "MG"
    assert n.uf(None, "Remote") is None


def test_familia_nao_descarta_titulo_sem_dados_quando_descricao_e_de_engenharia():
    assert n.familia("Engenheiro de Software", {"spark", "airflow", "databricks"}) == (Familia.engenharia_dados, "descricao")
    assert n.familia("Engenheiro de Software", {"python"}) == (Familia.outra, "titulo")
    assert n.familia("Analytics Engineer", set())[0] == Familia.analytics_engineering


def test_familia_governanca_so_de_dados():
    gov = Familia.governanca_qualidade
    assert n.familia("Analista de Governança de Dados Pleno", set())[0] == gov
    assert n.familia("Gerente de Governança e Arquitetura de Dados", set())[0] == gov
    assert n.familia("Analista Qualidade de Dados JR", set())[0] == gov
    assert n.familia("GOVERNANÇA DE PRIVACIDADE - POA/RS", set())[0] == Familia.outra
    assert n.familia("Especialista de Governança e Controle Estratégico", set())[0] == Familia.outra

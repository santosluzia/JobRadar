"""Descoberta assistida e fila de curadoria de empresas (ADR 0012). Nada vai à internet."""
import shutil
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import yaml

from jobradar.cli import main
from jobradar.collectors import GreenhouseCollector, build_collectors
from jobradar.empresas import carregar_catalogo
from jobradar.empresas import verificacao as vf
from jobradar.empresas.catalogo import Empresa
from jobradar.empresas.curadoria import CuradoriaErro, adicionar_candidata, aprovar, descartar, formatar
from jobradar.empresas.deteccao_ats import PaginaIndisponivel, detectar, detectar_na_url, detectar_no_html
from jobradar.settings import CONFIG_DIR, carregar
from jobradar.storage import Lake

FILTRO = {"titulo_contem": ["data", "dados"], "pausa_segundos": 0}


def _cli(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# ---------------------------------------------------------------- detecção pela URL
@pytest.mark.parametrize("url, esperado", [
    ("https://boards.greenhouse.io/nubank", ("greenhouse", "nubank", None)),
    ("https://job-boards.greenhouse.io/artefact/jobs/8911509002", ("greenhouse", "artefact", None)),
    ("https://boards.greenhouse.io/embed/job_board?for=acme&b=x", ("greenhouse", "acme", None)),
    ("https://boards.greenhouse.io/embed/job_board/js?for=acme", ("greenhouse", "acme", None)),
    ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", ("greenhouse", "acme", None)),
    ("https://job-boards.eu.greenhouse.io/acme", ("greenhouse", "acme", "eu")),
    ("https://jobs.lever.co/ciandt/5a1b-uuid", ("lever", "ciandt", None)),
    ("https://api.lever.co/v0/postings/ciandt?mode=json", ("lever", "ciandt", None)),
    ("https://jobs.eu.lever.co/acme", ("lever", "acme", "eu")),
    ("https://jobs.ashbyhq.com/acme/uuid/application", ("ashby", "acme", None)),
    ("https://api.ashbyhq.com/posting-api/job-board/acme", ("ashby", "acme", None)),
    ("https://jobs.smartrecruiters.com/Acme/7444-data-engineer", ("smartrecruiters", "Acme", None)),
    ("https://careers.smartrecruiters.com/Acme", ("smartrecruiters", "Acme", None)),
    ("https://api.smartrecruiters.com/v1/companies/Acme/postings", ("smartrecruiters", "Acme", None)),
    ("https://acme.gupy.io/jobs/123", ("gupy", "acme", None)),
    ("https://acme.wd5.myworkdayjobs.com/pt-BR/Careers", ("workday", None, None)),
])
def test_detecta_ats_e_quadro_pelo_endereco(url, esperado):
    d = detectar_na_url(url)
    assert (d.ats, d.board, d.regiao) == esperado


@pytest.mark.parametrize("url", ["https://boards.greenhouse.io/embed/job_board", "https://jobs.lever.co/",
                                 "https://www.acme.com/carreiras", "https://portal.gupy.io/vagas", "não é url"])
def test_endereco_sem_quadro_nao_vira_deteccao(url):
    assert detectar_na_url(url) is None


def test_detecta_quadros_citados_no_html_sem_repetir():
    html = """<a href="https://jobs.lever.co/acme/1">Vaga</a><a href="https://jobs.lever.co/acme/2">Outra</a>
              <iframe src="//boards.greenhouse.io/embed/job_board?for=acme&amp;b=https%3A%2F%2Facme.com"></iframe>
              <a href="https://www.linkedin.com/company/acme">LinkedIn</a>"""
    achados = detectar_no_html(html, "https://acme.com/carreiras")
    assert [(d.ats, d.board) for d in achados] == [("lever", "acme"), ("greenhouse", "acme")]


# ---------------------------------------------------------------- página de carreiras (robots.txt)
def _site(robots=(200, "User-agent: *\nAllow: /\n"), pagina=(200, '<a href="https://jobs.ashbyhq.com/acme">Vagas</a>'),
          redirecionar=None):
    pedidos = []

    def h(req):
        pedidos.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(robots[0], text=robots[1])
        if redirecionar and req.url.host == "acme.com":
            return httpx.Response(302, headers={"location": redirecionar})
        if req.url.host == "jobs.lever.co":
            return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})
        return httpx.Response(pagina[0], text=pagina[1], headers={"content-type": "text/html; charset=utf-8"})
    return _cli(h), pedidos


def test_pagina_de_carreiras_lida_uma_vez_com_robots_permitindo():
    client, pedidos = _site()
    assert [(d.ats, d.board) for d in detectar("https://acme.com/carreiras", client)] == [("ashby", "acme")]
    assert pedidos == ["https://acme.com/robots.txt", "https://acme.com/carreiras"]   # sem seguir links


@pytest.mark.parametrize("robots, trecho", [
    ((200, "User-agent: *\nDisallow: /carreiras\n"), "não permite"),
    ((503, ""), "HTTP 503"),
    ((403, ""), "HTTP 403"),
])
def test_robots_que_proibe_ou_falha_impede_a_consulta(robots, trecho):
    client, pedidos = _site(robots=robots)
    with pytest.raises(PaginaIndisponivel, match=trecho):
        detectar("https://acme.com/carreiras", client)
    assert pedidos == ["https://acme.com/robots.txt"]


def test_sem_robots_permitido_mas_login_ou_http_nao_https_param():
    client, _ = _site(robots=(404, ""))
    assert detectar("https://acme.com/carreiras", client)
    client, _ = _site(robots=(404, ""), pagina=(403, "login"))
    with pytest.raises(PaginaIndisponivel, match="login"):
        detectar("https://acme.com/carreiras", client)
    with pytest.raises(PaginaIndisponivel, match="https"):
        detectar("http://acme.com/carreiras", client)


def test_redirecionamento_para_o_quadro_tambem_conta():
    client, _ = _site(redirecionar="https://jobs.lever.co/acme")
    assert [(d.ats, d.board) for d in detectar("https://acme.com/carreiras", client)] == [("lever", "acme")]


# ---------------------------------------------------------------- verificação do quadro
def _gh(vagas, total=None, nome="Acme"):
    corpo = {"jobs": [{"id": i, "title": t, "company_name": nome, "location": {"name": loc},
                       "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{i}", "content": "<p>SQL</p>"}
                      for i, (t, loc) in enumerate(vagas, 1)],
             "meta": {"total": total if total is not None else len(vagas)}}
    return _cli(lambda req: httpx.Response(200, json=corpo))


def test_verificacao_conta_vagas_de_dados_por_pais_e_le_o_nome_da_api():
    vagas = [("Data Engineer", "São Paulo, Brazil"), ("Analista de Dados", "Lisbon, Portugal"),
             ("Data Scientist", "New York, United States"), ("Account Executive", "São Paulo, Brazil")]
    v = vf.verificar("greenhouse", "acme", FILTRO, client=_gh(vagas, nome="LinkedIn Job Wrapping"))
    assert (v.ok, v.completo, v.vagas_listadas, v.vagas_dados) == (True, True, 4, 3)
    assert (v.vagas_brasil, v.vagas_alvo, v.paises) == (1, 2, {"BR": 1, "PT": 1, "US": 1})
    assert v.nome_api == "LinkedIn Job Wrapping"
    assert v.pendencias("LinkedIn Job Wrapping") == []
    assert "nome_fixo" in v.pendencias("Artefact")[0] and v.pendencias("Artefact", nome_fixo=True) == []


def test_verificacao_aponta_quadro_incompleto_sem_dados_fora_do_alvo_e_erro():
    v = vf.verificar("greenhouse", "acme", FILTRO, client=_gh([("Data Engineer", "Berlin, Germany")], total=5))
    pend = v.pendencias("Acme")
    assert any("incompleto" in p for p in pend) and any("América Latina" in p for p in pend)
    v = vf.verificar("greenhouse", "acme", FILTRO, client=_gh([("Vendedor", "São Paulo")]))
    assert any("filtro de título" in p for p in v.pendencias("Acme"))
    v = vf.verificar("greenhouse", "acme", FILTRO, client=_cli(lambda req: httpx.Response(404)))
    assert not v.ok and "não respondeu" in v.pendencias("Acme")[0]
    assert "não tem coletor" in vf.verificar("workday", "x", {}).erro


@pytest.mark.parametrize("api, catalogo, diverge", [
    ("XP Inc.", "XP", False), ("Itaú Unibanco", "Itau Unibanco", False), (None, "Acme", False),
    ("LinkedIn Job Wrapping", "Artefact", True),
])
def test_nome_diverge(api, catalogo, diverge):
    assert vf.nome_diverge(api, catalogo) is diverge


def test_registro_e_ultima_verificacao(tmp_path):
    lake = Lake(tmp_path)
    antiga = vf.Verificacao("greenhouse", "acme", datetime(2026, 11, 1, tzinfo=timezone.utc), ok=False, erro="HTTP 500")
    nova = vf.verificar("greenhouse", "acme", FILTRO, client=_gh([("Data Engineer", "Recife, PE")]),
                        agora=datetime(2026, 11, 10, tzinfo=timezone.utc))
    vf.registrar(lake, [antiga, nova])
    u = vf.ultima(lake, "greenhouse", "ACME")
    assert u.ok and u.vagas_brasil == 1 and u.paises == {"BR": 1} and u.em.date() == date(2026, 11, 10)
    assert not vf.vencida(u, date(2026, 11, 17)) and vf.vencida(u, date(2026, 11, 18))
    assert vf.ultima(lake, "lever", "acme") is None


# ---------------------------------------------------------------- fila de curadoria (edição do YAML)
@pytest.fixture
def catalogo(tmp_path):
    destino = tmp_path / "empresas.yaml"
    shutil.copy(CONFIG_DIR / "empresas.yaml", destino)
    return destino


def _candidata(**kw):
    base = {"id": "acme", "nome": "Acme, S.A.", "pais": "BR", "segmento": "tecnologia", "ats": "greenhouse",
            "board": "acme", "status": "candidata", "origem": "descoberta", "observacoes": "a API diz: 'Acme' {x}"}
    return Empresa(**{**base, **kw})


def test_candidata_entra_no_fim_preservando_comentarios_e_entradas(catalogo):
    antes = catalogo.read_text(encoding="utf-8")
    cat = adicionar_candidata(catalogo, _candidata())
    depois = catalogo.read_text(encoding="utf-8")
    assert depois.startswith(antes.rstrip("\n")) and "Candidatas (descoberta assistida)" in depois
    nova = next(e for e in cat.empresas if e.id == "acme")
    assert (nova.status, nova.nome, nova.observacoes) == ("candidata", "Acme, S.A.", "a API diz: 'Acme' {x}")
    assert "acme" not in cat.quadros_ativos("greenhouse")                       # candidata não é coletada
    adicionar_candidata(catalogo, _candidata(id="beta", board="beta"))
    assert catalogo.read_text(encoding="utf-8").count("Candidatas (descoberta assistida)") == 1
    with pytest.raises(CuradoriaErro, match="já existe"):
        adicionar_candidata(catalogo, _candidata())
    with pytest.raises(CuradoriaErro, match="já está no catálogo"):
        adicionar_candidata(catalogo, _candidata(id="vtex2", board="VTEX"))
    with pytest.raises(CuradoriaErro, match="candidata"):
        adicionar_candidata(catalogo, _candidata(id="z", board="z", status="ativa", verificada_em=date(2026, 11, 1)))


def test_aprovar_e_descartar_mudam_so_a_entrada(catalogo):
    adicionar_candidata(catalogo, _candidata())
    e = next(x for x in carregar_catalogo(yaml.safe_load(catalogo.read_text(encoding="utf-8"))).empresas if x.id == "acme")
    linhas_antes = catalogo.read_text(encoding="utf-8").split("\n")
    cat = aprovar(catalogo, e, date(2026, 11, 17))
    assert "acme" in cat.quadros_ativos("greenhouse")
    assert next(x for x in cat.empresas if x.id == "acme").verificada_em == date(2026, 11, 17)
    linhas = catalogo.read_text(encoding="utf-8").split("\n")
    assert linhas[:len(linhas_antes) - 4] == linhas_antes[:len(linhas_antes) - 4]   # o resto do arquivo não muda
    ativa = next(x for x in cat.empresas if x.id == "acme")
    with pytest.raises(CuradoriaErro, match="só candidata ou pausada"):
        aprovar(catalogo, ativa, date(2026, 11, 17))
    with pytest.raises(CuradoriaErro, match="motivo"):
        descartar(catalogo, ativa, " ", date(2026, 11, 17))
    cat = descartar(catalogo, ativa, "quadro de parceiro", date(2026, 11, 18))
    d = next(x for x in cat.empresas if x.id == "acme")
    assert d.status == "descartada" and d.observacoes.endswith("descartada em 2026-11-18: quadro de parceiro")


def test_alteracao_invalida_nao_grava(catalogo):
    adicionar_candidata(catalogo, _candidata(ats="gupy"))
    antes = catalogo.read_text(encoding="utf-8")
    e = next(x for x in carregar_catalogo(yaml.safe_load(antes)).empresas if x.id == "acme")
    with pytest.raises(CuradoriaErro, match="inválido"):
        aprovar(catalogo, e, date(2026, 11, 17))                                # gupy não tem coletor
    assert catalogo.read_text(encoding="utf-8") == antes


def test_formato_da_entrada_e_o_do_arquivo():
    texto = formatar({"id": "x", "nome": "CI&T", "pais": "BR", "segmento": "outro", "ats": "lever", "board": "x",
                      "status": "ativa", "verificada_em": date(2026, 11, 17), "observacoes": "a, b: c #d"})
    assert texto.startswith("  - {id: x, nome: CI&T,") and all(len(linha) <= 112 for linha in texto.split("\n"))
    assert yaml.safe_load("l:\n" + texto)["l"][0]["observacoes"] == "a, b: c #d"


# ---------------------------------------------------------------- nome fixo na coleta
def test_nome_fixo_vence_o_nome_da_api_so_quando_marcado(tmp_path):
    s = carregar(lake=tmp_path, config_dir=CONFIG_DIR)
    s.empresas = {"empresas": [
        {"id": "artefact", "nome": "Artefact", "pais": "FR", "segmento": "consultoria", "ats": "greenhouse",
         "board": "artefactlinkedin", "status": "ativa", "verificada_em": "2026-11-17", "nome_fixo": True},
        {"id": "acme", "nome": "Acme", "pais": "BR", "segmento": "tecnologia", "ats": "greenhouse",
         "board": "acme", "status": "ativa", "verificada_em": "2026-11-17"}]}
    gh = next(c for c in build_collectors(s) if c.name == "greenhouse")
    assert gh.cfg["nomes_fixos"] == {"artefactlinkedin": "Artefact"}
    corpo = {"jobs": [{"id": 1, "title": "Data Engineer", "company_name": "LinkedIn Job Wrapping",
                       "absolute_url": "https://x/1", "location": {"name": "São Paulo"}}], "meta": {"total": 1}}
    for board, esperado in (("artefactlinkedin", "Artefact"), ("acme", "LinkedIn Job Wrapping")):
        c = GreenhouseCollector({**gh.cfg, "empresas": [board], "pausa_segundos": 0},
                                client=_cli(lambda req: httpx.Response(200, json=corpo)))
        assert c.to_raw_job(c.collect([]).records[0]).company == esperado


# ---------------------------------------------------------------- linha de comando
def test_cli_aprovar_exige_verificacao_recente_sem_pendencias(catalogo, tmp_path, monkeypatch, capsys):
    shutil.copy(CONFIG_DIR / "sources.yaml", catalogo.parent / "sources.yaml")
    for nome in ("skills.yaml", "scoring.yaml"):
        shutil.copy(CONFIG_DIR / nome, catalogo.parent / nome)
    monkeypatch.setenv("JOBRADAR_CONFIG_DIR", str(catalogo.parent))
    lake = tmp_path / "lake"
    adicionar_candidata(catalogo, _candidata(nome="Acme"))

    def rodar(*args):
        with pytest.raises(SystemExit) as fim:
            main(["--lake", str(lake), "empresas", *args])
        return fim.value.code

    assert rodar("aprovar", "acme") == 1 and "sem verificação" in capsys.readouterr().out
    velha = datetime.now(timezone.utc) - timedelta(days=10)
    vf.registrar(Lake(lake), [vf.verificar("greenhouse", "acme", FILTRO, client=_gh([("Data Engineer", "Recife, PE")]),
                                           agora=velha)])
    assert rodar("aprovar", "acme") == 1 and "mais de 7 dias" in capsys.readouterr().out
    vf.registrar(Lake(lake), [vf.verificar("greenhouse", "acme", FILTRO, client=_gh([("Data Engineer", "Recife, PE")]))])
    assert rodar("aprovar", "acme") == 0
    assert "acme" in carregar_catalogo(yaml.safe_load(catalogo.read_text(encoding="utf-8"))).quadros_ativos("greenhouse")
    assert rodar("descartar", "acme") == 1 and "motivo" in capsys.readouterr().out
    assert rodar("listar", "--status", "ativa") == 0 and "acme" in capsys.readouterr().out

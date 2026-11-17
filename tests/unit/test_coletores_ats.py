"""Ashby, SmartRecruiters e Lever com respostas simuladas no formato documentado (nada vai à internet)."""
import httpx

from jobradar.collectors import AshbyCollector, LeverCollector, SmartRecruitersCollector, build_collectors
from jobradar.empresas.catalogo import API_URL
from jobradar.settings import CONFIG_DIR, carregar

FILTRO = ["data", "dados"]


def _cli(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- Ashby
def _ashby_job(id_, titulo, **kw):
    base = {"id": id_, "title": titulo, "location": "São Paulo", "workplaceType": "Hybrid", "isRemote": True,
            "isListed": True, "publishedAt": "2026-11-10T12:00:00.000+00:00", "employmentType": "FullTime",
            "jobUrl": f"https://jobs.ashbyhq.com/acme/{id_}", "applyUrl": f"https://jobs.ashbyhq.com/acme/{id_}/application",
            "descriptionPlain": "Requisitos: Python, SQL e Spark.", "department": "Data",
            "address": {"postalAddress": {"addressLocality": "São Paulo", "addressRegion": "SP", "addressCountry": "Brazil"}}}
    return {**base, **kw}


def test_ashby_mapeia_campos_e_respeita_vaga_nao_listada():
    corpo = {"apiVersion": "1", "jobs": [
        _ashby_job("u1", "Data Engineer"),
        _ashby_job("u2", "Data Analyst", isListed=False),                    # só por link direto
        _ashby_job(None, "Engenheira de Dados", jobUrl="https://jobs.ashbyhq.com/acme/u3", workplaceType="Remote"),
        _ashby_job("u4", "Account Executive"),
    ]}
    pedidos = []

    def h(req):
        pedidos.append(req)
        return httpx.Response(200, json=corpo)
    c = AshbyCollector({"empresas": ["acme"], "nomes": {"acme": "Acme S.A."}, "titulo_contem": FILTRO}, client=_cli(h))
    c.pause = 0
    r = c.collect([])
    assert pedidos[0].url.path == "/posting-api/job-board/acme" and pedidos[0].url.params["includeCompensation"] == "true"
    assert [x["id"] for x in r.records] == ["u1", "u3"]                     # u3: id tirado do jobUrl
    assert r.quadros == {"acme": ["u1", "u2", "u3", "u4"]}                  # não listada continua no quadro
    assert r.params["nao_listadas"] == 1 and r.por_quadro["acme"]["vagas_mantidas"] == 2
    raw = c.to_raw_job(r.records[0])
    assert (raw.company, raw.country, raw.state, raw.city, raw.modality_raw) == ("Acme S.A.", "Brazil", "SP", "São Paulo", "hibrido")
    assert raw.url == "https://jobs.ashbyhq.com/acme/u1" and raw.board == "acme" and "Spark" in raw.description
    assert c.to_raw_job(r.records[1]).modality_raw == "remoto"


def test_ashby_sem_workplacetype_usa_isremote_so_para_remoto():
    c = AshbyCollector({"empresas": ["acme"]})
    assert c.to_raw_job(_ashby_job("a", "Data", workplaceType=None, isRemote=True)).modality_raw == "remoto"
    assert c.to_raw_job(_ashby_job("b", "Data", workplaceType=None, isRemote=False)).modality_raw is None


def test_ashby_formato_inesperado_e_falha_do_quadro():
    c = AshbyCollector({"empresas": ["acme"]}, client=_cli(lambda req: httpx.Response(200, json={"vagas": []})))
    c.pause = 0
    r = c.collect([])
    assert not r.ok and "formato mudou" in r.por_quadro["acme"]["erro"] and r.quadros == {}


# ---------------------------------------------------------------- SmartRecruiters
def _sr_item(id_, nome, **loc):
    return {"id": id_, "uuid": f"uuid-{id_}", "name": nome, "releasedDate": "2026-11-12T10:00:00.000Z",
            "company": {"identifier": "Acme", "name": "Acme Ltda"},
            "location": {"city": "São Paulo", "region": "SP", "country": "br", "remote": False, "hybrid": False, **loc},
            "experienceLevel": {"label": "Mid-Senior Level"}, "typeOfEmployment": {"label": "Full-time"}}


def _sr_detalhe(id_):
    return {"id": id_, "postingUrl": f"https://jobs.smartrecruiters.com/Acme/{id_}-vaga",
            "applyUrl": f"https://jobs.smartrecruiters.com/Acme/{id_}-vaga?oga=true",
            "jobAd": {"sections": {
                "companyDescription": {"title": "Sobre a empresa", "text": "<p>Somos uma varejista.</p>"},
                "jobDescription": {"title": "Descrição da vaga", "text": "<p>Construir pipelines.</p>"},
                "qualifications": {"title": "Requisitos", "text": "<ul><li>Python</li><li>Airflow</li></ul>"},
                "additionalInformation": {"title": "Informações adicionais", "text": ""}}}}


def _sr(itens, detalhe_falha=(), pagina=2):
    pedidos = []

    def h(req):
        pedidos.append(req)
        partes = req.url.path.split("/")             # /v1/companies/Acme/postings[/id]
        if len(partes) == 6:
            id_ = partes[5]
            return httpx.Response(404 if id_ in detalhe_falha else 200, json=_sr_detalhe(id_))
        off, lim = int(req.url.params["offset"]), int(req.url.params["limit"])
        assert req.url.params["destination"] == "PUBLIC"
        return httpx.Response(200, json={"offset": off, "limit": lim, "totalFound": len(itens),
                                         "content": itens[off:off + lim]})
    c = SmartRecruitersCollector({"empresas": ["Acme"], "titulo_contem": FILTRO}, client=_cli(h))
    c.pause, c.PAGINA = 0, pagina
    return c, c.collect([]), pedidos


def test_smartrecruiters_pagina_busca_detalhe_so_das_vagas_filtradas():
    itens = [_sr_item("1", "Engenheiro de Dados"), _sr_item("2", "Vendedor"), _sr_item("3", "Data Analyst", remote=True),
             _sr_item("4", "Caixa"), _sr_item("5", "Analista de Dados", hybrid=True)]
    c, r, pedidos = _sr(itens)
    listagens = [p for p in pedidos if p.url.path.endswith("/postings")]
    detalhes = [p.url.path.rsplit("/", 1)[-1] for p in pedidos if not p.url.path.endswith("/postings")]
    assert len(listagens) == 3 and detalhes == ["1", "3", "5"]             # 5 vagas em páginas de 2
    assert r.ok and r.quadros == {"Acme": ["1", "2", "3", "4", "5"]} and r.por_quadro["Acme"]["completo"]
    raw = c.to_raw_job(r.records[0])
    assert raw.url.startswith("https://jobs.smartrecruiters.com/Acme/1") and raw.company == "Acme Ltda"
    assert (raw.country, raw.state, raw.city, raw.modality_raw) == ("BR", "SP", "São Paulo", "presencial")
    assert "Requisitos:\nPython" in raw.description and "Informações adicionais" not in raw.description
    assert [c.to_raw_job(x).modality_raw for x in r.records[1:]] == ["remoto", "hibrido"]


def test_smartrecruiters_detalhe_com_erro_fica_fora_sem_derrubar_a_fonte():
    c, r, _ = _sr([_sr_item("1", "Engenheiro de Dados"), _sr_item("2", "Data Engineer")], detalhe_falha={"1"})
    assert r.ok and [x["id"] for x in r.records] == ["2"] and r.params["detalhes_com_erro"] == 1
    assert r.por_quadro["Acme"]["vagas_mantidas"] == 1 and r.quadros["Acme"] == ["1", "2"]   # não encerra a 1


def test_smartrecruiters_vaga_sem_id_e_descricao_longa():
    sem_id = {**_sr_item("x", "Data Engineer"), "id": None}
    c, r, pedidos = _sr([sem_id, _sr_item("2", "Data Analyst")])
    assert [x["id"] for x in r.records] == ["2"] and r.params["detalhes_com_erro"] == 1
    assert not [p for p in pedidos if p.url.path.endswith("/None")]          # não pede detalhe de "None"
    longo = {"jobAd": {"sections": {"jobDescription": {"title": "Vaga", "text": "<p>" + "a" * 30000 + "</p>"}}}}
    from jobradar.collectors.ats.smartrecruiters import descricao
    assert len(descricao(longo)) <= 20000


def test_smartrecruiters_formato_inesperado_e_total_que_nao_bate():
    for corpo in ({"items": []}, {"content": [], "totalFound": None}):
        c = SmartRecruitersCollector({"empresas": ["Acme"]}, client=_cli(lambda req, b=corpo: httpx.Response(200, json=b)))
        c.pause = 0
        r = c.collect([])
        assert not r.ok and "formato mudou" in r.errors[0]

    def h(req):   # a API diz que há 3 vagas, mas devolve 1 e para: lista incompleta não serve de evidência
        if req.url.path.endswith("/postings"):
            return httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 3,
                                             "content": [_sr_item("1", "Vendas")] if req.url.params["offset"] == "0" else []})
        return httpx.Response(200, json=_sr_detalhe("1"))
    c = SmartRecruitersCollector({"empresas": ["Acme"]}, client=_cli(h))
    c.pause = 0
    r = c.collect([])
    assert r.quadros == {} and r.params["quadros_incompletos"] == ["Acme"]


# ---------------------------------------------------------------- Lever
def test_lever_le_pais_listas_e_texto_adicional():
    vaga = {"id": "a", "text": "Data Engineer", "hostedUrl": "https://jobs.lever.co/y/a", "country": "CO",
            "categories": {"location": "Bogotá"}, "workplaceType": "remote", "createdAt": 1762000000000,
            "descriptionPlain": "Sobre a vaga: pipelines.",
            "lists": [{"text": "Requirements", "content": "<li>Python</li><li>dbt</li>"}],
            "additionalPlain": "Nice to have: Kafka"}
    c = LeverCollector({"empresas": ["y"]}, client=_cli(lambda req: httpx.Response(200, json=[vaga])))
    c.pause = 0
    raw = c.to_raw_job(c.collect([]).records[0])
    assert raw.country == "CO" and raw.description == "Sobre a vaga: pipelines.\n\nRequirements:\nPython\ndbt\n\nNice to have: Kafka"
    from jobradar.collectors.ats.lever import descricao
    assert descricao({"lists": [{"text": "", "content": "<li>SQL</li>"}]}) == "SQL"   # lista sem título: sem ":" solto


# ---------------------------------------------------------------- registro
def test_url_da_api_no_catalogo_e_a_dos_novos_coletores():
    assert API_URL["ashby"].format(board="x") == AshbyCollector.URL.format(board="x")
    assert API_URL["smartrecruiters"].format(board="x") == SmartRecruitersCollector.URL.format(board="x")


def test_empresa_ativa_no_ashby_liga_o_coletor_com_o_nome_do_catalogo(tmp_path):
    s = carregar(lake=tmp_path, config_dir=CONFIG_DIR)
    assert not [c for c in build_collectors(s) if c.name in ("ashby", "smartrecruiters")]   # sem empresa, sem coletor
    s.empresas = {"empresas": [{"id": "acme", "nome": "Acme", "pais": "BR", "segmento": "tecnologia", "ats": "ashby",
                                "board": "acme", "status": "ativa", "verificada_em": "2026-11-17"}]}
    ash = [c for c in build_collectors(s) if c.name == "ashby"]
    assert ash and ash[0].cfg["empresas"] == ["acme"] and ash[0].cfg["nomes"] == {"acme": "Acme"}

import httpx
import pytest

from jobradar.collectors import AdzunaCollector, GreenhouseCollector, GupyCollector, LeverCollector
from jobradar.collectors.base import CollectResult, SourceError


def _cliente(respostas):
    fila = list(respostas)

    def h(req):
        status, corpo = fila.pop(0) if len(fila) > 1 else fila[0]
        return httpx.Response(status, json=corpo)
    return httpx.Client(transport=httpx.MockTransport(h))


def test_retry_em_503_e_sucesso_depois():
    c = GupyCollector({"urls": ["https://portal.api.gupy.io/api/v1/jobs"], "limite_por_termo": 10},
                      client=_cliente([(503, {}), (200, {"data": [{"id": 1}], "pagination": {"total": 1}})]))
    c.pause = 0
    r = c.collect(["dados"])
    assert r.ok and r.retries == 1 and r.requests == 2 and len(r.records) == 1


def test_4xx_nao_e_repetido():
    c = GupyCollector({}, client=_cliente([(403, {})]))
    c.pause = 0
    with pytest.raises(SourceError):
        c._get("https://x.gupy.io", {}, CollectResult("gupy"))


def test_gupy_usa_url_alternativa_e_detecta_mudanca_de_formato():
    def h(req):
        if "portal.api" in req.url.host:
            return httpx.Response(200, json={"formato": "novo"})
        return httpx.Response(200, json={"data": [{"id": 7}], "pagination": {"total": 1}})
    c = GupyCollector({"urls": ["https://portal.api.gupy.io/api/v1/jobs", "https://employability-portal.gupy.io/api/v1/jobs"]},
                      client=httpx.Client(transport=httpx.MockTransport(h)))
    c.pause = 0
    r = c.collect(["dados"])
    assert r.ok and r.params["url"].startswith("https://employability")


def test_todas_as_urls_falhando_vira_erro_registrado_sem_excecao():
    c = GupyCollector({"urls": ["https://a.gupy.io"]}, client=_cliente([(500, {})]))
    c.pause = 0
    r = c.collect(["dados"])
    assert not r.ok and r.records == []


def test_duplicatas_entre_termos_sao_contadas():
    c = GupyCollector({"urls": ["https://a.gupy.io"]}, client=_cliente([(200, {"data": [{"id": 1}, {"id": 2}], "pagination": {"total": 2}})]))
    c.pause = 0
    r = c.collect(["a", "b", "c"])
    assert len(r.records) == 2 and r.duplicates_in_source == 4


def test_adzuna_mapeia_local_e_remoto():
    c = AdzunaCollector({}, "i", "k")
    raw = c.to_raw_job({"id": "9", "title": "Data Engineer", "redirect_url": "https://adzuna.com.br/x",
                        "location": {"display_name": "Barueri", "area": ["Brasil", "São Paulo", "Barueri"]},
                        "description": "Home office", "created": "2026-10-01T00:00:00Z"})
    assert raw.state == "São Paulo" and raw.city == "Barueri" and raw.modality_raw == "remoto"


def test_greenhouse_e_lever_filtram_por_titulo_antes_da_bronze():
    gh = {"jobs": [{"id": 1, "title": "Engenheira de Dados Sr"}, {"id": 2, "title": "Executivo de Vendas"},
                   {"id": 3, "title": "Analista de BI"}, {"id": 4, "title": "Bilingual Support"}]}
    lv = [{"id": "a", "text": "Data Developer"}, {"id": "b", "text": "Advogado(a)"}]

    def h(req):
        return httpx.Response(200, json=gh if "greenhouse" in req.url.host else lv)
    cliente = httpx.Client(transport=httpx.MockTransport(h))
    filtro = ["dados", "data", "bi"]
    g = GreenhouseCollector({"empresas": ["x"], "titulo_contem": filtro}, client=cliente)
    v = LeverCollector({"empresas": ["y"], "titulo_contem": filtro}, client=cliente)
    g.pause = v.pause = 0
    rg, rv = g.collect([]), v.collect([])
    assert [r["id"] for r in rg.records] == [1, 3] and rg.params["fora_do_filtro_titulo"] == 2
    assert [r["id"] for r in rv.records] == ["a"]
    sem_filtro = GreenhouseCollector({"empresas": ["x"]}, client=cliente)
    sem_filtro.pause = 0
    assert len(sem_filtro.collect([]).records) == 4


def test_quadro_completo_registra_todos_os_ids_antes_do_filtro_de_titulo():
    gh = {"jobs": [{"id": 1, "title": "Engenheira de Dados"}, {"id": 2, "title": "Executivo de Vendas"}],
          "meta": {"total": 2}}
    lv = [{"id": "a", "text": "Data Developer"}, {"id": "b", "text": "Advogado(a)"}]

    def h(req):
        return httpx.Response(200, json=gh if "greenhouse" in req.url.host else lv)
    cliente = httpx.Client(transport=httpx.MockTransport(h))
    g = GreenhouseCollector({"empresas": ["x"], "titulo_contem": ["dados", "data"]}, client=cliente)
    v = LeverCollector({"empresas": ["y"], "titulo_contem": ["dados", "data"]}, client=cliente)
    g.pause = v.pause = 0
    rg, rv = g.collect([]), v.collect([])
    assert rg.quadros == {"x": ["1", "2"]} and [r["id"] for r in rg.records] == [1]
    assert rv.quadros == {"y": ["a", "b"]}
    assert g.to_raw_job({**rg.records[0], "absolute_url": "https://x.io/1"}).board == "x"
    assert v.to_raw_job({**rv.records[0], "hostedUrl": "https://y.io/a"}).board == "y"


@pytest.mark.parametrize("resposta", [
    (503, {}),                                                        # quadro fora do ar
    (200, {"jobs": []}),                                              # vazio: suspeito
    (200, {"jobs": [{"id": 1, "title": "Data"}], "meta": {"total": 5}}),  # lista truncada
])
def test_quadro_com_erro_vazio_ou_truncado_nao_serve_de_evidencia(resposta):
    g = GreenhouseCollector({"empresas": ["x"]}, client=_cliente([resposta]))
    g.pause = 0
    assert g.collect([]).quadros == {}


# ---------------------------------------------------------------- Retry-After, jitter e teto de espera
def test_retry_after_em_segundos_em_data_http_e_invalido():
    from datetime import datetime, timezone

    from jobradar.collectors.base import retry_after
    agora = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
    assert retry_after("7", 2.0, agora) == 7.0
    assert retry_after("Tue, 17 Nov 2026 12:00:30 GMT", 2.0, agora) == 30.0
    assert retry_after("Tue, 17 Nov 2026 11:59:00 GMT", 2.0, agora) == 0.0   # data no passado: não espera
    assert retry_after("amanhã", 2.0, agora) == 2.0 and retry_after(None, 2.0, agora) == 2.0


def _esperas(monkeypatch):
    import jobradar.collectors.base as base
    esperas: list[float] = []
    monkeypatch.setattr(base.time, "sleep", esperas.append)
    return esperas


def test_backoff_tem_jitter_e_respeita_retry_after(monkeypatch):
    esperas = _esperas(monkeypatch)
    c = GupyCollector({"urls": ["https://a.gupy.io"]},
                      client=_cliente([(503, {}), (200, {"data": [], "pagination": {"total": 0}})]))
    c._get("https://a.gupy.io", {}, CollectResult("gupy"))
    assert 2.0 <= esperas[0] <= 2.5          # 2^1 com até +25% de jitter

    def h(req, fila=[httpx.Response(429, headers={"Retry-After": "5"}), httpx.Response(200, json={})]):
        return fila.pop(0)
    c = GupyCollector({}, client=httpx.Client(transport=httpx.MockTransport(h)))
    esperas.clear()
    c._get("https://a.gupy.io", {}, CollectResult("gupy"))
    assert esperas == [5.0]


def test_retry_after_acima_do_teto_desiste_sem_esperar(monkeypatch):
    esperas = _esperas(monkeypatch)
    c = GupyCollector({}, client=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(429, headers={"Retry-After": "3600"}))))
    r = CollectResult("gupy")
    with pytest.raises(SourceError, match="Retry-After"):
        c._get("https://a.gupy.io", {}, r)
    assert r.requests == 1 and esperas == []


# ---------------------------------------------------------------- métricas por quadro (empresa)
def test_metricas_por_quadro_e_falha_de_um_quadro_nao_derruba_os_outros():
    def h(req):
        token = req.url.path.split("/")[3]   # /v1/boards/<token>/jobs
        if token == "fora":
            return httpx.Response(404)
        if token == "mudou":
            return httpx.Response(200, json={"vagas": []})            # schema mudou: sem "jobs"
        return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Data Engineer"},
                                                  {"id": 2, "title": "Vendas"}], "meta": {"total": 2}})
    g = GreenhouseCollector({"empresas": ["ok", "fora", "mudou"], "titulo_contem": ["data"]},
                            client=httpx.Client(transport=httpx.MockTransport(h)))
    g.pause = 0
    r = g.collect([])
    assert [x["id"] for x in r.records] == [1] and r.quadros == {"ok": ["1", "2"]}
    ok, fora, mudou = r.por_quadro["ok"], r.por_quadro["fora"], r.por_quadro["mudou"]
    assert ok["ok"] and ok["completo"] and (ok["vagas_listadas"], ok["vagas_mantidas"], ok["requisicoes"]) == (2, 1, 1)
    assert not fora["ok"] and "404" in fora["erro"] and fora["requisicoes"] == 1
    assert not mudou["ok"] and "formato mudou" in mudou["erro"]
    assert len(r.errors) == 2 and not r.ok


def test_lever_com_resposta_fora_do_formato_registra_erro_do_quadro():
    v = LeverCollector({"empresas": ["y"]}, client=_cliente([(200, {"erro": "x"})]))
    v.pause = 0
    r = v.collect([])
    assert r.records == [] and not r.por_quadro["y"]["ok"] and "formato mudou" in r.errors[0]

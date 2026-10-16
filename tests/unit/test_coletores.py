import httpx
import pytest

from jobradar.collectors import AdzunaCollector, GupyCollector
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

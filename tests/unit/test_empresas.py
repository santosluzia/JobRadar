"""Catálogo de empresas (config/empresas.yaml), coletores alimentados por ele e situação por empresa."""
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from pydantic import ValidationError

from jobradar.collectors import GreenhouseCollector, LeverCollector, build_collectors
from jobradar.empresas import carregar_catalogo, situacao
from jobradar.empresas.catalogo import API_URL
from jobradar.settings import CONFIG_DIR, carregar
from jobradar.storage import Lake

# As 13 empresas que estavam em sources.yaml antes do catálogo: a migração não pode mudar a coleta.
GREENHOUSE_ANTES = ["quintoandar", "ebanx", "wildlifestudios", "vtex", "c6bank", "stone", "rdstation", "jusbrasil",
                    "xpinc", "btgpactual", "inter", "agibank"]


def _empresa(**kw):
    base = {"id": "acme", "nome": "Acme", "pais": "BR", "segmento": "tecnologia", "ats": "greenhouse",
            "board": "acme", "status": "ativa", "verificada_em": date(2026, 11, 1)}
    return {**base, **kw}


def test_catalogo_versionado_e_valido_e_preserva_as_empresas_coletadas(tmp_path):
    s = carregar(lake=tmp_path, config_dir=CONFIG_DIR)
    cat = carregar_catalogo(s.empresas)
    assert cat.quadros_ativos("greenhouse") == GREENHOUSE_ANTES
    assert cat.quadros_ativos("lever") == ["ciandt"]
    assert all(e.verificada_em and e.pais == "BR" for e in cat.empresas)
    coletores = {c.name: c.cfg["empresas"] for c in build_collectors(s) if c.name in ("greenhouse", "lever")}
    assert coletores == {"greenhouse": GREENHOUSE_ANTES, "lever": ["ciandt"]}


def test_url_da_api_no_catalogo_e_a_mesma_dos_coletores():
    assert API_URL["greenhouse"].format(board="x") == GreenhouseCollector.URL.format(token="x")
    assert API_URL["lever"].format(board="x") == LeverCollector.URL.format(empresa="x")
    e = carregar_catalogo({"empresas": [_empresa()]}).empresas[0]
    assert e.api_url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    assert e.pagina_ats == "https://boards.greenhouse.io/acme"


@pytest.mark.parametrize("empresas", [
    [_empresa(), _empresa(board="outro")],                       # id repetido
    [_empresa(), _empresa(id="acme2")],                          # mesmo quadro duas vezes
    [_empresa(ats="gupy")],                                      # ativa sem coletor
    [_empresa(board=None)],                                      # ativa sem quadro
    [_empresa(verificada_em=None)],                              # ativa sem verificação
    [_empresa(pais="br")],                                       # país fora do ISO alfa-2
    [_empresa(site="http://acme.com")],                          # site sem https
    [_empresa(segmento="startup")],                              # segmento fora da lista
    [_empresa(api="https://x")],                                 # campo não previsto
])
def test_catalogo_invalido_e_recusado(empresas):
    with pytest.raises(ValidationError):
        carregar_catalogo({"empresas": empresas})


def test_candidata_de_ats_sem_coletor_e_aceita_mas_nao_e_coletada():
    cat = carregar_catalogo({"empresas": [
        _empresa(), _empresa(id="beta", ats="workday", board="beta", status="candidata", verificada_em=None,
                             origem="descoberta"),
        _empresa(id="gama", board="gama", status="pausada")]})
    assert cat.quadros_ativos("greenhouse") == ["acme"] and cat.quadros_ativos("workday") == []


def test_lista_antiga_em_sources_yaml_soma_ao_catalogo_sem_repetir(tmp_path):
    s = carregar(lake=tmp_path, config_dir=CONFIG_DIR)
    s.empresas = {"empresas": [_empresa(board="Acme")]}
    s.sources["fontes"]["greenhouse"] = {"ativo": True, "empresas": ["Acme", "legado"]}
    s.sources["fontes"]["lever"] = {"ativo": True}
    gh = [c for c in build_collectors(s) if c.name == "greenhouse"]
    assert gh and gh[0].cfg["empresas"] == ["Acme", "legado"]
    assert not [c for c in build_collectors(s) if c.name == "lever"]   # sem empresa ativa, sem coletor


def test_situacao_cruza_catalogo_com_as_coletas_por_quadro(tmp_path):
    lake = Lake(tmp_path)
    t = [datetime(2026, 11, d, 12, tzinfo=timezone.utc) for d in (1, 2, 3)]
    lake.append("meta/board_runs", pd.DataFrame([
        {"run_id": "r1", "source": "greenhouse", "quadro": "acme", "ok": True, "completo": True,
         "vagas_listadas": 40, "vagas_mantidas": 6, "finalizada_em": t[0]},
        {"run_id": "r2", "source": "greenhouse", "quadro": "acme", "ok": True, "completo": True,
         "vagas_listadas": 42, "vagas_mantidas": 7, "finalizada_em": t[1]},
        {"run_id": "r3", "source": "greenhouse", "quadro": "acme", "ok": False, "completo": False,
         "vagas_listadas": 0, "vagas_mantidas": 0, "erro": "HTTP 503", "finalizada_em": t[2]},
        {"run_id": "r3", "source": "lever", "quadro": "acme", "ok": True, "completo": True,   # outra plataforma
         "vagas_listadas": 1, "vagas_mantidas": 1, "finalizada_em": t[2]},
    ]))
    cat = carregar_catalogo({"empresas": [_empresa(), _empresa(id="nova", board="nova")]})
    tab = situacao(cat, lake).set_index("id")
    acme = tab.loc["acme"]
    assert acme["ultima_coleta_ok"] == t[1] and acme["ultima_tentativa"] == t[2]
    assert acme["falhas_seguidas"] == 1 and not acme["ultima_ok"]
    assert (acme["vagas_listadas"], acme["vagas_mantidas"]) == (42, 7)
    nova = tab.loc["nova"]
    assert pd.isna(nova["ultima_coleta_ok"]) and nova["falhas_seguidas"] == 0

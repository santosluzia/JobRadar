"""Painel Streamlit: cada página renderiza sem erro com lake vazio e com lake populado."""
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from jobradar import pipeline

from ..conftest import AGORA

APP = Path(__file__).resolve().parents[2] / "app"
PAGINAS = sorted((APP / "pages").glob("*.py"))


@pytest.fixture(autouse=True)
def _caminho(monkeypatch):
    import streamlit as st
    monkeypatch.syspath_prepend(str(APP))
    st.cache_resource.clear()
    st.cache_data.clear()
    yield
    sys.modules.pop("components", None)
    sys.modules.pop("components.data", None)


def _rodar(pagina: Path, lake: Path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_LAKE", str(lake))
    at = st_testing.AppTest.from_file(str(pagina), default_timeout=30)
    at.run()
    return at


@pytest.mark.parametrize("pagina", PAGINAS, ids=lambda p: p.stem)
def test_pagina_com_lake_vazio_mostra_estado_informativo(pagina, tmp_path, monkeypatch):
    at = _rodar(pagina, tmp_path / "vazio", monkeypatch)
    assert not at.exception
    assert any("Ainda não há dados" in i.value for i in at.info)


@pytest.mark.parametrize("pagina", PAGINAS, ids=lambda p: p.stem)
def test_pagina_com_dados(pagina, settings, fake, monkeypatch):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    at = _rodar(pagina, settings.lake, monkeypatch)
    assert not at.exception, at.exception
    assert not any("Ainda não há dados" in i.value for i in at.info)

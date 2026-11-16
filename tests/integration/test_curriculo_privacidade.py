"""Etapa 3 — privacidade e segurança do currículo, e análise separada por objetivo.

O canário é um texto único colocado no currículo fictício: ele não pode aparecer em NENHUM arquivo
publicado, no lake (que vai para o git), nem na saída do pipeline/publicação/e-mail.
"""
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from jobradar import pipeline
from jobradar.curriculo import servico, versoes
from jobradar.publishing import construir, publicar
from jobradar.settings import ROOT, carregar
from jobradar.storage import Lake
from jobradar.transformations.skills import Taxonomy

from ..conftest import AGORA, CONFIG_DIR

CANARIO = "CANARIO-7f3a9c-NAO-PODE-VAZAR"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "curriculo_ficticio.txt"
PERFIL_2_OBJETIVOS = {
    "objetivos": [{"id": "engenharia", "nome": "Engenharia de Dados", "familias": ["engenharia_dados"]},
                  {"id": "analytics", "nome": "Analytics Engineering", "familias": ["analytics_engineering"]}],
    "competencias": [{"skill": "sql", "nivel": "profissional"}, {"skill": "python", "nivel": "projeto"}],
}


def _cv_com_canario() -> bytes:
    texto = FIXTURE.read_text(encoding="utf-8").replace("Empresa Fictícia S.A.", f"Empresa {CANARIO}")
    return texto.replace("Integração de dados", f"Integração de dados ({CANARIO})").encode("utf-8")


def _todos_os_bytes(raiz: Path) -> bytes:
    return b"".join(p.read_bytes() for p in raiz.rglob("*") if p.is_file())


def test_canario_do_curriculo_nao_vaza(settings, fake, tmp_path, capsys, caplog):
    tax = Taxonomy(settings.skills)
    cv = servico.importar(_cv_com_canario(), "cv.txt", tax, guardar_original=True)
    assert CANARIO in versoes.pasta().joinpath("versoes", f"{cv.versao_id}.json").read_text(encoding="utf-8")

    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    servico.diagnostico(settings, salvar=True, agora=AGORA)               # o diagnóstico também é local
    publicar(construir(settings, AGORA, "r1"), tmp_path / "public_out", "r1", AGORA)
    from jobradar.notifications import renderizar, selecionar
    vagas, _ = selecionar(settings, AGORA)
    assunto, html, texto = renderizar(vagas, AGORA, {}, [])

    canario = CANARIO.encode()
    assert canario not in _todos_os_bytes(tmp_path / "public_out")      # dados públicos
    assert canario not in _todos_os_bytes(settings.lake)                # lake = repositório git privado
    assert CANARIO not in assunto + html + texto                       # e-mail
    saida = capsys.readouterr()
    assert CANARIO not in saida.out + saida.err + caplog.text           # logs
    assert not str(versoes.pasta()).startswith(str(settings.lake))      # pasta privada fora do lake


def test_pipeline_publicacao_e_email_nao_importam_o_curriculo():
    codigo = ("import sys, jobradar.pipeline, jobradar.publishing, jobradar.notifications, jobradar.cli; "
              "print([m for m in sys.modules if m.startswith('jobradar.curriculo')])")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[]"


def test_curriculo_funciona_sem_rede(settings, fake, monkeypatch):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)

    def bloqueado(*a, **k):
        raise AssertionError("o módulo de currículo tentou acessar a rede")
    monkeypatch.setattr(socket.socket, "connect", bloqueado)
    monkeypatch.setattr(socket, "create_connection", bloqueado)
    servico.importar(_cv_com_canario(), "cv.txt", Taxonomy(settings.skills))
    assert servico.diagnostico(settings, agora=AGORA)


def test_score_e_diagnostico_separados_por_objetivo(tmp_path, fake):
    lake = tmp_path / "lake"
    (lake / "private").mkdir(parents=True)
    (lake / "private" / "profile.yaml").write_text(yaml.safe_dump(PERFIL_2_OBJETIVOS), encoding="utf-8")
    s = carregar(lake=lake, config_dir=CONFIG_DIR)
    pipeline.run(s, fake.collectors(s), run_id="r1", agora=AGORA)
    sc = Lake(lake).read("gold/job_scores")
    assert set(sc["objetivo_id"]) == {"engenharia", "analytics"}
    assert (sc.groupby("job_id")["objetivo_id"].nunique() == 2).all()      # uma nota por objetivo, não uma média
    servico.importar(FIXTURE.read_bytes(), "cv.txt", Taxonomy(s.skills))
    diags = {d["objetivo_id"]: d for d in servico.diagnostico(s, agora=AGORA + timedelta(hours=1))}
    assert set(diags) == {"engenharia", "analytics"}
    eng, ae = diags["engenharia"], diags["analytics"]
    assert eng["familias"] == ["engenharia_dados"] and ae["familias"] == ["analytics_engineering"]
    assert eng["vagas_alvo"] != ae["vagas_alvo"]                       # vagas-alvo diferentes
    for d in diags.values():
        for lente in ("perfil", "curriculo"):
            v = d["aderencia"][lente]["valor"]
            assert v is None or 0 <= v <= 100
        assert "Não é previsão de contratação" in d["aviso"]
        assert d["amostra_pequena"] is True                            # fixture tem poucas vagas
    # o modelo de perfil do repositório é válido e mostra vários objetivos
    from jobradar.scoring import Profile
    exemplo = Profile.from_dict(yaml.safe_load((ROOT / "config" / "profile.example.yaml").read_text(encoding="utf-8")))
    assert len(exemplo.objetivos) >= 2


def test_mudanca_de_perfil_recalcula_e_remove_objetivo_antigo(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    assert set(Lake(settings.lake).read("gold/job_scores")["objetivo_id"]) == {"principal"}
    settings.profile = PERFIL_2_OBJETIVOS
    pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    assert set(Lake(settings.lake).read("gold/job_scores")["objetivo_id"]) == {"engenharia", "analytics"}


@pytest.mark.parametrize("mod", ["publishing/exporter.py", "publishing/contract.py", "pipeline.py",
                                 "notifications/email.py"])
def test_codigo_publico_nao_le_a_pasta_privada(mod):
    fonte = (ROOT / "src" / "jobradar" / mod).read_text(encoding="utf-8")
    assert "JOBRADAR_HOME" not in fonte and "curriculo" not in fonte

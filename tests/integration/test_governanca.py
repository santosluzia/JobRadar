"""Etapa 8 — governança, segurança e qualidade.

Fronteira público × privado, separação do score (workflow privado), registro de validações, máscara de
segredos, configuração do painel, retenção/apagamento dos dados pessoais locais e monitoramento.
"""
import json
import tomllib
from pathlib import Path

import pandas as pd
import pytest
import yaml

from jobradar import cli, pipeline
from jobradar.publishing import construir, publicar
from jobradar.settings import ROOT
from jobradar.storage import Lake
from jobradar.validacoes import validar_configuracoes

from ..conftest import AGORA


# ---------------------------------------------------------------- score fora do workflow público
def test_sem_pontuacao_nao_usa_o_perfil_e_pontuar_completa_depois(settings, fake, monkeypatch):
    import jobradar.pipeline as mod

    def proibido(*_a, **_k):
        raise AssertionError("o fluxo público não pode usar o perfil")

    monkeypatch.setattr(mod, "perfil_efetivo", proibido)
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA, pontuar=False)
    assert rep.vagas_pontuadas == 0
    assert pipeline.reextrair(settings, agora=AGORA, todas=True, pontuar=False)["vagas_pontuadas"] == 0
    lake = Lake(settings.lake)
    assert lake.read("gold/job_scores").empty
    monkeypatch.undo()

    assert pipeline.pontuar(settings, AGORA) > 0               # workflow privado
    scores = lake.read("gold/job_scores")
    assert not scores.empty and scores["perfil_hash"].nunique() == 1
    assert pipeline.pontuar(settings, AGORA) == 0              # incremental: nada mudou, nada recalcula


def test_cli_sem_pontuacao_descarta_o_perfil_da_memoria(settings, fake, monkeypatch):
    monkeypatch.setattr(cli, "build_collectors", lambda s: fake.collectors(s))
    assert settings.profile
    vistos = {}
    original = pipeline.run

    def espiao(s, *a, **k):
        vistos["perfil"] = dict(s.profile)
        return original(s, *a, agora=AGORA, **k)

    monkeypatch.setattr(pipeline, "run", espiao)
    args = type("A", (), {"run_id": "r1", "report": None, "sem_pontuacao": True})()
    cli.cmd_run(args, settings)
    assert vistos["perfil"] == {} and settings.profile_path is None
    validacoes = Lake(settings.lake).read("meta/validacoes")
    assert set(validacoes["artefato"]) == {"taxonomia"}         # público só valida o que é público
    assert Lake(settings.lake).read("private/validacoes").empty


# ---------------------------------------------------------------- validações registradas
def test_validacoes_de_configuracao_vao_para_tabelas_separadas(settings):
    lake = Lake(settings.lake)
    r = validar_configuracoes(settings, lake, "r1", incluir_privadas=True, agora=AGORA)
    assert {x["artefato"] for x in r} == {"taxonomia", "perfil", "radar_config"}
    assert all(x["ok"] for x in r)
    assert set(lake.read("meta/validacoes")["artefato"]) == {"taxonomia"}
    assert set(lake.read("private/validacoes")["artefato"]) == {"perfil", "radar_config"}


def test_perfil_invalido_registra_so_contagem_e_campo(settings):
    settings.profile = {"competencias": [{"skill": "sql", "nivel": "SEGREDO-PESSOAL-123"}]}
    lake = Lake(settings.lake)
    r = validar_configuracoes(settings, lake, "r2", incluir_privadas=True, agora=AGORA)
    perfil = next(x for x in r if x["artefato"] == "perfil")
    assert perfil["ok"] is False and perfil["erros"] >= 1
    linha = lake.read("private/validacoes").iloc[-1]
    assert "SEGREDO-PESSOAL-123" not in str(linha["detalhe"])


def test_publicacao_registra_validacao_do_contrato(settings, fake, tmp_path):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    args = type("A", (), {"out": str(tmp_path / "pub"), "run_id": "r1"})()
    assert cli.cmd_publish(args, settings) == 0
    v = Lake(settings.lake).read("meta/validacoes")
    linha = v[v["artefato"] == "contrato_publico"].iloc[-1]
    assert bool(linha["ok"]) and linha["versao"]


# ---------------------------------------------------------------- fronteira público × privado
CANARIO = "CANARIO-E8-b41d-NAO-PODE-VAZAR"


def test_canario_em_todo_dado_privado_nunca_chega_ao_publico(settings, fake, tmp_path):
    lake_dir = settings.lake
    perfil = dict(settings.profile)
    perfil["competencias"] = list(perfil["competencias"]) + [
        {"skill": "dbt", "nivel": "projeto", "evidencias": [f"projeto {CANARIO}"]}]
    (lake_dir / "private" / "profile.yaml").write_text(yaml.safe_dump(perfil, allow_unicode=True), encoding="utf-8")
    settings.profile = perfil
    (lake_dir / "private" / "radar.yaml").write_text(
        yaml.safe_dump({"ativo": True, "assunto": CANARIO}, allow_unicode=True), encoding="utf-8")
    (lake_dir / "private" / "curriculo_resumo.json").write_text(json.dumps({"nota": CANARIO}), encoding="utf-8")
    lake = Lake(lake_dir)
    lake.append("private/study_progress", pd.DataFrame([{
        "skill_id": "dbt", "status": "em_andamento", "evidencia": CANARIO, "atualizado_em": AGORA}]))

    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    destino = publicar(construir(settings, AGORA, "r1"), tmp_path / "pub", "r1", AGORA)
    publicado = b"".join(p.read_bytes() for p in destino.rglob("*") if p.is_file())
    assert publicado and CANARIO.encode() not in publicado
    for tabela in ("silver/jobs", "gold/skill_pairs", "meta/runs", "meta/source_runs", "meta/validacoes"):
        assert CANARIO not in lake.read(tabela).to_csv()


def test_publicacao_nao_le_nada_de_private_nem_de_score():
    """Checagem estática: o código que monta o contrato público não referencia tabelas privadas."""
    pasta = ROOT / "src" / "jobradar" / "publishing"
    for arq in pasta.glob("*.py"):
        texto = arq.read_text(encoding="utf-8")
        for proibido in ('"private/', "'private/", "job_scores", "profile", "perfil_efetivo", "curriculo"):
            assert proibido not in texto, f"{arq.name} referencia {proibido}"


# ---------------------------------------------------------------- segredos e painel
def test_mascara_de_segredos(monkeypatch):
    from jobradar.seguranca import mascarar
    monkeypatch.setenv("SMTP_PASSWORD", "senhaSuperSecreta99")
    t = mascarar("GET https://api.adzuna.com/x?app_id=abc123&app_key=zzzKEY&what=dados "
                 "falhou; login senhaSuperSecreta99; Authorization: Bearer abcdefghijklmnop")
    for segredo in ("abc123", "zzzKEY", "senhaSuperSecreta99", "abcdefghijklmnop"):
        assert segredo not in t
    assert "what=dados" in t and "app_id=***" in t


def test_filtro_de_log_mascara(monkeypatch, caplog):
    import logging
    from jobradar.seguranca import FiltroSegredos
    log = logging.getLogger("jobradar.teste")
    caplog.handler.addFilter(FiltroSegredos())
    with caplog.at_level(logging.INFO):
        log.info("url %s", "https://x/?app_key=vazou")
    assert "vazou" not in caplog.text and "app_key=***" in caplog.text


def test_painel_so_local_e_sem_telemetria():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "localhost"
    assert cfg["browser"]["gatherUsageStats"] is False


def test_troca_atomica_tenta_de_novo_no_windows(tmp_path, monkeypatch):
    from jobradar.storage import lake as mod
    real = mod.os.replace
    falhas = {"n": 0}

    def instavel(a, b):
        if falhas["n"] < 2:
            falhas["n"] += 1
            raise PermissionError("arquivo em uso")
        return real(a, b)

    monkeypatch.setattr(mod.os, "replace", instavel)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    Lake(tmp_path).append("meta/validacoes", pd.DataFrame([{
        "run_id": "r", "artefato": "taxonomia", "versao": "2", "ok": True, "erros": 0, "detalhe": None,
        "em": AGORA}]))
    assert falhas["n"] == 2 and len(Lake(tmp_path).read("meta/validacoes")) == 1


def test_workflow_publico_desliga_score_e_email_com_a_variavel():
    wf = (ROOT / ".github" / "workflows" / "daily-pipeline.yml").read_text(encoding="utf-8")
    assert "vars.JOBRADAR_NOTIFICACAO_PRIVADA == 'true' && '--sem-pontuacao'" in wf
    assert "$SEM_PONTUACAO" in wf
    assert "vars.JOBRADAR_NOTIFICACAO_PRIVADA != 'true' && (github.event_name" in wf


# ---------------------------------------------------------------- retenção e apagamento
def _versao(home, i: int):
    from datetime import timedelta
    from jobradar.curriculo import versoes
    from jobradar.curriculo.estrutura import Curriculo
    quando = AGORA - timedelta(days=30 * (20 - i))
    cv = Curriculo(versao_id=quando.strftime("%Y%m%dT%H%M%S") + f"-{i:06x}", criado_em=quando, texto=f"v{i}")
    versoes.salvar(cv, home, original=b"original")
    return cv


def test_retencao_guarda_as_ultimas_versoes_e_apaga_diagnosticos_antigos(tmp_path):
    from jobradar import retencao
    from jobradar.curriculo import versoes
    from jobradar.privado import pasta_privada
    home = tmp_path / "home"
    ids = [_versao(home, i).versao_id for i in range(5)]
    raiz = versoes.pasta(home)
    (raiz / "diagnosticos" / "20200101T000000_x_obj.json").write_text("{}", encoding="utf-8")
    (raiz / "diagnosticos" / f"{AGORA:%Y%m%dT%H%M%S}_x_obj.json").write_text("{}", encoding="utf-8")
    (pasta_privada("evolucao", home) / "20200101T000000_obj.json").write_text("{}", encoding="utf-8")
    (pasta_privada("evolucao", home) / "notas_sem_data.json").write_text("{}", encoding="utf-8")

    r = retencao.limpar(home, {"max_versoes_curriculo": 3, "meses_diagnosticos": 24}, agora=AGORA)
    assert r["versoes_curriculo"] == 2 and r["diagnosticos"] == 1 and r["planos"] == 1
    assert [v["versao_id"] for v in versoes.listar(home)] == ids[2:]
    assert not list(raiz.glob(f"originais/{ids[0]}.*"))           # o original sai junto
    assert (pasta_privada("evolucao", home) / "notas_sem_data.json").exists()   # sem data no nome: fica
    assert retencao.limpar(home, {"max_versoes_curriculo": 3}, agora=AGORA)["versoes_curriculo"] == 0


def test_importacao_aplica_a_retencao(tmp_path, settings):
    from jobradar.curriculo import servico, versoes
    from jobradar.transformations.skills import Taxonomy
    home = tmp_path / "home"
    for i in range(3):
        _versao(home, i)
    texto = (Path(__file__).resolve().parents[1] / "fixtures" / "curriculo_ficticio.txt").read_bytes()
    servico.importar(texto, "cv.txt", Taxonomy(settings.skills), home, retencao={"max_versoes_curriculo": 2})
    assert len(versoes.listar(home)) == 2


def test_apagar_tudo_remove_pasta_local_e_resumo_no_lake(tmp_path, settings, monkeypatch):
    from jobradar.evolucao import resumo_cv
    home = tmp_path / "home_privada"            # a mesma do fixture autouse ($JOBRADAR_HOME)
    _versao(home, 1)
    resumo_cv.gravar(settings.lake, "v1", AGORA.isoformat(), "2.0.0", {"sql": "comprovada"})
    args = type("A", (), {"acao": "apagar-tudo", "confirmar": False})()
    assert cli.cmd_privacidade(args, settings) == 1             # sem --confirmar não apaga nada
    assert home.exists()
    args.confirmar = True
    assert cli.cmd_privacidade(args, settings) == 0
    assert not home.exists()
    assert resumo_cv.carregar(settings.lake) is None
    assert not (settings.lake / resumo_cv.HISTORICO).exists()
    assert (settings.lake / "private" / "profile.yaml").exists()   # perfil é configuração: fica


# ---------------------------------------------------------------- monitoramento
def test_saude_sem_alerta_logo_apos_execucao_e_custo_zero(settings, fake):
    from jobradar.analytics import saude
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    ind = saude.indicadores(Lake(settings.lake), AGORA)
    assert ind["custo_ia_usd"] == 0
    assert ind["execucao"]["total"] == 1 and ind["execucao"]["taxa_falha_7d_pct"] == 0
    assert {x["fonte"] for x in ind["extracao_por_fonte"]}
    # a fixture tem registros inválidos de propósito (12,5%): o alerta dispara no padrão (10%)…
    assert saude.alertas(ind) == ["registros inválidos em 7 dias: 12.5%"]
    assert saude.alertas(ind, {"invalidos_max_pct": 20}) == []        # …e o limite é configurável
    md = saude.markdown(ind, [])
    assert "Nenhum alerta" in md


def test_saude_alerta_execucao_parada_falhas_e_validacao(settings, fake):
    from datetime import timedelta
    from jobradar.analytics import saude
    from jobradar.validacoes import registrar
    lake = Lake(settings.lake)
    lake.append("meta/runs", pd.DataFrame([{
        "run_id": "r0", "iniciada_em": AGORA, "finalizada_em": AGORA, "status": "sucesso", "duracao_s": 60.0,
        "metricas": "{}"}]))
    lake.append("meta/runs", pd.DataFrame([{
        "run_id": f"f{i}", "iniciada_em": AGORA + timedelta(hours=i), "finalizada_em": AGORA + timedelta(hours=i),
        "status": "falha", "duracao_s": 5.0, "metricas": "{}"} for i in range(1, 4)]))
    lake.append("meta/source_runs", pd.DataFrame([{
        "run_id": f"f{i}", "source": "gupy", "ok": False, "coletados": 0, "validos": 0, "invalidos": 0,
        "duplicatas_fonte": 0, "novas": 0, "requisicoes": 1, "retentativas": 0, "erros": "x",
        "finalizada_em": AGORA + timedelta(hours=i)} for i in range(1, 4)]))
    registrar(lake, "f3", "contrato_publico", "1.1.0", False, 2, "contrato inválido", AGORA)
    al = saude.alertas(saude.indicadores(lake, AGORA + timedelta(hours=20)))
    texto = " | ".join(al)
    assert "sem execução bem-sucedida" in texto
    assert "taxa de falha" in texto
    assert "fonte gupy falhou nas últimas 3" in texto
    assert "contrato_publico" in texto


def test_rodape_do_radar_mostra_alerta_de_saude(settings, fake, monkeypatch, tmp_path):
    from jobradar.analytics import saude
    from jobradar.notifications import radar
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    settings.filtros["score_minimo"] = 0
    monkeypatch.setattr(saude, "alertas", lambda ind, cfg=None: ["fonte gupy falhou nas últimas 3 execuções"])
    html = tmp_path / "radar.html"
    radar.enviar(settings, AGORA, "r1", turno=1, dry_run=True, html_out=html)
    corpo = html.read_text(encoding="utf-8")
    assert "Saúde do JobRadar" in corpo and "fonte gupy falhou" in corpo


def test_actions_fixadas_por_sha():
    """Tag de action é móvel (pode ser trocada por quem controla o repositório da action); SHA não."""
    import re
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        for linha in wf.read_text(encoding="utf-8").splitlines():
            if "uses:" in linha:
                assert re.search(r"@[0-9a-f]{40}\s+#\s*v\d", linha), f"{wf.name}: {linha.strip()}"

"""Etapa 1: camada semântica local (com codificador FALSO — os testes nunca baixam modelo),
conjunto-ouro/métricas e fila de candidatas."""
import hashlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from jobradar.analytics.candidatas import candidatas
from jobradar.avaliacao import ConjuntoOuro, ItemOuro, avaliar, carregar_ouro, relatorio, salvar_ouro
from jobradar.semantic import ExtratorSemantico, enriquecer, pendentes
from jobradar.semantic.modelo import ModeloInvalido, conferir
from jobradar.settings import CONFIG_DIR, _yaml
from jobradar.storage import Lake
from jobradar.transformations.skills import SkillMatch, Taxonomy
from jobradar.transformations.text import normalizar

TAX = Taxonomy(_yaml(CONFIG_DIR / "skills.yaml"))
AGORA = datetime(2026, 11, 11, tzinfo=timezone.utc)
VOCAB = ["pipeline", "ingest", "integr", "qualidade", "consist", "governan", "catalog", "monitor", "observab",
         "tempo real", "evento", "distribu", "volume", "modelag", "dimension", "machine", "intelig", "python",
         "consulta", "relacion", "versionamento", "continua", "warehouse", "armazem", "lake", "camada"]


def codificador_falso(textos: list[str]) -> np.ndarray:
    """Saco de radicais: frases com os mesmos radicais ficam parecidas. Determinístico e offline."""
    return np.array([[1.0 if v in normalizar(t) else 0.0 for v in VOCAB] for t in textos])


def _job(job_id, titulo, desc):
    return {"job_id": job_id, "titulo": titulo, "descricao": desc, "descricao_hash": job_id + "h",
            "is_canonica": True}


# ---------------------------------------------------------------- camada semântica
def test_semantica_so_complementa_e_respeita_limiar_e_contexto():
    ext = ExtratorSemantico(TAX, codificador_falso, limiar=0.7, limiar_media=0.9)
    desc = ("Somos referência em qualidade e consistência de serviços.\n"          # contexto: ignorado
            "Responsabilidades:\nAssegurar consistência e qualidade das bases entregues aos clientes.")
    achados = {a.skill_id: a for a in ext.extrair("Analista", desc, set())}
    assert "qualidade_dados" in achados
    a = achados["qualidade_dados"]
    assert a.evidencia.startswith("Assegurar") and a.importancia == "requisito" and a.similaridade >= 0.7
    assert a.confianca in {"media", "baixa"}
    # competência já achada pelas regras não é repetida
    assert "qualidade_dados" not in {x.skill_id for x in ext.extrair("Analista", desc, {"qualidade_dados"})}
    # frase só parecida (similaridade ~0,71) não passa de um limiar alto
    parecida = "Requisitos:\nCuidar da qualidade do atendimento aos clientes."
    assert ExtratorSemantico(TAX, codificador_falso, 0.95, 1.0).extrair("Analista", parecida, set()) == []
    assert ExtratorSemantico(TAX, codificador_falso, 0.65, 1.0).extrair("Analista", parecida, set())


def test_titulo_nao_e_evidencia_semantica():
    ext = ExtratorSemantico(TAX, codificador_falso, limiar=0.5, limiar_media=0.9)
    assert ext.extrair("Engenheiro de qualidade e consistência", "Requisitos:\nExcel.", set()) == []


def test_enriquecer_e_incremental(tmp_path):
    lake = Lake(tmp_path)
    jobs = pd.DataFrame([_job("j1", "Analista", "Requisitos:\nAssegurar consistência e qualidade das bases."),
                         _job("j2", "Analista", "Requisitos:\nExcel avançado.")])
    alvo = pendentes(jobs, lake.read("silver/job_skills_semantica"), TAX)
    assert len(alvo) == 2
    assert enriquecer(lake, TAX, alvo, pd.DataFrame(columns=["job_id", "skill_id"]), "r1", AGORA, codificador_falso) == 2
    sem = lake.read("silver/job_skills_semantica")
    assert set(sem["job_id"]) == {"j1", "j2"}                        # j2 registrada mesmo sem achado
    assert sem.loc[sem["job_id"] == "j2", "skill_id"].isna().all()
    assert (sem["taxonomia_versao"] == TAX.versao).all() and sem["modelo_revisao"].notna().all()
    assert pendentes(jobs, sem, TAX).empty                            # nada a refazer
    jobs.loc[0, "descricao_hash"] = "mudou"                           # descrição nova → só ela volta
    assert list(pendentes(jobs, sem, TAX)["job_id"]) == ["j1"]


def test_modelo_com_hash_errado_e_recusado(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"conteudo")
    certo = hashlib.sha256(b"conteudo").hexdigest()
    conferir(tmp_path, {"model.safetensors": certo})
    with pytest.raises(ModeloInvalido):
        conferir(tmp_path, {"model.safetensors": "0" * 64})
    with pytest.raises(ModeloInvalido):
        conferir(tmp_path, {"tokenizer.json": certo})               # arquivo ausente


def test_camada_semantica_vem_desligada_e_fixada():
    cfg = TAX.config.extracao
    assert cfg.semantica.ativa is False and cfg.gold_hibrida is False
    assert len(cfg.semantica.revisao) == 40 and all(len(h) == 64 for h in cfg.semantica.sha256.values())


# ---------------------------------------------------------------- conjunto-ouro e métricas
def _item(job_id, comp, desejaveis=(), revisado=True, lote="teste", fonte="gupy"):
    return ItemOuro(job_id=job_id, fonte=fonte, familia="engenharia_dados", titulo="Data Engineer",
                    descricao="x", competencias=list(comp), desejaveis=list(desejaveis), revisado=revisado, lote=lote)


def test_metricas_de_precisao_recall_e_importancia():
    itens = [_item("a", ["sql", "python"], desejaveis=["python"]), _item("b", ["etl"], fonte="adzuna")]
    saida = {"a": [SkillMatch("sql", "requisito", "sql"), SkillMatch("python", "requisito", "python"),
                   SkillMatch("aws", "requisito", "aws")],
             "b": []}
    m = avaliar("teste", itens, lambda i: saida[i.job_id], TAX)
    assert (m.geral.tp, m.geral.fp, m.geral.fn) == (2, 1, 1)
    assert m.geral.precisao == pytest.approx(2 / 3) and m.geral.recall == pytest.approx(2 / 3)
    assert (m.importancia_ok, m.importancia_total) == (1, 2)          # python era desejável
    assert m.por_texto["trecho"].fn == 1
    texto = relatorio([m])
    assert "66.7%" in texto and "Data Engineer" not in texto           # relatório só tem agregados


def test_ouro_salva_carrega_e_filtra_rascunhos_e_lote(tmp_path):
    c = ConjuntoOuro(taxonomia_versao=TAX.versao, itens=[
        _item("a", ["sql"]), _item("b", ["sql"], revisado=False), _item("c", ["sql"], lote="ajuste"),
        ItemOuro(job_id="d", fonte="gupy", familia="analise_dados", titulo="t", descricao="linha 1\nlinha 2")])
    salvar_ouro(tmp_path, c)
    lido = carregar_ouro(tmp_path)
    assert [i.job_id for i in lido.anotados()] == ["a", "c"]
    assert [i.job_id for i in lido.anotados(incluir_rascunhos=True, lote="teste")] == ["a", "b"]
    assert lido.itens[3].descricao == "linha 1\nlinha 2" and lido.itens[3].competencias is None


# ---------------------------------------------------------------- fila de candidatas
def test_candidatas_trazem_ferramenta_nova_e_ignoram_o_coberto_e_o_generico():
    dados = [{"job_id": f"d{i}", "titulo": "Engenheiro de Dados", "familia": "engenharia_dados",
              "descricao": f"Requisitos:\nExperiência com Python e Dataform no projeto {i}.\nVisão de dados.",
              "is_canonica": True, "primeira_observacao": AGORA} for i in range(8)]
    outras = [{"job_id": f"o{i}", "titulo": "Vendedor", "familia": "outra",
               "descricao": "Requisitos:\nExperiência com vendas e visão de dados.", "is_canonica": True,
               "primeira_observacao": AGORA} for i in range(8)]
    df = candidatas(pd.DataFrame(dados + outras), TAX, ["engenharia_dados"], AGORA, min_vagas=5)
    termos = set(df["termo"])
    assert "dataform" in termos
    assert not termos & {"python", "experiencia", "visao", "projeto"}  # coberto pela taxonomia / genérico


def test_candidatas_ignoram_cabecalho_fixo_de_ats():
    """Cabeçalho de anúncio ("Nível Acadêmico: … Turno/Horas Áreas de Atuação Profissional: TI") não é competência."""
    dados = [{"job_id": f"d{i}", "titulo": "Engenheiro de Dados", "familia": "engenharia_dados",
              "descricao": (f"Requisitos:\nExperiência com Dataform no projeto {i}.\n"
                            "Nível Acadêmico: Ensino Superior Completo Turno/Horas Áreas de Atuação Profissional: TI"),
              "is_canonica": True, "primeira_observacao": AGORA} for i in range(8)]
    termos = set(candidatas(pd.DataFrame(dados), TAX, ["engenharia_dados"], AGORA, min_vagas=5)["termo"])
    assert termos == {"dataform"}   # sem a regra: academico, turno/horas, areas, ensino, superior, completo…

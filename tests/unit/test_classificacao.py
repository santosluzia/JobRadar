"""PR F (ADR 0014): títulos em espanhol, lacunas de família, subfamília, idioma da vaga, idiomas exigidos,
migração do histórico, conjunto-ouro de classificação e retrato agregado."""
import json
from datetime import timedelta

import pandas as pd
import pytest

from jobradar.analytics import cargos
from jobradar.avaliacao import ClassificacaoOuro, ConjuntoOuro, IdiomaOuro, ItemOuro, amostrar_classificacao
from jobradar.avaliacao import classificacao as av_cls
from jobradar.models import Familia, Senioridade
from jobradar.settings import CONFIG_DIR, carregar
from jobradar.storage import Lake
from jobradar.transformations import classificacao as cl
from jobradar.transformations import normalize as n
from jobradar.transformations.skills import Taxonomy

from ..conftest import AGORA


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return Taxonomy(carregar(config_dir=CONFIG_DIR).skills)


# ------------------------------------------------------------------ família e senioridade (taxonomia 2.2.0)
@pytest.mark.parametrize("titulo, familia", [
    ("Ingeniero de Datos Sr", Familia.engenharia_dados),
    ("Ingeniero Big Data - Integración de Datos y CDC", Familia.engenharia_dados),
    ("Arquitecto de Datos", Familia.engenharia_dados),
    ("Engenheiro Big Data Sênior", Familia.engenharia_dados),
    ("Tech Lead - Arquitetura de Dados", Familia.engenharia_dados),
    ("Desarrollador ETL, AWS Glue y Serverless", Familia.desenvolvimento_dados),
    ("Administrador de Bases de Datos", Familia.administracao_dados),
    ("Analista de Datos", Familia.analise_dados),
    ("Analista Sr. de Dados, Automação e IA", Familia.analise_dados),
    ("Analista de Inteligência de Dados Pleno", Familia.analise_dados),
    ("Estágio em Análise de Dados", Familia.analise_dados),
    ("Assistente de BI", Familia.analise_dados),
    ("Analista de Product Analytics Pleno", Familia.analise_dados),
    ("Analista de Gestão de Dados Pleno", Familia.governanca_qualidade),
    ("Especialista en Gobierno de Datos", Familia.governanca_qualidade),
    # "Governança e Arquitetura de Dados" continua governança (a regra de arquitetura não rouba)
    ("Gerente de Governança e Arquitetura de Dados", Familia.governanca_qualidade),
    # cargos adjacentes continuam fora das famílias de dados
    ("Cientista de Dados Sênior", Familia.outra),
    ("Científico de Datos Jr", Familia.outra),
    ("Head de Dados", Familia.outra),
    ("Analytics Engineer Pleno", Familia.analytics_engineering),
])
def test_familia_por_titulo_em_portugues_e_espanhol(titulo, familia):
    assert n.familia(titulo, set())[0] == familia


def test_senioridade_em_espanhol():
    assert n.senioridade("Data Engineer Semi Senior", None)[0] == Senioridade.pleno
    assert n.senioridade("Ingeniero de Datos SSr", None)[0] == Senioridade.pleno
    assert n.senioridade("Ingeniero de Datos Senior", None)[0] == Senioridade.senior
    assert n.senioridade("Practicante de Datos", None)[0] == Senioridade.estagio
    assert n.senioridade("Jefe de Datos", None)[0] == Senioridade.lideranca


# ------------------------------------------------------------------ subfamília
@pytest.mark.parametrize("titulo, familia, esperado", [
    ("Arquiteto de Dados Sênior", "engenharia_dados", ("arquitetura_dados", "titulo")),
    ("Data Platform Engineer", "engenharia_dados", ("plataforma_dados", "titulo")),
    ("Engenheiro de Dados Pleno", "engenharia_dados", ("engenharia_dados", "familia")),
    ("Desenvolvedor PL/SQL Sênior", "desenvolvimento_dados", ("banco_dados", "titulo")),
    ("Desenvolvedor Power BI", "desenvolvimento_dados", ("bi_desenvolvimento", "titulo")),
    ("Desenvolvedor ETL", "desenvolvimento_dados", ("etl_integracao", "titulo")),
    ("Analista de BI", "analise_dados", ("bi_visualizacao", "titulo")),
    ("Analista de Dados", "analise_dados", ("analise_dados", "familia")),
    ("Master Data Quality Lead", "governanca_qualidade", ("mdm", "titulo")),
    ("Analista de Qualidade de Dados", "governanca_qualidade", ("qualidade_dados", "titulo")),
    ("Data Steward", "governanca_qualidade", ("governanca_dados", "familia")),
    ("Administrador de Dados Pleno", "administracao_dados", ("administracao_dados", "titulo")),
    ("Administrador de Banco de Dados", "administracao_dados", ("dba", "familia")),
    ("DBA Oracle", "administracao_dados", ("dba", "familia")),
    ("Cientista de Dados Sênior", "outra", ("ciencia_dados", "titulo")),
    ("Machine Learning Engineer", "outra", ("machine_learning", "titulo")),
    ("Data Product Manager", "outra", ("produto_dados", "titulo")),
    ("Gerente de Dados e Analytics", "outra", ("lideranca_dados", "titulo")),
    ("Clinical Scientist", "outra", ("fora_de_dados", "familia")),
    ("Desenvolvedor Fullstack", "outra", ("fora_de_dados", "familia")),
])
def test_subfamilia(titulo, familia, esperado):
    assert cl.subfamilia(titulo, familia) == esperado
    assert esperado[0] in cl.SUBFAMILIAS_VALIDAS[familia]


# ------------------------------------------------------------------ idioma da vaga
def test_idioma_da_vaga():
    pt = "Buscamos uma pessoa para atuar com dados. Você vai desenvolver pipelines e não terá rotina monótona."
    en = "We are looking for a data engineer to join our team and work with you on the platform."
    es = "Buscamos un ingeniero de datos con experiencia en el desarrollo de los pipelines y conocimientos de SQL."
    assert cl.idioma_vaga("Engenheiro de Dados", pt) == ("pt", "descricao")
    assert cl.idioma_vaga("Data Engineer", en) == ("en", "descricao")
    assert cl.idioma_vaga("Ingeniero de Datos", es) == ("es", "descricao")
    assert cl.idioma_vaga("Data Engineer", None) == ("indeterminado", "nao_informada")
    assert cl.idioma_vaga("Data Engineer", "Python, SQL, Spark") == ("indeterminado", "nao_informada")


# ------------------------------------------------------------------ idiomas exigidos
def _exig(tax, titulo, descricao, pais="BR"):
    c = cl.classificar(titulo, descricao, "engenharia_dados", tax, pais)
    return {e.idioma: (e.nivel, e.importancia, e.origem) for e in c.idiomas_exigidos}


def test_idiomas_exigidos_nivel_importancia_e_origem(tax):
    desc = ("Requisitos:\nPython e SQL.\nInglês avançado para reuniões com o time global.\n"
            "Diferenciais:\nEspanhol intermediário.")
    assert _exig(tax, "Engenheiro de Dados", desc) == {
        "en": ("avancado", "requisito", "descricao"), "es": ("intermediario", "desejavel", "descricao")}
    # no título
    assert _exig(tax, "Engenheiro de Dados (Inglês Fluente)", "Requisitos: Python.")["en"][:2] == ("fluente", "requisito")
    # nível mais alto entre as frases do mesmo peso
    assert _exig(tax, "Data Engineer", "Requisitos:\nInglês intermediário.\nInglês fluente desejável na conversação.")[
        "en"][1] == "requisito"


def test_idiomas_exigidos_ignora_beneficio_negacao_e_lingua_da_propria_vaga(tax):
    beneficio = ("Requisitos:\nPython e SQL.\nBenefícios:\nReembolso de curso de idiomas (inglês ou espanhol).")
    assert _exig(tax, "Engenheiro de Dados", beneficio) == {}
    assert _exig(tax, "Engenheiro de Dados", "Requisitos: SQL. Inglês não é necessário para a vaga.") == {}


def test_vaga_em_ingles_no_brasil_exige_ingles_inferido(tax):
    en = "We are looking for a data engineer to join our team. You will work with Spark and the data platform."
    assert _exig(tax, "Data Engineer", en) == {"en": ("nao_informado", "requisito", "idioma_da_vaga")}
    # vaga em espanhol na Colômbia: é a língua do país, não vira exigência
    es = "Buscamos un ingeniero de datos con experiencia en el desarrollo de los pipelines y conocimientos de SQL."
    assert _exig(tax, "Ingeniero de Datos", es, pais="CO") == {}
    # menção explícita vence a inferência
    en2 = en + " Requirements: fluent English."
    assert _exig(tax, "Data Engineer", en2)["en"] == ("fluente", "requisito", "descricao")


# ------------------------------------------------------------------ migração do histórico
def _jobs(**extra) -> pd.DataFrame:
    base = {"job_id": ["a", "b"], "titulo": ["Arquiteto de Dados", "Data Engineer"],
            "descricao": ["Buscamos uma pessoa para o time de dados e você vai desenhar a arquitetura. "
                          "Requisitos: Inglês avançado.", None], "familia": ["engenharia_dados"] * 2,
            "pais_iso": ["BR", "BR"], "origem_campos": [json.dumps({"familia": "titulo"}), None],
            "subfamilia": [None, None], "idioma_vaga": [None, "en"], "idiomas_exigidos": [None, "[]"],
            "classificacao_versao": [None, None]}
    base.update(extra)
    return pd.DataFrame(base)


def test_atualizar_migra_e_mantem_idioma_sem_descricao(tax):
    jobs, nmig = cl.atualizar(_jobs(), tax)
    assert nmig == 2 and (jobs["classificacao_versao"] == cl.CLASSIFICACAO_VERSAO).all()
    a, b = jobs.iloc[0], jobs.iloc[1]
    assert a["subfamilia"] == "arquitetura_dados" and a["idioma_vaga"] == "pt"
    assert json.loads(a["idiomas_exigidos"])[0]["nivel"] == "avancado"
    assert json.loads(a["origem_campos"]) == {"familia": "titulo", "subfamilia": "titulo", "idioma_vaga": "descricao"}
    # descrição já saiu pela retenção: mantém o idioma calculado antes
    assert b["idioma_vaga"] == "en" and b["subfamilia"] == "engenharia_dados"
    # segunda passada não refaz nada
    assert cl.atualizar(jobs, tax)[1] == 0
    # família mudou (reextrair): refaz a subfamília mesmo na versão atual
    jobs.loc[1, "familia"] = "outra"
    jobs2, nmig2 = cl.atualizar(jobs, tax, forcar_subfamilia={"b"})
    assert nmig2 == 1 and jobs2.iloc[1]["subfamilia"] == "fora_de_dados"


# ------------------------------------------------------------------ conjunto-ouro de classificação
def _item(titulo, descricao, familia, sub, idioma, idiomas=()):
    return ItemOuro(job_id=titulo, fonte="gupy", familia=familia, titulo=titulo, descricao=descricao,
                    classificacao=ClassificacaoOuro(familia=familia, subfamilia=sub, idioma_vaga=idioma,
                                                    idiomas=[IdiomaOuro(idioma=i, nivel=nv) for i, nv in idiomas]))


def test_medir_classificacao(tax):
    pt = "Buscamos uma pessoa para atuar com dados e você vai trabalhar com SQL. Requisitos: inglês avançado."
    itens = [
        _item("Engenheiro de Dados", pt, "engenharia_dados", "engenharia_dados", "pt", [("en", "avancado")]),
        _item("Analista de BI", pt, "analise_dados", "bi_visualizacao", "pt", [("en", "avancado")]),
        # rótulo diferente da previsão: erro de família, sem contar a subfamília
        _item("Cientista de Dados", pt, "analise_dados", "analise_dados", "pt", []),
    ]
    r = av_cls.medir(itens, tax)
    assert r.n == 3 and r.familia_acertos == 2 and r.subfamilia_n == 2 and r.subfamilia_acertos == 2
    assert r.idioma_acertos == 3 and r.confusoes[("analise_dados", "outra")] == 1
    assert r.exigencias["en"].tp == 2 and r.exigencias["en"].fp == 1 and r.nivel_acertos == 2
    assert r.amostra_pequena
    texto = av_cls.relatorio(r)
    assert "amostra pequena" in texto and "Família: F1 macro" in texto


def test_rotulados_separa_rascunho_de_revisado():
    a = _item("A", "x", "outra", "fora_de_dados", "pt")
    b = _item("B", "x", "outra", "fora_de_dados", "pt")
    b.classificacao.revisado = True
    c = ConjuntoOuro(taxonomia_versao="2.2.0", itens=[a, b, ItemOuro(job_id="c", fonte="gupy", familia="outra",
                                                                         titulo="C", descricao="x")])
    assert [i.job_id for i in c.rotulados()] == ["B"]
    assert len(c.rotulados(incluir_rascunhos=True)) == 2


def test_amostrar_classificacao_cobre_familias_adjacentes_e_idiomas(tmp_path):
    lake = Lake(tmp_path)
    linhas = []
    for k, (fam, sub, idioma) in enumerate([("engenharia_dados", "engenharia_dados", "pt")] * 5
                                           + [("outra", "fora_de_dados", "pt")] * 5
                                           + [("outra", "ciencia_dados", "pt")] * 3
                                           + [("analise_dados", "analise_dados", "en")] * 3):
        linhas.append({"job_id": f"j{k}", "source": "gupy", "titulo": f"T{k}", "descricao": "texto",
                       "familia": fam, "subfamilia": sub, "idioma_vaga": idioma, "is_canonica": True,
                       "pais_iso": "BR"})
    lake.write("silver/jobs", pd.DataFrame(linhas))
    c = amostrar_classificacao(lake, por_familia=2, adjacentes=2, outros_idiomas=1, taxonomia_versao="2.2.0")
    ids = [i.job_id for i in c.itens]
    # 2 por família (3 famílias) + 2 adjacentes + 1 fora do português (as en restantes)
    assert len(ids) == len(set(ids)) == 9
    assert sum(i.familia == "analise_dados" for i in c.itens) == 3
    assert all(i.competencias is None and i.classificacao is None for i in c.itens)
    # não repete vagas já sorteadas
    c2 = amostrar_classificacao(lake, por_familia=2, existente=c)
    assert len({i.job_id for i in c2.itens}) == len(c2.itens)


# ------------------------------------------------------------------ retrato agregado
def test_resumo_de_cargos():
    exig = json.dumps([{"idioma": "en", "nivel": "avancado", "importancia": "requisito", "origem": "descricao"}])
    jobs = pd.DataFrame({
        "is_canonica": [True, True, True, True],
        "primeira_observacao": [AGORA - timedelta(days=d) for d in (1, 2, 3, 60)],
        "familia": ["engenharia_dados", "engenharia_dados", "outra", "engenharia_dados"],
        "subfamilia": ["arquitetura_dados", "engenharia_dados", "ciencia_dados", "engenharia_dados"],
        "idioma_vaga": ["pt", "en", "pt", "pt"],
        "idiomas_exigidos": [exig, "[]", "[]", exig],
    })
    r = cargos.resumo(jobs, AGORA, ["engenharia_dados"], dias=30)
    assert r["vagas_dados"] == 2 and r["amostra_pequena"]
    assert r["adjacentes"] == {"ciencia_dados": 1}
    assert r["exige_ingles_pct"] == 50.0 and r["nivel_ingles"] == {"avancado": 1}
    assert "Cargos adjacentes" in cargos.markdown(r)

"""Assinatura de formato, detecção de mudança e qualidade por fonte (ADR 0013). Nada vai à internet."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from jobradar.analytics import qualidade_fontes as qf
from jobradar.analytics import saude
from jobradar.collectors import essenciais_por_fonte
from jobradar.collectors.assinatura import assinar, caminhos, comparar
from jobradar.storage import Lake

AGORA = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
ESS = ("id", "name", "jobUrl", "description")


def _gupy(n=20, **troca):
    base = {"id": 1, "name": "Engenheira de Dados", "jobUrl": "https://x.gupy.io/job/1", "description": "<p>SQL</p>",
            "city": "São Paulo", "badges": {"isPWD": True}, "_board": "interno"}
    regs = []
    for i in range(n):
        r = {**base, "id": i}
        for k, v in troca.items():
            if v is None:
                r.pop(k, None)
            else:
                r[k] = v
        regs.append(r)
    return regs


# ---------------------------------------------------------------- caminhos e assinatura
def test_caminhos_achata_dicionarios_e_listas_sem_valores_nulos_nem_anotacoes_internas():
    reg = {"id": 1, "titulo": None, "location": {"name": "SP", "area": ["BR", "SP"]},
           "departments": [{"name": "Dados", "id": 3}], "_board": "x", "ativo": True, "nota": 1.5}
    assert set(caminhos(reg)) == {("id", "numero"), ("location.name", "texto"), ("location.area[]", "lista"),
                                  ("departments[]", "lista"), ("departments[].name", "texto"),
                                  ("departments[].id", "numero"), ("ativo", "bool"), ("nota", "numero")}


def test_assinatura_tem_presenca_e_hash_que_ignora_campo_raro():
    regs = _gupy(20)
    a = assinar("gupy", regs, ESS)
    assert a.registros == 20 and a.campos["name"] == {"tipos": ["texto"], "presenca_pct": 100.0}
    assert a.essenciais == {"id": 100.0, "name": 100.0, "jobUrl": 100.0, "description": 100.0}
    regs[0]["salary"] = 5000                                        # 5%: abaixo da presença forte
    assert assinar("gupy", regs, ESS).hash == a.hash
    assert "_board" not in a.campos


# ---------------------------------------------------------------- comparação
def test_campo_essencial_renomeado_e_mudanca_grave():
    antes = assinar("gupy", _gupy(), ESS)
    depois = assinar("gupy", _gupy(name=None, title="Engenheira de Dados"), ESS)
    d = comparar(depois, antes)
    assert d["grave"] and d["essenciais_em_queda"] == ["name"] and d["removidos"] == ["name"] and d["novos"] == ["title"]


def test_tipo_trocado_em_campo_essencial_e_grave_e_em_campo_opcional_nao():
    antes = assinar("gupy", _gupy(), ESS)
    assert comparar(assinar("gupy", _gupy(id="abc"), ESS), antes)["grave"]
    d = comparar(assinar("gupy", _gupy(city=7), ESS), antes)
    assert d["mudou"] and not d["grave"] and d["tipos_alterados"] == ["city"]
    d = comparar(assinar("gupy", _gupy(city=["São Paulo"]), ESS), antes)   # texto → lista: o caminho muda
    assert not d["grave"] and d["removidos"] == ["city"] and d["novos"] == ["city[]"]


def test_campo_opcional_que_oscila_e_amostra_pequena_nao_viram_mudanca():
    com = _gupy(20)
    for r in com[:2]:
        r["salary_max"] = 9000                                      # 10% numa coleta, 0% na outra
    assert not comparar(assinar("gupy", com, ESS), assinar("gupy", _gupy(20), ESS))["mudou"]
    assert not comparar(assinar("gupy", _gupy(3, name=None), ESS), assinar("gupy", _gupy(), ESS))["comparada"]


def test_queda_forte_de_presenca_de_campo_essencial_e_grave():
    regs = _gupy(20)
    for r in regs[:10]:
        r.pop("description")                                        # 100% → 50%
    d = comparar(assinar("gupy", regs, ESS), assinar("gupy", _gupy(20), ESS))
    assert d["grave"] and d["essenciais_em_queda"] == ["description"] and d["removidos"] == []


# ---------------------------------------------------------------- registro, histórico e alerta
def test_registro_por_execucao_e_alerta_de_mudanca_grave_por_24h(tmp_path):
    lake = Lake(tmp_path)
    qf.registrar_execucao(lake, "r1", AGORA, [("gupy", _gupy(), ESS), ("adzuna", [], ())])
    linhas = qf.registrar_execucao(lake, "r2", AGORA + timedelta(hours=6), [("gupy", _gupy(name=None, title="x"), ESS)])
    tab = lake.read(qf.TABELA)
    assert list(tab["source"]) == ["gupy", "gupy"]                  # fonte sem registro não ganha linha
    assert not tab.iloc[0]["comparada"] and linhas[0]["grave"]
    sit = qf.situacao_schema(lake, AGORA + timedelta(hours=7))[0]
    assert sit["fonte"] == "gupy" and "name" in sit["grave_recente"] and sit["assinaturas_no_historico"] == 2
    assert qf.situacao_schema(lake, AGORA + timedelta(hours=31))[0]["grave_recente"] is None
    # a 3ª coleta, igual à 2ª, compara com ela: o formato novo vira a referência
    assert not qf.registrar_execucao(lake, "r3", AGORA + timedelta(hours=12), [("gupy", _gupy(name=None, title="x"), ESS)])[0]["mudou"]


def test_reconstrucao_pela_bronze_na_ordem_de_coleta_e_sem_a_execucao_atual(tmp_path):
    lake = Lake(tmp_path)
    for i, (regs, h) in enumerate(((_gupy(), 0), (_gupy(), 6), (_gupy(name=None, title="x"), 12))):
        em = AGORA + timedelta(hours=h)
        lake.write_bronze("gupy", em.date(), f"r{i}", {"run_id": f"r{i}", "source": "gupy", "ingested_at": em.isoformat(),
                                                       "records": regs})
    assert qf.reconstruir(lake, essenciais_por_fonte(), agora=AGORA + timedelta(days=1), excluir_run="r2") == 2
    assert qf.reconstruir(lake, essenciais_por_fonte(), agora=AGORA + timedelta(days=1)) == 3
    tab = lake.read(qf.TABELA).sort_values("em")
    assert list(tab["run_id"]) == ["r0", "r1", "r2"] and list(tab["grave"]) == [False, False, True]


def test_campos_essenciais_declarados_em_todos_os_coletores():
    ess = essenciais_por_fonte()
    assert set(ess) == {"gupy", "adzuna", "greenhouse", "lever", "ashby", "smartrecruiters"}
    assert all("id" in v for v in ess.values())


# ---------------------------------------------------------------- qualidade e nota por fonte
def _jobs(fonte, n, **kw):
    base = {"source": fonte, "familia": "engenharia_dados", "descricao": "x" * 1500, "empresa": "Acme",
            "publicada_em": AGORA, "uf": "SP", "cidade": "São Paulo", "pais_iso": "BR", "modalidade": "remoto",
            "primeira_observacao": AGORA - timedelta(days=1), "is_canonica": True}
    return [{**base, "job_id": f"{fonte}{i}", "canonical_job_id": f"{fonte}{i}", **kw} for i in range(n)]


def test_nota_por_fonte_com_indicadores_amostra_pequena_e_exclusivas(tmp_path):
    lake = Lake(tmp_path)
    jobs = _jobs("gupy", 40) + _jobs("adzuna", 40, familia="outra", descricao="trecho", modalidade="nao_informada")
    jobs[40]["canonical_job_id"], jobs[40]["is_canonica"] = "gupy0", False   # adzuna0 é a mesma vaga de gupy0
    jobs += _jobs("lever", 5)
    lake.write("silver/jobs", pd.DataFrame(jobs))
    lake.write("silver/job_skills", pd.DataFrame([{"job_id": f"gupy{i}", "skill_id": "sql", "tipo": "tecnica"} for i in range(40)]))
    lake.write("meta/source_runs", pd.DataFrame([
        {"run_id": "r1", "source": "gupy", "ok": True, "coletados": 40, "validos": 40, "finalizada_em": AGORA},
        {"run_id": "r1", "source": "adzuna", "ok": True, "coletados": 40, "validos": 40, "finalizada_em": AGORA},
        {"run_id": "r2", "source": "adzuna", "ok": False, "coletados": 0, "validos": 0, "finalizada_em": AGORA},
        {"run_id": "r1", "source": "lever", "ok": True, "coletados": 5, "validos": 5, "finalizada_em": AGORA}]))
    q = {x["fonte"]: x for x in qf.por_fonte(lake, AGORA + timedelta(hours=1))}
    g, a = q["gupy"], q["adzuna"]
    assert (g["nota"], g["relevancia_pct"], g["extracao_pct"], g["exclusivas_pct"]) == (100.0, 100.0, 100.0, 97.5)
    assert (a["disponibilidade_pct"], a["relevancia_pct"], a["descricao_completa_pct"], a["campos_pct"]) == (50.0, 0.0, 0.0, 75.0)
    assert a["nota"] == round((50 * .20 + 100 * .10 + 0 + 0 + 75 * .15 + 0) / 1.0, 1)
    assert q["lever"]["amostra_pequena"] and not g["amostra_pequena"]
    assert [x["fonte"] for x in qf.por_fonte(lake, AGORA + timedelta(hours=1))][-1] == "adzuna"


def test_saude_inclui_qualidade_formato_e_alerta_de_mudanca_grave(tmp_path):
    lake = Lake(tmp_path)
    qf.registrar_execucao(lake, "r1", AGORA, [("gupy", _gupy(), ESS)])
    qf.registrar_execucao(lake, "r2", AGORA + timedelta(hours=6), [("gupy", _gupy(description=None), ESS)])
    ind = saude.indicadores(lake, AGORA + timedelta(hours=7))
    assert ind["formato_fontes"][0]["fonte"] == "gupy" and "qualidade_fontes" in ind
    assert any(a.startswith("formato da fonte gupy mudou") and "description" in a for a in saude.alertas(ind))
    assert "Formato das respostas" in saude.markdown(ind, [])

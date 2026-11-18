"""Pipeline completo contra fontes simuladas: incremental, histórico, status, falhas."""
from datetime import timedelta

import pandas as pd
import pyarrow.parquet as pq

from jobradar import pipeline
from jobradar.storage import Lake
from jobradar.transformations.geografia import GEOGRAFIA_VERSAO

from ..conftest import AGORA, adzuna_jobs, gupy_jobs


def test_primeira_execucao_popula_todas_as_camadas(settings, fake):
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    assert rep.status == "sucesso"
    gupy = next(f for f in rep.fontes if f.source == "gupy")
    assert (gupy.coletados, gupy.validos, gupy.invalidos) == (5, 4, 1)
    assert rep.duplicatas_entre_fontes == 1  # Fintech Y na Gupy e na Adzuna
    jobs = lake.read("silver/jobs")
    assert len(jobs) == 7 and jobs["is_canonica"].sum() == 6
    dup = jobs[~jobs["is_canonica"]].iloc[0]
    assert dup["source"] == "adzuna"  # ATS direto é preferido ao agregador
    assert list(settings.lake.glob("bronze/source=*/dt=*/run=r1.json.gz"))
    assert not lake.read("gold/skill_monthly").empty
    assert len(lake.read("gold/job_scores")) == 6
    problemas = lake.read("silver/quality_issues")
    assert (problemas["problema"] == "invalido").sum() == 1


def test_segunda_execucao_e_incremental_e_preserva_primeira_observacao(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    depois = AGORA + timedelta(days=1)
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=depois)
    lake = Lake(settings.lake)
    jobs = lake.read("silver/jobs")
    assert rep.novas == 0 and len(jobs) == 7
    assert (pd.to_datetime(jobs["primeira_observacao"], utc=True) == AGORA).all()
    assert (pd.to_datetime(jobs["ultima_observacao"], utc=True) == depois).all()
    assert len(lake.read("silver/observations")) == 14  # uma observação por vaga por execução
    assert rep.meses_recalculados == []                  # nada mudou: gold não é recalculado


def test_mudanca_de_requisitos_e_registrada(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    fake.gupy[2]["description"] = "Requisitos: Python, SQL, dbt, Airflow e Snowflake."
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    obs = Lake(settings.lake).read("silver/observations")
    mudou = obs[obs["mudou_requisitos"]]
    assert rep.requisitos_alterados == 1
    assert "snowflake" in mudou.iloc[0]["skills_adicionadas"] and "aws" in mudou.iloc[0]["skills_removidas"]
    assert rep.meses_recalculados == ["2026-10"]


def test_vaga_que_some_fica_desconhecida_e_nao_encerrada(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    fake.gupy = [j for j in gupy_jobs() if j["id"] != 102]
    pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=20))
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert jobs.loc["102", "status"] == "desconhecida"
    assert jobs.loc["101", "status"] == "ativa"


def test_prazo_vencido_encerra_com_evidencia(settings, fake):
    fake.gupy[0]["applicationDeadline"] = "2026-10-01"
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert jobs.loc["101", "status"] == "encerrada"
    assert jobs.loc["101", "motivo_status"] == "prazo_de_inscricao_vencido"


def test_fonte_fora_do_ar_gera_execucao_parcial(settings, fake):
    fake.falhar = {"adzuna"}
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    adz = next(f for f in rep.fontes if f.source == "adzuna")
    # cada termo é tentado (2 retentativas por termo) até 3 termos seguidos com erro
    assert rep.status == "parcial" and not adz.ok and adz.retentativas == 2 * min(len(settings.termos), 3)
    assert set(Lake(settings.lake).read("silver/jobs")["source"]) == {"gupy", "greenhouse"}


def test_todas_as_fontes_fora_do_ar_nao_altera_o_historico(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    antes = Lake(settings.lake).read("silver/jobs")
    fake.falhar = {"gupy", "adzuna", "greenhouse"}
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    lake = Lake(settings.lake)
    assert rep.status == "falha"
    pd.testing.assert_frame_equal(antes, lake.read("silver/jobs"))
    assert lake.read("meta/runs")["status"].tolist() == ["sucesso", "falha"]


def test_historico_sobrevive_entre_processos(settings, fake):
    """Simula o GitHub Actions: cada execução é um processo novo lendo o mesmo lake."""
    from jobradar.settings import CONFIG_DIR, carregar
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    novo = carregar(lake=settings.lake, config_dir=CONFIG_DIR)
    novo.termos[:] = settings.termos
    fake.adzuna = adzuna_jobs() + [{"id": "a3", "title": "Engenheira de Dados Pleno", "company": {"display_name": "Nova"},
                                     "location": {"display_name": "São Paulo", "area": ["Brasil", "São Paulo"]},
                                     "redirect_url": "https://www.adzuna.com.br/land/ad/a3", "created": "2026-10-17T00:00:00Z",
                                     "description": "Spark e SQL"}]
    rep = pipeline.run(novo, fake.collectors(novo), run_id="r2", agora=AGORA + timedelta(days=1))
    assert rep.novas == 1


def test_retencao_da_bronze(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA - timedelta(days=100))
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA)
    assert rep.bronze_particoes_removidas == 3
    assert not list(settings.lake.glob("bronze/*/*/run=r1.json.gz"))


def _vaga_greenhouse(id_, titulo="Data Engineer"):
    return {"id": id_, "title": titulo, "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{id_}",
            "location": {"name": "Remote - Brazil"}, "updated_at": "2026-10-15T00:00:00Z",
            "company_name": "Acme", "content": "Python e SQL"}


def test_vaga_que_sai_do_quadro_do_ats_e_encerrada_e_volta_se_reaparecer(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    # O quadro da Acme continua no ar, com outra vaga (fora do filtro de dados), mas sem a 9001.
    fake.greenhouse = {"jobs": [_vaga_greenhouse(9002, "Executivo de Vendas")]}
    fake.gupy = [j for j in gupy_jobs() if j["id"] != 102]  # some de uma BUSCA: não encerra
    depois = AGORA + timedelta(hours=6, microseconds=478846)  # produção tem microssegundos
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=depois)
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert rep.encerradas_fora_do_quadro == 1
    assert jobs.loc["9001", "status"] == "encerrada"
    assert jobs.loc["9001", "motivo_status"] == "saiu_do_quadro_da_empresa"
    assert pd.Timestamp(jobs.loc["9001", "encerrada_em"]) == depois
    assert jobs.loc["9001", "quadro"] == "acme"
    assert jobs.loc["102", "status"] == "ativa"

    # Execução seguinte sem a vaga: não conta de novo nem muda a data de encerramento.
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r3", agora=depois + timedelta(hours=6))
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert rep.encerradas_fora_do_quadro == 0 and pd.Timestamp(jobs.loc["9001", "encerrada_em"]) == depois

    # A vaga voltou ao quadro: reabre.
    fake.greenhouse = {"jobs": [_vaga_greenhouse(9001), _vaga_greenhouse(9002, "Executivo de Vendas")]}
    pipeline.run(settings, fake.collectors(settings), run_id="r4", agora=depois + timedelta(hours=12))
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert jobs.loc["9001", "status"] == "ativa" and pd.isna(jobs.loc["9001", "encerrada_em"])


def test_quadro_fora_do_ar_ou_vazio_nao_encerra_vagas(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    fake.falhar = {"greenhouse"}
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(hours=6))
    assert rep.encerradas_fora_do_quadro == 0
    fake.falhar = set()
    fake.greenhouse = {"jobs": []}
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r3", agora=AGORA + timedelta(hours=12))
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert rep.encerradas_fora_do_quadro == 0 and jobs.loc["9001", "status"] == "ativa"


def test_vaga_gravada_antes_da_regra_sem_quadro_nao_e_encerrada(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    p = lake.path("silver/jobs")  # lake de antes da mudança: parquet sem as colunas novas
    pq.write_table(pq.read_table(p).drop(["quadro", "encerrada_em"]), p)
    fake.greenhouse = {"jobs": [_vaga_greenhouse(9002, "Executivo de Vendas")]}
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(hours=6))
    jobs = lake.read("silver/jobs").set_index("source_job_id")
    assert rep.encerradas_fora_do_quadro == 0 and jobs.loc["9001", "status"] == "ativa"


def _adzuna(id_, empresa=None, descricao="Requisitos: SQL, Python e Spark.", criado="2026-10-15T22:00:00Z"):
    return {"id": id_, "title": "Analista de Dados Sênior", "company": {"display_name": empresa} if empresa else {},
            "location": {"display_name": "São Paulo, Estado de São Paulo", "area": ["Brasil", "São Paulo"]},
            "redirect_url": f"https://www.adzuna.com.br/details/{id_}", "created": criado, "description": descricao}


def test_republicacao_no_agregador_sem_empresa_nao_conta_como_nova(settings, fake):
    fake.adzuna = adzuna_jobs() + [_adzuna("r1")]
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    # Dia seguinte: o mesmo anúncio volta com outro id e outra data; e um anúncio diferente de outra empresa.
    fake.adzuna = adzuna_jobs() + [_adzuna("r2", criado="2026-10-16T22:00:00Z"),
                                   _adzuna("x1", empresa="Outra", criado="2026-10-16T22:00:00Z")]
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(days=1))
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert not jobs.loc["r2", "is_canonica"] and jobs.loc["r2", "canonical_job_id"] == jobs.loc["r1", "job_id"]
    assert jobs.loc["r1", "is_canonica"] and jobs.loc["x1", "is_canonica"]
    adz = next(f for f in rep.fontes if f.source == "adzuna")
    assert rep.novas == 1 and adz.novas == 1                     # só a x1 é nova de verdade
    assert len(jobs) == 10                                        # nada é apagado


def test_mesmo_texto_em_empresas_diferentes_nao_e_republicacao(settings, fake):
    fake.adzuna = [_adzuna("e1", empresa="Consultoria A"), _adzuna("e2", empresa="Consultoria B")]
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert jobs.loc["e1", "is_canonica"] and jobs.loc["e2", "is_canonica"]


def test_vaga_que_vira_republicacao_recalcula_o_mes_dela_na_gold(settings, fake):
    """Histórico gravado antes da regra: a cópia era canônica e inflava o agregado do mês."""
    fake.adzuna = [_adzuna("r1"), _adzuna("r2", criado="2026-10-16T22:00:00Z")]
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    jobs = lake.read("silver/jobs")
    jobs["is_canonica"] = True                                   # como o lake estava antes desta regra
    lake.write("silver/jobs", jobs)
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(hours=6))
    assert rep.meses_recalculados == ["2026-10"]
    gold = lake.read("gold/skill_monthly")
    total = gold[(gold["skill_id"] == "__total__") & (gold["familia"] == "analise_dados")]["total_vagas"].sum()
    assert total == 1


def test_metricas_por_quadro_vao_para_meta_board_runs_e_bronze(settings, fake):
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    fake.falhar.add("greenhouse")
    pipeline.run(settings, fake.collectors(settings), run_id="r2", agora=AGORA + timedelta(hours=6))
    lake = Lake(settings.lake)
    br = lake.read("meta/board_runs").sort_values("finalizada_em")
    assert list(br["quadro"]) == ["acme", "acme"] and list(br["source"]) == ["greenhouse", "greenhouse"]
    r1, r2 = br.iloc[0], br.iloc[1]
    assert r1["ok"] and r1["completo"] and (r1["vagas_listadas"], r1["vagas_mantidas"]) == (1, 1)
    assert not r2["ok"] and "503" in r2["erro"] and r2["retentativas"] == 2
    bronze = next(settings.lake.glob("bronze/source=greenhouse/dt=*/run=r1.json.gz"))
    assert lake.read_bronze(bronze)["por_quadro"]["acme"]["vagas_listadas"] == 1


def _adzuna_em(id_, estado, descricao, titulo="Oracle DBA - Remote, Latin America"):
    return {**_adzuna(id_, empresa="Bluelight", descricao=descricao), "title": titulo,
            "location": {"display_name": f"{estado}, Brasil", "area": ["Brasil", estado]}}


def test_vaga_remota_repetida_por_estado_vira_uma_so(settings, fake):
    remoto, presencial = "Trabalho 100% remoto. Requisitos: Oracle.", "Trabalho presencial. Requisitos: Oracle."
    fake.adzuna = [_adzuna_em("rj", "Rio de Janeiro", remoto), _adzuna_em("pe", "Pernambuco", remoto),
                   _adzuna_em("p1", "Bahia", presencial, "Oracle DBA"), _adzuna_em("p2", "Paraná", presencial, "Oracle DBA")]
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert jobs.loc["rj", "uf"] != jobs.loc["pe", "uf"]
    assert jobs.loc["rj", "canonical_job_id"] == jobs.loc["pe", "canonical_job_id"]   # remota: UF não conta
    assert jobs.loc["p1", "is_canonica"] and jobs.loc["p2", "is_canonica"]           # presencial: UF conta
    assert next(f for f in rep.fontes if f.source == "adzuna").novas == 3   # 2 presenciais + 1 remota


# ---------------------------------------------------------------- geografia e deduplicação internacional
def _gh(id_, local, titulo="Data Engineer"):
    from ..conftest import iso
    return {"id": id_, "title": titulo, "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{id_}",
            "location": {"name": local}, "updated_at": iso(1), "company_name": "Acme",
            "content": "&lt;p&gt;Requirements: Python, SQL, Spark.&lt;/p&gt;"}


def test_mesma_vaga_em_cidades_ou_paises_diferentes_nao_vira_duplicata(settings, fake):
    fake.greenhouse = {"jobs": [_gh(1, "Lisbon, Portugal"), _gh(2, "Porto, Portugal"),
                                _gh(3, "Remote - Brazil"), _gh(4, "Remote - Portugal"),
                                _gh(5, "Madrid, Spain")]}
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    jobs = Lake(settings.lake).read("silver/jobs")
    gh = jobs[jobs["source"] == "greenhouse"].set_index("source_job_id")
    assert gh["is_canonica"].all()                                   # 5 vagas, 5 canônicas
    assert gh.loc["1", "pais_iso"] == "PT" and gh.loc["1", "cidade_norm"] == "lisboa"
    assert gh.loc["5", "pais_iso"] == "ES" and pd.isna(gh.loc["5", "uf"])   # ES não vira Espírito Santo
    assert gh.loc["3", "pais_iso"] == "BR" and (gh["geografia_versao"] == GEOGRAFIA_VERSAO).all()


def test_historico_antigo_ganha_geografia_sem_mudar_as_chaves_do_brasil(settings, fake):
    from jobradar.transformations.silver import RUIDO_TITULO
    from jobradar.transformations.text import normalizar, sha1
    fake.greenhouse = {"jobs": [_gh(1, "Lisbon, Portugal"), _gh(2, "Porto, Portugal")]}
    pipeline.run(settings, fake.collectors(settings), run_id="r1", agora=AGORA)
    lake = Lake(settings.lake)
    novo = lake.read("silver/jobs")
    # Simula o histórico gravado antes da geografia: sem as colunas novas e com a chave só pela UF.
    antigo = novo.copy()
    antigo[["pais_iso", "regiao", "cidade_norm", "geografia_versao"]] = None
    antigo["chave_alternativa"] = [
        sha1(normalizar(e), " ".join(RUIDO_TITULO.sub(" ", normalizar(t)).split()), u if isinstance(u, str) else "")
        if isinstance(e, str) else None for e, t, u in zip(antigo["empresa"], antigo["titulo"], antigo["uf"])]
    lake.write("silver/jobs", antigo)
    rep = pipeline.run(settings, [], run_id="r2", agora=AGORA + timedelta(hours=6))
    assert rep.status == "falha"                       # sem coletor nada é migrado: a silver não é tocada
    # Com coleta (só da Gupy, as vagas do Greenhouse ficam no histórico), a migração acontece.
    fake.falhar.update({"greenhouse", "adzuna"})
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r3", agora=AGORA + timedelta(hours=12))
    depois = lake.read("silver/jobs").set_index("job_id")
    assert rep.chaves_geografia_alteradas == 2         # só Lisboa e Porto mudam de chave
    ref = novo.set_index("job_id")
    assert (depois.loc[ref.index, "chave_alternativa"] == ref["chave_alternativa"]).all()
    assert depois.loc[depois["source"] == "greenhouse", "is_canonica"].all()
    rep = pipeline.run(settings, fake.collectors(settings), run_id="r4", agora=AGORA + timedelta(hours=18))
    assert rep.chaves_geografia_alteradas == 0         # idempotente


def test_ashby_entra_no_pipeline_e_encerra_vaga_que_sai_do_quadro(settings):
    import httpx

    from jobradar.collectors import AshbyCollector
    from ..conftest import iso
    vagas = [{"id": f"u{i}", "title": "Data Engineer" if i < 3 else "Sales", "location": "Lisbon, Portugal",
              "workplaceType": "OnSite", "isListed": True, "publishedAt": iso(1), "jobUrl": f"https://jobs.ashbyhq.com/acme/u{i}",
              "descriptionPlain": "Requirements: Python, SQL.", "address": {"postalAddress": {"addressCountry": "Portugal"}}}
             for i in range(1, 5)]

    def coletor(lista):
        c = AshbyCollector({"empresas": ["acme"], "nomes": {"acme": "Acme"}, "titulo_contem": ["data"]},
                           client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"jobs": lista}))))
        c.pause = 0
        return c
    pipeline.run(settings, [coletor(vagas)], run_id="r1", agora=AGORA)
    pipeline.run(settings, [coletor(vagas[1:])], run_id="r2", agora=AGORA + timedelta(hours=6))   # u1 saiu do quadro
    jobs = Lake(settings.lake).read("silver/jobs").set_index("source_job_id")
    assert list(jobs["source"].unique()) == ["ashby"] and set(jobs.index) == {"u1", "u2"}
    assert jobs.loc["u1", "status"] == "encerrada" and jobs.loc["u2", "status"] == "ativa"
    assert jobs.loc["u2", "pais_iso"] == "PT" and jobs.loc["u2", "empresa"] == "Acme"
    br = Lake(settings.lake).read("meta/board_runs")
    assert set(br["source"]) == {"ashby"} and br["completo"].all()

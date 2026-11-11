"""Pipeline completo contra fontes simuladas: incremental, histórico, status, falhas."""
from datetime import timedelta

import pandas as pd
import pyarrow.parquet as pq

from jobradar import pipeline
from jobradar.storage import Lake

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
    assert rep.status == "parcial" and not adz.ok and adz.retentativas == 2
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

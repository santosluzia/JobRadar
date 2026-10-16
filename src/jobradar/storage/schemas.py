"""Schemas físicos das tabelas do lake (Parquet). Documentados em docs/data-dictionary.md."""
from __future__ import annotations

import pyarrow as pa

TS = pa.timestamp("us", tz="UTC")
S = pa.string()

TABLES: dict[str, pa.Schema] = {
    # ---------------- silver ----------------
    "silver/jobs": pa.schema([
        ("job_id", S), ("source", S), ("source_job_id", S), ("url", S), ("url_canonica", S),
        ("titulo", S), ("titulo_norm", S), ("empresa", S), ("cidade", S), ("uf", S), ("pais", S),
        ("local_raw", S), ("modalidade", S), ("senioridade", S), ("familia", S),
        ("origem_campos", S), ("publicada_em", TS), ("prazo_em", TS),
        ("primeira_observacao", TS), ("ultima_observacao", TS), ("ultima_execucao", S),
        ("status", S), ("motivo_status", S), ("descricao", S), ("descricao_hash", S),
        ("chave_alternativa", S), ("canonical_job_id", S), ("is_canonica", pa.bool_()),
        ("atualizado_em", TS),
    ]),
    "silver/job_skills": pa.schema([
        ("job_id", S), ("skill_id", S), ("importancia", S), ("termo", S), ("run_id", S),
    ]),
    "silver/observations": pa.schema([
        ("job_id", S), ("run_id", S), ("observada_em", TS), ("descricao_hash", S), ("titulo", S),
        ("skills", S), ("mudou_requisitos", pa.bool_()), ("skills_adicionadas", S),
        ("skills_removidas", S),
    ]),
    "silver/quality_issues": pa.schema([
        ("run_id", S), ("source", S), ("source_job_id", S), ("campo", S), ("problema", S),
        ("detalhe", S), ("registrado_em", TS),
    ]),
    # ---------------- gold ----------------
    "gold/skill_monthly": pa.schema([
        ("mes", S), ("familia", S), ("senioridade", S), ("skill_id", S),
        ("vagas_com_skill", pa.int64()), ("vagas_requisito", pa.int64()), ("total_vagas", pa.int64()),
    ]),
    "gold/job_scores": pa.schema([
        ("job_id", S), ("score", pa.int64()), ("explicacao", S), ("lacunas", S),
        ("sem_evidencia", S), ("calculado_em", TS), ("perfil_hash", S),
    ]),
    # ---------------- meta ----------------
    "meta/runs": pa.schema([
        ("run_id", S), ("iniciada_em", TS), ("finalizada_em", TS), ("status", S),
        ("duracao_s", pa.float64()), ("metricas", S),
    ]),
    "meta/source_runs": pa.schema([
        ("run_id", S), ("source", S), ("ok", pa.bool_()), ("coletados", pa.int64()),
        ("validos", pa.int64()), ("invalidos", pa.int64()), ("duplicatas_fonte", pa.int64()),
        ("novas", pa.int64()), ("requisicoes", pa.int64()), ("retentativas", pa.int64()),
        ("erros", S), ("finalizada_em", TS),
    ]),
    "meta/notifications": pa.schema([
        ("job_id", S), ("canal", S), ("enviada_em", TS), ("run_id", S),
    ]),
    # ---------------- private (nunca publicado) ----------------
    "private/applications": pa.schema([
        ("job_id", S), ("status", S), ("atualizado_em", TS), ("observacoes", S),
    ]),
    "private/application_events": pa.schema([
        ("job_id", S), ("de", S), ("para", S), ("em", TS), ("nota", S),
    ]),
    "private/study_progress": pa.schema([
        ("skill_id", S), ("status", S), ("inicio", S), ("conclusao", S), ("evidencia", S),
        ("atualizado_em", TS),
    ]),
}

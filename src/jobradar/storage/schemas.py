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
        ("status", S), ("motivo_status", S), ("quadro", S), ("encerrada_em", TS), ("descricao", S), ("descricao_hash", S),
        ("chave_alternativa", S), ("canonical_job_id", S), ("is_canonica", pa.bool_()),
        ("atualizado_em", TS),
        # versão da taxonomia com que as competências da vaga foram extraídas (nulo = 1.0.0)
        ("taxonomia_versao", S),
        # Geografia (ADR 0010; nulo = gravada antes, recalculada na próxima execução): país ISO alfa-2,
        # região (UF no Brasil, estado/província nos demais), cidade normalizada e versão das regras
        ("pais_iso", S), ("regiao", S), ("cidade_norm", S), ("geografia_versao", S),
    ]),
    "silver/job_skills": pa.schema([
        ("job_id", S), ("skill_id", S), ("importancia", S), ("termo", S), ("run_id", S),
        # Etapa 1 (aditivo; nulo nas linhas antigas = extração por termo, taxonomia 1.0.0, técnica)
        ("metodo", S), ("evidencia", S), ("confianca", S), ("tipo", S), ("taxonomia_versao", S),
        # Etapa 2: JSON [[frase, início, fim], ...] de todas as menções (coocorrência sem "mesma menção")
        ("posicoes", S),
    ]),
    # Achados da camada de embeddings local, só para competências que as regras NÃO acharam.
    # Fica separada: só entra em gold/score/público com extracao.gold_hibrida = true.
    "silver/job_skills_semantica": pa.schema([
        ("job_id", S), ("skill_id", S), ("importancia", S), ("evidencia", S), ("similaridade", pa.float64()),
        ("confianca", S), ("tipo", S), ("modelo", S), ("modelo_revisao", S), ("limiar", pa.float64()),
        ("taxonomia_versao", S), ("descricao_hash", S), ("run_id", S), ("calculado_em", TS),
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
        # Etapa 2, só nas linhas "__total__": vagas do grupo com ao menos uma competência técnica
        # (base da coocorrência; vaga sem nenhuma competência extraída não informa nada sobre pares)
        ("vagas_com_competencia", pa.int64()),
    ]),
    "gold/job_scores": pa.schema([
        ("job_id", S), ("score", pa.int64()), ("explicacao", S), ("lacunas", S),
        ("sem_evidencia", S), ("calculado_em", TS), ("perfil_hash", S),
        # Etapa 3: uma linha por vaga e objetivo do perfil (nulo = linha antiga, de um objetivo só)
        ("objetivo_id", S),
    ]),
    # Coocorrência: vagas com o par (a < b) por coorte mensal e segmento. Contagens somáveis entre
    # meses; as marginais (vagas com a, com b e com ao menos uma competência) estão em skill_monthly.
    "gold/skill_pairs": pa.schema([
        ("mes", S), ("familia", S), ("senioridade", S), ("skill_a", S), ("skill_b", S),
        ("vagas_par", pa.int64()), ("vagas_par_requisito", pa.int64()),
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
    # Etapa 8: resultado das validações por execução. Público (contrato, taxonomia) e privado (perfil,
    # radar.yaml) em tabelas separadas: os dois workflows nunca gravam o mesmo arquivo (sem conflito de push).
    "meta/validacoes": pa.schema([
        ("run_id", S), ("artefato", S), ("versao", S), ("ok", pa.bool_()), ("erros", pa.int64()), ("detalhe", S),
        ("em", TS),
    ]),
    "private/validacoes": pa.schema([
        ("run_id", S), ("artefato", S), ("versao", S), ("ok", pa.bool_()), ("erros", pa.int64()), ("detalhe", S),
        ("em", TS),
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
    # Etapa 5: um registro por Radar diário (enviado ou com falha); controla duplicidade e repetição
    "private/radar_envios": pa.schema([
        ("data", S), ("objetivo_id", S), ("enviado_em", TS), ("run_id", S), ("status", S), ("assunto", S),
        ("vagas", pa.int64()), ("acao_tipo", S), ("acao_skill", S), ("acao_texto", S), ("chaves", S), ("erro", S),
    ]),
    # Etapa 6: um registro por Relatório Semanal (para comparar com a semana seguinte e acompanhar progresso)
    "private/relatorios_semanais": pa.schema([
        ("semana", S), ("objetivo_id", S), ("enviado_em", TS), ("run_id", S), ("status", S), ("assunto", S),
        ("oportunidades", S), ("resumo", S), ("erro", S),
    ]),
    # Etapa 7: retrato mensal por objetivo (só agregados e níveis) + status do e-mail do mês
    "private/diagnosticos_mensais": pa.schema([
        ("mes", S), ("objetivo_id", S), ("gerado_em", TS), ("run_id", S), ("status", S), ("retrato", S), ("erro", S),
    ]),
    # Etapa 4: histórico de mudanças de progresso (estado atual fica em study_progress)
    "private/study_events": pa.schema([
        ("skill_id", S), ("de", S), ("para", S), ("em", TS), ("evidencia", S), ("nota", S),
    ]),
}

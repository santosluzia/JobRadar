"""Camada semântica local (embeddings) — complementar às regras e DESLIGADA por padrão.

Decisão e medição: docs/adr/0001-extracao-de-competencias-sem-custo.md.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..storage import Lake
from ..transformations.skills import Taxonomy
from .extrator import AchadoSemantico, Codificador, ExtratorSemantico

__all__ = ["AchadoSemantico", "Codificador", "ExtratorSemantico", "enriquecer", "pendentes"]


def pendentes(jobs: pd.DataFrame, semantica: pd.DataFrame, tax: Taxonomy) -> pd.DataFrame:
    """Vagas canônicas com descrição que ainda não passaram pela camada com ESTA configuração
    (descrição, versão da taxonomia, modelo e limiar): só elas precisam de processamento."""
    cfg = tax.config.extracao.semantica
    base = jobs[jobs["is_canonica"].fillna(False) & jobs["descricao"].notna()]
    if semantica.empty:
        return base
    feito = semantica[(semantica["taxonomia_versao"] == tax.versao) & (semantica["modelo_revisao"] == cfg.revisao)
                      & (semantica["limiar"] == cfg.limiar)]
    chave = set(feito["job_id"] + "|" + feito["descricao_hash"].fillna(""))
    return base[~(base["job_id"] + "|" + base["descricao_hash"].fillna("")).isin(chave)]


def enriquecer(lake: Lake, tax: Taxonomy, alvo: pd.DataFrame, skills_regras: pd.DataFrame, run_id: str,
               agora: datetime, codificar: Codificador | None = None) -> int:
    """Roda a camada nas vagas de `alvo` e substitui as linhas delas em silver/job_skills_semantica.
    Uma vaga processada sem achado também fica registrada (linha com skill_id nulo), para não ser
    reprocessada à toa."""
    cfg = tax.config.extracao.semantica
    if codificar is None:
        from .modelo import carregar_codificador
        codificar = carregar_codificador(cfg)
    ext = ExtratorSemantico(tax, codificar, cfg.limiar, cfg.limiar_media, tuple(cfg.tipos))
    alvo = alvo[alvo["descricao"].notna()]
    por_job = skills_regras.groupby("job_id")["skill_id"].apply(set).to_dict() if not skills_regras.empty else {}
    comum = {"modelo": cfg.modelo, "modelo_revisao": cfg.revisao, "limiar": cfg.limiar,
             "taxonomia_versao": tax.versao, "run_id": run_id, "calculado_em": agora}
    linhas = []
    for j in alvo.itertuples():
        achados = ext.extrair(j.titulo, j.descricao, por_job.get(j.job_id, set()))
        base = {"job_id": j.job_id, "descricao_hash": j.descricao_hash, **comum}
        linhas += [{**base, "skill_id": a.skill_id, "importancia": a.importancia, "evidencia": a.evidencia,
                    "similaridade": a.similaridade, "confianca": a.confianca, "tipo": a.tipo} for a in achados] \
            or [{**base, "skill_id": None}]
    atual = lake.read("silver/job_skills_semantica")
    novo = pd.DataFrame(linhas, columns=atual.columns)
    partes = [p for p in (atual[~atual["job_id"].isin(alvo["job_id"])], novo) if not p.empty]
    lake.write("silver/job_skills_semantica", pd.concat(partes, ignore_index=True) if partes else atual)
    return len(alvo)

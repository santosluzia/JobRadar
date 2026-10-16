"""Candidaturas e progresso de estudos — dados PRIVADOS (lake/private/), nunca publicados.

O sistema não se candidata nem interage com plataformas: só registra o que você fez.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..models import APPLICATION_STATUSES
from ..storage import Lake, utcnow

STUDY_STATUSES = ["planejado", "em_andamento", "concluido", "pausado"]


def atualizar_candidatura(lake: Lake, job_id: str, status: str, nota: str | None = None,
                          agora: datetime | None = None) -> None:
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"status inválido: {status} (use {', '.join(APPLICATION_STATUSES)})")
    jobs = lake.read("silver/jobs")
    if job_id not in set(jobs["job_id"]):
        raise KeyError(f"vaga {job_id} não está no histórico")
    agora = agora or utcnow()
    apps = lake.read("private/applications")
    anterior = apps.loc[apps["job_id"] == job_id, "status"]
    de = anterior.iloc[0] if len(anterior) else "nova"
    obs = nota if nota is not None else (apps.loc[apps["job_id"] == job_id, "observacoes"].iloc[0] if len(anterior) else None)
    apps = pd.concat([apps[apps["job_id"] != job_id], pd.DataFrame([{
        "job_id": job_id, "status": status, "atualizado_em": agora, "observacoes": obs}])], ignore_index=True)
    lake.write("private/applications", apps)
    lake.append("private/application_events", pd.DataFrame([{
        "job_id": job_id, "de": de, "para": status, "em": agora, "nota": nota}]))


def atualizar_estudo(lake: Lake, skill_id: str, status: str, inicio: str | None = None,
                     conclusao: str | None = None, evidencia: str | None = None) -> None:
    if status not in STUDY_STATUSES:
        raise ValueError(f"status inválido: {status} (use {', '.join(STUDY_STATUSES)})")
    df = lake.read("private/study_progress")
    atual = df[df["skill_id"] == skill_id]
    base = atual.iloc[0].to_dict() if len(atual) else {}
    linha = {"skill_id": skill_id, "status": status,
             "inicio": inicio or base.get("inicio"), "conclusao": conclusao or base.get("conclusao"),
             "evidencia": evidencia or base.get("evidencia"), "atualizado_em": utcnow()}
    lake.write("private/study_progress", pd.concat([df[df["skill_id"] != skill_id], pd.DataFrame([linha])],
                                                   ignore_index=True))

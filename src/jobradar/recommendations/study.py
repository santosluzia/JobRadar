"""Prioridades de estudo explicáveis.

Regras de confiança (docs/architecture.md):
- tendência só é declarada com ≥ min_vagas_janela vagas nas DUAS janelas e variação ≥ min_variacao_pp;
- lacuna prioritária exige amostra mínima e frequência ≥ limiar na janela recente;
- sem amostra suficiente, a competência vai para "monitoramento", nunca para "prioridade".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..analytics.market import Snapshot
from ..scoring.profile import Profile
from ..transformations.skills import Taxonomy

CLASSES = ("consolidada", "em_desenvolvimento", "lacuna_prioritaria", "monitoramento")


@dataclass
class Recommendation:
    skill_id: str
    nome: str
    classe: str
    prioridade: float
    nivel_perfil: str
    percentual_recente: float
    percentual_requisito: float
    vagas_recente: int
    n_recente: int
    n_anterior: int
    variacao_pp: float | None
    tendencia: str             # alta | queda | estavel | inconclusiva
    esforco: str
    projeto_pratico: bool
    justificativa: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _grupo_alvo(snap: Snapshot, profile: Profile, filtros: dict[str, Any]) -> pd.DataFrame:
    c = snap.canonicas
    familias = profile.familias or filtros.get("familias") or []
    senior = (profile.senioridades or filtros.get("senioridades") or []) + ["nao_informada"]
    if familias:
        c = c[c["familia"].isin(familias)]
    return c[c["senioridade"].isin(senior)]


def _janela(c: pd.DataFrame, ini: datetime, fim: datetime) -> pd.DataFrame:
    p = pd.to_datetime(c["primeira_observacao"], utc=True)
    return c[(p >= ini) & (p < fim)]


def recomendar(snap: Snapshot, profile: Profile, tax: Taxonomy, cfg: dict[str, Any],
               filtros: dict[str, Any], agora: datetime) -> list[Recommendation]:
    alvo = _grupo_alvo(snap, profile, filtros)
    jd, jc = int(cfg["janela_dias"]), int(cfg["janela_comparacao_dias"])
    recente = _janela(alvo, agora - timedelta(days=jd), agora + timedelta(seconds=1))
    anterior = _janela(alvo, agora - timedelta(days=jd + jc), agora - timedelta(days=jd))
    n_r, n_a = len(recente), len(anterior)
    min_n, min_pp = int(cfg["min_vagas_janela"]), float(cfg["min_variacao_pp"])
    limiar = float(cfg["limiar_lacuna_prioritaria"])
    pesos, esf = cfg["pesos"], cfg["esforco_fator"]

    def stats(df: pd.DataFrame) -> tuple[dict[str, int], dict[str, int]]:
        sk = snap.skills[snap.skills["job_id"].isin(df["job_id"])]
        return (sk.groupby("skill_id")["job_id"].nunique().to_dict(),
                sk[sk["importancia"] == "requisito"].groupby("skill_id")["job_id"].nunique().to_dict())

    cont_r, req_r = stats(recente)
    cont_a, _ = stats(anterior)
    saida: list[Recommendation] = []
    for skill in tax.skills:
        vagas = cont_r.get(skill.id, 0)
        nivel = profile.nivel(skill.id)
        if vagas == 0 and nivel == "sem_evidencia":
            continue
        pct = 100 * vagas / n_r if n_r else 0.0
        pct_req = 100 * req_r.get(skill.id, 0) / n_r if n_r else 0.0
        variacao, tendencia = None, "inconclusiva"
        if n_r >= min_n and n_a >= min_n:
            variacao = round(pct - 100 * cont_a.get(skill.id, 0) / n_a, 1)
            tendencia = "alta" if variacao >= min_pp else "queda" if variacao <= -min_pp else "estavel"

        lacuna = nivel in ("nao_dominada", "sem_evidencia")
        if nivel in ("profissional", "projeto"):
            classe = "consolidada"
        elif nivel == "em_desenvolvimento":
            classe = "em_desenvolvimento"
        elif lacuna and n_r >= min_n and pct / 100 >= limiar:
            classe = "lacuna_prioritaria"
        else:
            classe = "monitoramento"

        prioridade = 0.0
        if classe in ("lacuna_prioritaria", "em_desenvolvimento", "monitoramento"):
            prioridade = (pesos["demanda"] * pct / 100 + pesos["requisito"] * pct_req / 100
                          + pesos["tendencia"] * (max(variacao or 0, 0) / 100)
                          + pesos["projeto"] * (1.0 if skill.projeto else 0.0)
                          + pesos["esforco"] * float(esf.get(skill.esforco, 0.5)))
        saida.append(Recommendation(
            skill_id=skill.id, nome=skill.nome, classe=classe, prioridade=round(prioridade, 3),
            nivel_perfil=nivel, percentual_recente=round(pct, 1), percentual_requisito=round(pct_req, 1),
            vagas_recente=vagas, n_recente=n_r, n_anterior=n_a, variacao_pp=variacao, tendencia=tendencia,
            esforco=skill.esforco, projeto_pratico=skill.projeto,
            justificativa=_justificar(classe, skill.nome, nivel, vagas, n_r, pct, pct_req, tendencia,
                                      variacao, min_n, limiar, skill.esforco),
        ))
    ordem = {c: i for i, c in enumerate(["lacuna_prioritaria", "em_desenvolvimento", "monitoramento", "consolidada"])}
    return sorted(saida, key=lambda r: (ordem[r.classe], -r.prioridade, -r.percentual_recente))


def _justificar(classe, nome, nivel, vagas, n, pct, pct_req, tendencia, variacao, min_n, limiar, esforco) -> str:
    base = f"{nome} aparece em {vagas} de {n} vagas-alvo recentes ({pct:.0f}%; requisito em {pct_req:.0f}%)."
    if n < min_n:
        base += f" Amostra abaixo do mínimo de {min_n} vagas: sem conclusão de prioridade."
    if tendencia in ("alta", "queda"):
        base += f" Tendência de {tendencia} ({variacao:+.1f} p.p. contra o período anterior)."
    elif tendencia == "inconclusiva" and n >= min_n:
        base += " Período anterior sem amostra suficiente para avaliar tendência."
    perfil = {"profissional": "você já tem evidência profissional",
              "projeto": "você tem evidência em projeto",
              "em_desenvolvimento": "está em desenvolvimento no seu perfil",
              "nao_dominada": "marcada como não dominada no perfil",
              "sem_evidencia": "sem evidência registrada no perfil (não significa que você não saiba)"}[nivel]
    if classe == "lacuna_prioritaria":
        return f"{base} {perfil.capitalize()}; frequência acima de {limiar:.0%}. Esforço estimado: {esforco}."
    return f"{base} {perfil.capitalize()}."

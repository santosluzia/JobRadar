"""Controle de progresso por competência (Etapa 4) e perfil EFETIVO = perfil declarado + progresso.

Status (4.4): nao_iniciada · em_estudo · em_pratica · demonstrada_em_projeto ·
comprovada_profissional (+ `pausada`, auxiliar). Os status antigos (planejado, em_andamento,
concluido, pausado) continuam aceitos e são convertidos.

Como o progresso entra no perfil efetivo — só SOBE o nível declarado, nunca rebaixa:
- em_estudo, em_pratica, pausada       → em_desenvolvimento
- demonstrada_em_projeto + evidência   → projeto
- comprovada_profissional + evidência  → profissional (declaração SUA; o sistema nunca infere)
- sem evidência informada, os dois últimos valem só como em_desenvolvimento.
Curso concluído NÃO vira experiência profissional: "concluido" (antigo) vira em_estudo com data de conclusão.

O perfil efetivo entra no hash do perfil: mudar o progresso recalcula scores e diagnóstico.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import pandas as pd

from ..scoring import Profile
from ..storage import Lake, utcnow

STATUS = ["nao_iniciada", "em_estudo", "em_pratica", "demonstrada_em_projeto", "comprovada_profissional", "pausada"]
LEGADO = {"planejado": "nao_iniciada", "em_andamento": "em_estudo", "concluido": "em_estudo", "pausado": "pausada"}
ACEITOS = STATUS + list(LEGADO)
_ORDEM = {"sem_evidencia": -1, "nao_dominada": 0, "em_desenvolvimento": 1, "projeto": 2, "profissional": 3}


def normalizar_status(status: str) -> str:
    if status not in ACEITOS:
        raise ValueError(f"status inválido: {status} (use {', '.join(STATUS)})")
    return LEGADO.get(status, status)


def nivel_do_progresso(status: str | None, evidencia: str | None) -> str | None:
    """Nível de perfil que o progresso justifica (None = não altera o perfil)."""
    if not status:
        return None
    status = LEGADO.get(status, status)
    tem_evidencia = bool(evidencia and str(evidencia).strip())
    if status == "comprovada_profissional" and tem_evidencia:
        return "profissional"
    if status == "demonstrada_em_projeto" and tem_evidencia:
        return "projeto"
    if status in ("em_estudo", "em_pratica", "pausada", "demonstrada_em_projeto", "comprovada_profissional"):
        return "em_desenvolvimento"
    return None


def efeito_no_perfil(nivel_progresso: str | None, nivel_declarado: str | None) -> str | None:
    """Frase curta sobre o efeito do progresso no perfil efetivo. O progresso só SOBE nível: se o perfil
    já declara um nível igual ou maior, ele continua valendo."""
    if not nivel_progresso:
        return None
    if nivel_declarado and _ORDEM.get(nivel_declarado, -1) >= _ORDEM.get(nivel_progresso, -1):
        return f"o perfil já declara {nivel_declarado}, que continua valendo: o progresso só sobe nível"
    return f"conta no perfil como {nivel_progresso}"


def atualizar(lake: Lake, skill_id: str, status: str, evidencia: str | None = None, inicio: str | None = None,
              conclusao: str | None = None, nota: str | None = None, agora: datetime | None = None) -> dict[str, Any]:
    """Grava o estado atual (private/study_progress) e o evento (private/study_events)."""
    status = normalizar_status(status)
    agora = agora or utcnow()
    df = lake.read("private/study_progress")
    atual = df[df["skill_id"] == skill_id]
    base = atual.iloc[0].to_dict() if len(atual) else {}
    linha = {"skill_id": skill_id, "status": status,
             "inicio": inicio or base.get("inicio") or (agora.date().isoformat() if status != "nao_iniciada" else None),
             "conclusao": conclusao or base.get("conclusao"),
             "evidencia": evidencia or base.get("evidencia"), "atualizado_em": agora}
    lake.write("private/study_progress", pd.concat([df[df["skill_id"] != skill_id], pd.DataFrame([linha])],
                                                   ignore_index=True))
    lake.append("private/study_events", pd.DataFrame([{
        "skill_id": skill_id, "de": LEGADO.get(base.get("status"), base.get("status")) if base else None,
        "para": status, "em": agora, "evidencia": evidencia, "nota": nota}]))
    aviso = None
    if status in ("demonstrada_em_projeto", "comprovada_profissional") and not linha["evidencia"]:
        aviso = "sem evidência informada: conta como em desenvolvimento até você registrar onde demonstrou"
    return {**linha, "nivel_no_perfil": nivel_do_progresso(status, linha["evidencia"]), "aviso": aviso}


def perfil_efetivo_dict(perfil: dict[str, Any], progresso: pd.DataFrame) -> dict[str, Any]:
    """profile.yaml + progresso. Sem progresso, devolve o MESMO dicionário (hash não muda)."""
    if progresso.empty or not perfil:
        return perfil
    d = copy.deepcopy(perfil)
    comps = {c["skill"]: c for c in d.setdefault("competencias", [])}
    for r in progresso.itertuples():
        nivel = nivel_do_progresso(r.status, r.evidencia)
        if not nivel:
            continue
        c = comps.get(r.skill_id)
        if c is None:
            c = {"skill": r.skill_id, "nivel": nivel, "evidencias": []}
            d["competencias"].append(c)
            comps[r.skill_id] = c
        elif _ORDEM[nivel] > _ORDEM[c["nivel"]]:
            c["nivel"] = nivel
        else:
            continue
        if r.evidencia and str(r.evidencia) not in c.setdefault("evidencias", []):
            c["evidencias"] = [*c.get("evidencias", []), f"progresso: {r.evidencia}"]
    return d


def perfil_efetivo(perfil: dict[str, Any], lake: Lake) -> Profile:
    return Profile.from_dict(perfil_efetivo_dict(perfil, lake.read("private/study_progress")))

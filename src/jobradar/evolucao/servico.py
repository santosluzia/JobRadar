"""Operações do plano de evolução usadas pela CLI e pelo painel. Histórico só local ($JOBRADAR_HOME)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..privado import pasta_privada
from ..settings import Settings


def planos(s: Settings, objetivo_id: str | None = None, home: Path | None = None, salvar: bool = False,
           agora: datetime | None = None) -> list[dict[str, Any]]:
    from ..analytics import market
    from ..curriculo import versoes
    from ..storage import Lake
    from ..transformations.skills import Taxonomy
    from .plano import montar
    from .progresso import perfil_efetivo

    tax = Taxonomy(s.skills)
    lake = Lake(s.lake)
    snap = market.carregar(lake, tax.config.extracao.gold_hibrida)
    scores = lake.read("gold/job_scores")
    perfil = perfil_efetivo(s.profile, lake)
    progresso = lake.read("private/study_progress")
    cv = versoes.carregar(home=home)
    agora = agora or datetime.now(timezone.utc)
    saida = []
    for p in ([perfil.para(objetivo_id)] if objetivo_id else perfil.por_objetivo()):
        plano = montar(snap, scores, p, cv, tax, s.scoring, s.filtros, s.evolucao, progresso, agora)
        if salvar:
            salvar_plano(plano, home)
        saida.append(plano)
    return saida


def salvar_plano(plano: dict[str, Any], home: Path | None = None) -> Path:
    raiz = pasta_privada("evolucao", home)
    nome = re.sub(r"[^\w.-]", "_", f"{plano['gerado_em'][:19].replace(':', '').replace('-', '')}_{plano['objetivo_id']}.json")
    destino = raiz / nome
    destino.write_text(json.dumps(plano, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return destino


def historico(objetivo_id: str | None = None, home: Path | None = None) -> list[dict[str, Any]]:
    """Resumo dos planos salvos: quando, aderência e quais competências eram prioritárias."""
    saida = []
    for arq in sorted(pasta_privada("evolucao", home).glob("*.json")):
        p = json.loads(arq.read_text(encoding="utf-8"))
        if objetivo_id and p["objetivo_id"] != objetivo_id:
            continue
        saida.append({"gerado_em": p["gerado_em"], "objetivo_id": p["objetivo_id"], "objetivo": p["objetivo"],
                      "aderencia_perfil": p["aderencia"]["perfil"]["valor"],
                      "aderencia_curriculo": (p["aderencia"]["curriculo"] or {}).get("valor"),
                      "prioritarias": [i["skill_id"] for i in p["prioritarias"]],
                      "por_classe": {k: len(v) for k, v in p["classes"].items()}})
    return saida

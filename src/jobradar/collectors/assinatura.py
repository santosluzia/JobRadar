"""Assinatura do formato das respostas de cada fonte e detecção de mudança (ADR 0013).

A assinatura de uma coleta é o conjunto de caminhos de campo que vieram nos registros brutos, com o tipo
e a presença (% de registros com valor não nulo). Só NOMES de campo e tipos, nunca valores: é dado
operacional e pode ir para o resumo público do Actions.

- `caminhos` achata um registro: `location.name`, `location.area[]`, `departments[].name`. Valores nulos
  não contam; listas contam como `lista` e os elementos (até 5) são achatados também.
- O `hash` usa os caminhos presentes em ao menos `PRESENCA_FORTE_PCT`% dos registros: campo opcional raro
  não muda a assinatura a cada execução.
- `comparar` aponta campos novos, removidos e com tipo trocado, com faixa de tolerância: novo = estava
  ausente (< `AUSENTE_PCT`%) e passou a ter ≥ `PRESENCA_FORTE_PCT`%; removido = o contrário. Campo opcional
  que oscila (salário na Adzuna, ~9% das vagas) não vira mudança. A mudança é **grave** quando atinge um
  campo ESSENCIAL (o que o coletor usa, `CAMPOS_ESSENCIAIS` de cada coletor): sumiu, caiu
  `QUEDA_GRAVE_PP` pontos de presença ou trocou de tipo. É o aviso antecipado de "formato mudou" antes de
  a silver ficar com campos vazios — o caso da Gupy, que não tem API documentada.
- Amostra com menos de `MIN_REGISTROS` registros não é comparada (instável).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterator

# Anotações que os próprios coletores acrescentam ao registro (não vêm da fonte).
INTERNOS = {"_board", "_empresa", "_empresa_nome", "_empresa_fixa"}
PRESENCA_FORTE_PCT = 25.0
AUSENTE_PCT = 5.0
QUEDA_GRAVE_PP = 30.0
MIN_REGISTROS = 5
_ELEMENTOS = 5
_TIPOS = {bool: "bool", int: "numero", float: "numero", str: "texto"}


def caminhos(registro: Any, prefixo: str = "") -> Iterator[tuple[str, str]]:
    """(caminho, tipo) de cada valor não nulo do registro."""
    if isinstance(registro, dict):
        for k, v in registro.items():
            if not prefixo and k in INTERNOS:
                continue
            yield from caminhos(v, f"{prefixo}.{k}" if prefixo else str(k))
    elif isinstance(registro, list):
        if prefixo:
            yield f"{prefixo}[]", "lista"
        for x in registro[:_ELEMENTOS]:
            if isinstance(x, (dict, list)):
                yield from caminhos(x, f"{prefixo}[]")
    elif registro is not None and prefixo:
        yield prefixo, _TIPOS.get(type(registro), type(registro).__name__)


@dataclass
class Assinatura:
    source: str
    registros: int
    campos: dict[str, dict[str, Any]] = field(default_factory=dict)   # caminho → {tipos, presenca_pct}
    essenciais: dict[str, float] = field(default_factory=dict)        # caminho essencial → presença %
    hash: str | None = None


def assinar(source: str, registros: list[dict[str, Any]], essenciais: tuple[str, ...] = ()) -> Assinatura:
    n = len(registros)
    presenca: Counter[str] = Counter()
    tipos: dict[str, set[str]] = defaultdict(set)
    for r in registros:
        vistos = set()
        for caminho, tipo in caminhos(r):
            tipos[caminho].add(tipo)
            vistos.add(caminho)
        presenca.update(vistos)
    campos = {c: {"tipos": sorted(tipos[c]), "presenca_pct": round(100 * presenca[c] / n, 1)}
              for c in sorted(presenca)} if n else {}
    estaveis = [(c, v["tipos"]) for c, v in campos.items() if v["presenca_pct"] >= PRESENCA_FORTE_PCT]
    h = hashlib.sha1(json.dumps(estaveis, ensure_ascii=False).encode()).hexdigest()[:12] if n else None
    return Assinatura(source, n, campos, {e: campos.get(e, {}).get("presenca_pct", 0.0) for e in essenciais}, h)


def comparar(atual: Assinatura, anterior: Assinatura | None) -> dict[str, Any]:
    """Diferenças entre duas assinaturas da mesma fonte. `grave` = um campo essencial sumiu, caiu
    `QUEDA_GRAVE_PP` pontos de presença ou trocou de tipo."""
    vazio = {"comparada": False, "mudou": False, "grave": False, "novos": [], "removidos": [], "tipos_alterados": [],
             "essenciais_em_queda": []}
    if anterior is None or atual.registros < MIN_REGISTROS or anterior.registros < MIN_REGISTROS:
        return vazio

    p_at = {c: v["presenca_pct"] for c, v in atual.campos.items()}
    p_an = {c: v["presenca_pct"] for c, v in anterior.campos.items()}
    novos = sorted(c for c, p in p_at.items() if p >= PRESENCA_FORTE_PCT and p_an.get(c, 0.0) < AUSENTE_PCT)
    removidos = sorted(c for c, p in p_an.items() if p >= PRESENCA_FORTE_PCT and p_at.get(c, 0.0) < AUSENTE_PCT)
    tipos = sorted(c for c in set(p_at) & set(p_an)
                   if min(p_at[c], p_an[c]) >= PRESENCA_FORTE_PCT
                   and atual.campos[c]["tipos"] != anterior.campos[c]["tipos"])
    queda = sorted(c for c, p in atual.essenciais.items()
                   if anterior.essenciais.get(c) is not None and anterior.essenciais[c] - p >= QUEDA_GRAVE_PP)
    essenciais = set(atual.essenciais) | set(anterior.essenciais)
    grave = bool(queda) or any(c in essenciais for c in tipos)
    return {"comparada": True, "mudou": bool(novos or removidos or tipos or queda), "grave": grave,
            "novos": novos, "removidos": removidos, "tipos_alterados": tipos, "essenciais_em_queda": queda}


def resumo(mudancas: dict[str, Any], limite: int = 6) -> str:
    """Texto curto para alerta e terminal."""
    partes = []
    for chave, rotulo in (("essenciais_em_queda", "essenciais em queda"), ("tipos_alterados", "tipo trocado"),
                          ("removidos", "removidos"), ("novos", "novos")):
        itens = mudancas.get(chave) or []
        if itens:
            mais = f" (+{len(itens) - limite})" if len(itens) > limite else ""
            partes.append(f"{rotulo}: {', '.join(itens[:limite])}{mais}")
    return "; ".join(partes) or "sem diferença"

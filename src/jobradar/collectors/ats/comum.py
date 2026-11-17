"""Peças comuns aos coletores de ATS que listam o quadro INTEIRO de uma empresa (Greenhouse, Lever,
Ashby e SmartRecruiters).

Como a resposta é o quadro inteiro, a ausência de uma vaga é evidência de que ela saiu do ar (diferente
da Gupy e da Adzuna, que são buscas). Cada quadro lido por completo vai para `CollectResult.quadros` com
os ids de todas as vagas, antes do filtro de título. Não entram: quadro com erro, quadro vazio (suspeito:
a empresa não fica sem nenhuma vaga de um dia para o outro) e quadro cujo total informado pela API não
bate com a lista devolvida.

Se `titulo_contem` estiver configurado, só ficam as vagas cujo título contém uma dessas palavras (sem
acento, palavra inteira); o resto é descartado antes da bronze para não inflar o histórico nem diluir as
análises de mercado. O filtro fino de relevância continua na silver.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any, Iterator

from ...transformations.text import normalizar
from ..base import CollectResult, SourceError


def filtro_titulo(cfg: dict[str, Any]):
    palavras = [normalizar(p) for p in cfg.get("titulo_contem") or [] if p]
    if not palavras:
        return lambda titulo: True
    padrao = re.compile(r"\b(" + "|".join(re.escape(p) for p in palavras) + r")\b")
    return lambda titulo: bool(padrao.search(normalizar(titulo)))


def registrar_quadro(result: CollectResult, quadro: str, vagas: list[dict[str, Any]],
                     total_informado: int | None = None) -> None:
    completo = bool(vagas) and (total_informado is None or total_informado == len(vagas))
    if quadro in result.por_quadro:
        result.por_quadro[quadro].update(vagas_listadas=len(vagas), completo=completo)
    if not completo:
        result.params.setdefault("quadros_incompletos", []).append(quadro)
        return
    result.quadros[quadro] = sorted({str(v.get("id")) for v in vagas if v.get("id") is not None})


def aplicar_filtro(cfg: dict[str, Any], todos: list[dict[str, Any]], campo: str, result: CollectResult,
                   chave_quadro: str) -> list[dict[str, Any]]:
    aceita = filtro_titulo(cfg)
    mantidos = [r for r in todos if aceita(r.get(campo))]
    result.params["fora_do_filtro_titulo"] = len(todos) - len(mantidos)
    for r in mantidos:
        m = result.por_quadro.get(r.get(chave_quadro))
        if m is not None:
            m["vagas_mantidas"] += 1
    return mantidos


@contextmanager
def medindo(result: CollectResult, quadro: str) -> Iterator[dict[str, Any]]:
    """Mede um quadro: requisições, retentativas, duração e erro. Erro da fonte (SourceError) ou JSON
    inválido (ValueError) fica registrado no quadro e em `result.errors`, sem derrubar os demais quadros."""
    m: dict[str, Any] = {"ok": False, "completo": False, "vagas_listadas": 0, "vagas_mantidas": 0,
                         "requisicoes": 0, "retentativas": 0, "duracao_s": 0.0, "erro": None}
    result.por_quadro[quadro] = m
    req0, ret0, t0 = result.requests, result.retries, time.monotonic()
    try:
        yield m
        m["ok"] = True
    except (SourceError, ValueError) as e:
        m["erro"] = str(e)
        result.errors.append(f"{quadro}: {e}")
    finally:
        m.update(requisicoes=result.requests - req0, retentativas=result.retries - ret0,
                 duracao_s=round(time.monotonic() - t0, 2))

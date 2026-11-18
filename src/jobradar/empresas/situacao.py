"""Situação da coleta por empresa: o catálogo curado cruzado com `meta/board_runs` (medido a cada execução).

Só dados públicos e operacionais (empresa, quadro, contagens, datas): pode ir para o terminal e para o
resumo do Actions.
"""
from __future__ import annotations

import pandas as pd

from ..storage import Lake
from .catalogo import Catalogo, _chave

COLUNAS = ["id", "nome", "pais", "segmento", "ats", "board", "status", "verificada_em", "ultima_coleta_ok",
           "ultima_tentativa", "ultima_ok", "falhas_seguidas", "vagas_listadas", "vagas_mantidas",
           "ultima_verificacao", "vagas_dados_verificacao"]


def situacao(catalogo: Catalogo, lake: Lake) -> pd.DataFrame:
    runs = lake.read("meta/board_runs")
    verifs = lake.read("meta/empresas_verificacoes")   # curadoria (ADR 0012)
    linhas = []
    for e in catalogo.empresas:
        ver = verifs[(verifs["ats"] == e.ats) & (verifs["board"].astype(str).str.lower() == (e.board or "").lower())] \
            if e.board and not verifs.empty else verifs.iloc[0:0]
        ult_ver = ver.sort_values("em").iloc[-1] if not ver.empty else None
        r = runs[(runs["source"] == e.ats) & (runs["quadro"].map(lambda q: _chave(str(q))) == _chave(e.board or ""))] \
            if e.board and not runs.empty else runs.iloc[0:0]
        r = r.sort_values("finalizada_em")
        ok = r[r["ok"].fillna(False).astype(bool)]
        ult = r.iloc[-1] if not r.empty else None
        ult_ok = ok.iloc[-1] if not ok.empty else None
        falhas = 0
        for v in reversed(r["ok"].fillna(False).astype(bool).tolist()):
            if v:
                break
            falhas += 1
        linhas.append({
            "id": e.id, "nome": e.nome, "pais": e.pais, "segmento": e.segmento, "ats": e.ats, "board": e.board,
            "status": e.status, "verificada_em": e.verificada_em,
            "ultima_coleta_ok": ult_ok["finalizada_em"] if ult_ok is not None else None,
            "ultima_tentativa": ult["finalizada_em"] if ult is not None else None,
            "ultima_ok": bool(ult["ok"]) if ult is not None else None,
            "falhas_seguidas": falhas,
            "vagas_listadas": int(ult_ok["vagas_listadas"]) if ult_ok is not None else None,
            "vagas_mantidas": int(ult_ok["vagas_mantidas"]) if ult_ok is not None else None,
            "ultima_verificacao": ult_ver["em"] if ult_ver is not None else None,
            "vagas_dados_verificacao": int(ult_ver["vagas_dados"]) if ult_ver is not None and ult_ver["ok"] else None,
        })
    return pd.DataFrame(linhas, columns=COLUNAS)

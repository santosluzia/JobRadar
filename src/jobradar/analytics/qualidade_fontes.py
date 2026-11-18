"""Qualidade por fonte (ADR 0013): o quanto cada fonte entrega de vaga útil, e se o formato dela mudou.

Só tabelas operacionais e de mercado (meta/*, silver/jobs, silver/job_skills): nada pessoal. A saída pode
ir para o resumo público do Actions.

Indicadores por fonte, na janela (padrão 30 dias; vagas vistas pela 1ª vez na janela):
- disponibilidade: % das execuções em que a fonte respondeu sem erro;
- válidos: % dos registros coletados que viraram vaga válida;
- relevância: % das vagas com família de dados (≠ `outra`);
- descrição completa: % com descrição de ao menos `DESCRICAO_COMPLETA_MIN` caracteres (a Adzuna entrega
  só um trecho);
- campos: média de empresa, data de publicação, local e modalidade informados;
- extração: % com ao menos uma competência técnica;
- exclusivas: % das vagas que só essa fonte trouxe (o grupo de deduplicação não tem outra fonte).
  Mede a contribuição, não entra na nota.

Nota 0–100 = média ponderada dos indicadores disponíveis (`PESOS`). `amostra_pequena` quando há menos de
`AMOSTRA_MIN` vagas na janela: a nota existe, mas não é comparável.

Assinaturas de formato (collectors/assinatura.py) ficam em `meta/schema_assinaturas`: `registrar_execucao`
roda no pipeline; `reconstruir` refaz o histórico a partir da bronze (90 dias).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from ..collectors.assinatura import MIN_REGISTROS, Assinatura, assinar, comparar, resumo
from ..storage import Lake, utcnow

TABELA = "meta/schema_assinaturas"
DESCRICAO_COMPLETA_MIN = 1000
AMOSTRA_MIN = 30
PESOS = {"disponibilidade_pct": 0.20, "validos_pct": 0.10, "relevancia_pct": 0.25, "descricao_completa_pct": 0.15,
         "campos_pct": 0.15, "extracao_pct": 0.15}


# ---------------------------------------------------------------- assinaturas de formato
def _assinatura_da_linha(linha: pd.Series) -> Assinatura:
    def js(v):
        return json.loads(v) if isinstance(v, str) and v else {}
    return Assinatura(linha["source"], int(linha["registros"] or 0), js(linha["campos"]), js(linha["essenciais"]),
                      linha["hash"])


def _anterior(tab: pd.DataFrame, source: str) -> Assinatura | None:
    """Última assinatura comparável (com ao menos MIN_REGISTROS registros) da fonte."""
    da_fonte = tab[(tab["source"] == source) & (tab["registros"].fillna(0) >= MIN_REGISTROS)]
    if da_fonte.empty:
        return None
    em = pd.to_datetime(da_fonte["em"], utc=True)
    return _assinatura_da_linha(da_fonte.loc[em.sort_values(kind="stable").index[-1]])


def _linha(run_id: str, em: datetime, atual: Assinatura, anterior: Assinatura | None) -> dict[str, Any]:
    dif = comparar(atual, anterior)
    em = pd.Timestamp(em)
    em = em.tz_localize("UTC") if em.tzinfo is None else em.tz_convert("UTC")
    return {"run_id": run_id, "source": atual.source, "em": em, "registros": atual.registros, "hash": atual.hash,
            "campos": json.dumps(atual.campos, ensure_ascii=False),
            "essenciais": json.dumps(atual.essenciais, ensure_ascii=False), "comparada": dif["comparada"],
            "mudou": dif["mudou"], "grave": dif["grave"],
            "mudancas": json.dumps({k: dif[k] for k in ("novos", "removidos", "tipos_alterados", "essenciais_em_queda")},
                                   ensure_ascii=False) if dif["mudou"] else None}


def registrar_execucao(lake: Lake, run_id: str, em: datetime,
                       coletas: list[tuple[str, list[dict[str, Any]], tuple[str, ...]]]) -> list[dict[str, Any]]:
    """Assina cada (fonte, registros, essenciais) da execução e grava em `meta/schema_assinaturas`.
    Fonte sem registro (falhou ou veio vazia) não ganha linha: não há formato para medir."""
    tab = lake.read(TABELA)
    linhas = []
    for source, registros, essenciais in coletas:
        if not registros:
            continue
        linha = _linha(run_id, em, assinar(source, registros, essenciais), _anterior(tab, source))
        linhas.append(linha)
        tab = pd.concat([tab, pd.DataFrame([linha])], ignore_index=True) if not tab.empty else pd.DataFrame([linha])
    lake.append(TABELA, pd.DataFrame(linhas))
    return linhas


def reconstruir(lake: Lake, essenciais_por_fonte: dict[str, tuple[str, ...]], dias: int | None = None,
                agora: datetime | None = None, excluir_run: str | None = None) -> int:
    """Refaz `meta/schema_assinaturas` a partir da bronze (na ordem de coleta). Substitui a tabela.
    `excluir_run`: execução em andamento (a bronze dela já foi gravada; ela se registra depois)."""
    agora = agora or utcnow()
    arquivos = []
    for p in (lake.root / "bronze").glob("source=*/dt=*/run=*.json.gz"):
        try:
            dia = datetime.fromisoformat(p.parent.name.removeprefix("dt=")).date()
        except ValueError:
            continue
        if dias is None or dia >= (agora - timedelta(days=dias)).date():
            arquivos.append(p)
    envelopes = []
    for p in arquivos:
        env = lake.read_bronze(Path(p))
        envelopes.append((str(env.get("ingested_at") or ""), env))
    envelopes.sort(key=lambda x: x[0])
    lake.write(TABELA, lake.read(TABELA).iloc[0:0])
    total = 0
    for ingested, env in envelopes:
        source = env.get("source")
        registros = env.get("records") or []
        if not source or not registros or (excluir_run and str(env.get("run_id")) == excluir_run):
            continue
        em = pd.Timestamp(ingested).to_pydatetime() if ingested else agora
        total += len(registrar_execucao(lake, str(env.get("run_id")), em,
                                        [(source, registros, essenciais_por_fonte.get(source, ()))]))
    return total


def situacao_schema(lake: Lake, agora: datetime | None = None, horas_alerta: int = 24) -> list[dict[str, Any]]:
    """Por fonte: assinatura atual, última mudança e mudança grave recente (alerta)."""
    agora = pd.Timestamp(agora or utcnow())
    tab = lake.read(TABELA)
    saida = []
    for source, g in tab.sort_values("em").groupby("source"):
        ult = g.iloc[-1]
        mud = g[g["mudou"].fillna(False).astype(bool)]
        graves = g[g["grave"].fillna(False).astype(bool)
                   & (pd.to_datetime(g["em"], utc=True) >= agora - timedelta(hours=horas_alerta))]
        ult_grave = graves.iloc[-1] if not graves.empty else None
        saida.append({
            "fonte": source, "hash": ult["hash"], "registros": int(ult["registros"] or 0),
            "assinaturas_no_historico": int(g["hash"].nunique()),
            "ultima_mudanca_em": mud.iloc[-1]["em"] if not mud.empty else None,
            "ultima_mudanca": resumo(json.loads(mud.iloc[-1]["mudancas"])) if not mud.empty and
            isinstance(mud.iloc[-1]["mudancas"], str) else None,
            "grave_recente": None if ult_grave is None else resumo(json.loads(ult_grave["mudancas"] or "{}")),
            "essenciais": json.loads(ult["essenciais"]) if isinstance(ult["essenciais"], str) else {},
        })
    return saida


# ---------------------------------------------------------------- qualidade por fonte
def _pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


def _nota(ind: dict[str, Any]) -> float | None:
    disponiveis = {k: p for k, p in PESOS.items() if ind.get(k) is not None}
    if not disponiveis:
        return None
    return round(sum(ind[k] * p for k, p in disponiveis.items()) / sum(disponiveis.values()), 1)


def por_fonte(lake: Lake, agora: datetime | None = None, dias: int = 30) -> list[dict[str, Any]]:
    agora = pd.Timestamp(agora or utcnow())
    inicio = agora - timedelta(days=dias)
    src = lake.read("meta/source_runs")
    src = src[pd.to_datetime(src["finalizada_em"], utc=True) >= inicio]
    jobs = lake.read("silver/jobs")
    grupos = jobs.groupby(jobs["canonical_job_id"].fillna(jobs["job_id"]))["source"].nunique()
    janela = jobs[pd.to_datetime(jobs["primeira_observacao"], utc=True) >= inicio]
    sk = lake.read("silver/job_skills")
    com_skill = set(sk.loc[sk["tipo"].isna() | (sk["tipo"] == "tecnica"), "job_id"])
    fontes = sorted(set(src["source"]) | set(janela["source"]))
    saida = []
    for f in fontes:
        r = src[src["source"] == f]
        j = janela[janela["source"] == f]
        n = len(j)
        desc = j["descricao"].fillna("").str.len()
        local = j["uf"].notna() | j["cidade"].notna() | j["pais_iso"].notna()
        campos = [j["empresa"].notna(), j["publicada_em"].notna(), local, j["modalidade"].fillna("nao_informada") != "nao_informada"]
        ind = {
            "fonte": f, "periodo_dias": dias, "execucoes": int(len(r)), "vagas": int(n),
            "disponibilidade_pct": _pct(int(r["ok"].astype(bool).sum()), len(r)),
            "validos_pct": _pct(int(r["validos"].sum()), int(r["coletados"].sum())),
            "relevancia_pct": _pct(int((j["familia"] != "outra").sum()), n),
            "descricao_completa_pct": _pct(int((desc >= DESCRICAO_COMPLETA_MIN).sum()), n),
            "campos_pct": round(sum(float(c.mean()) for c in campos) / len(campos) * 100, 1) if n else None,
            "extracao_pct": _pct(int(j["job_id"].isin(com_skill).sum()), n),
            "exclusivas_pct": _pct(int((j["canonical_job_id"].fillna(j["job_id"]).map(grupos) == 1).sum()), n),
            "amostra_pequena": n < AMOSTRA_MIN,
        }
        ind["nota"] = _nota(ind)
        saida.append(ind)
    return sorted(saida, key=lambda x: (x["nota"] is None, -(x["nota"] or 0)))


def markdown(qualidade: list[dict[str, Any]], schema: list[dict[str, Any]]) -> str:
    def v(x):
        return "—" if x is None else f"{x}%"
    linhas = []
    if qualidade:
        d = qualidade[0]["periodo_dias"]
        linhas += [f"#### Qualidade por fonte ({d} dias)", "",
                   "| Fonte | Nota | Vagas | Disponível | Relevantes | Descrição completa | Campos | Extração | Exclusivas |",
                   "|---|---|---|---|---|---|---|---|---|"]
        linhas += [f"| {q['fonte']} | {q['nota'] if q['nota'] is not None else '—'}"
                   f"{' (amostra pequena)' if q['amostra_pequena'] else ''} | {q['vagas']} | {v(q['disponibilidade_pct'])} | "
                   f"{v(q['relevancia_pct'])} | {v(q['descricao_completa_pct'])} | {v(q['campos_pct'])} | "
                   f"{v(q['extracao_pct'])} | {v(q['exclusivas_pct'])} |" for q in qualidade]
        linhas.append("")
    if schema:
        linhas += ["#### Formato das respostas", "", "| Fonte | Assinatura | Última mudança | Mudança grave (24 h) |",
                   "|---|---|---|---|"]
        for s in schema:
            quando = pd.Timestamp(s["ultima_mudanca_em"]).strftime("%Y-%m-%d") if s["ultima_mudanca_em"] is not None else "—"
            linhas.append(f"| {s['fonte']} | `{s['hash']}` | {quando}{': ' + s['ultima_mudanca'] if s['ultima_mudanca'] else ''} | "
                          f"{'⚠️ ' + s['grave_recente'] if s['grave_recente'] else 'não'} |")
    return "\n".join(linhas)

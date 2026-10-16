"""Geração e validação dos JSON públicos.

Só o que está no contrato sai daqui. Descrições, score pessoal, lacunas, perfil, candidaturas
e notificações NUNCA entram — o schema usa additionalProperties=false para garantir isso.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker

from .. import __version__
from ..analytics import market
from ..analytics.selection import relevantes
from ..settings import Settings
from ..storage import Lake
from ..transformations.skills import Taxonomy
from .contract import FILES, MAJOR, SCHEMA_VERSION, schemas

NOTA = ("Amostra das fontes e termos configurados no JobRadar; não representa o mercado inteiro. "
        "Tendências consideram o volume coletado por período.")


class ContractError(ValueError):
    pass


def _iso(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    ts = pd.Timestamp(v)
    if pd.isna(ts):
        return None
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _nulo(v: Any) -> Any:
    return None if v is None or (not isinstance(v, (list, dict, str)) and pd.isna(v)) else v


def _contagem(itens: list[dict]) -> list[dict]:
    return [{"value": i["valor"], "jobs": i["vagas"], "pct": i["percentual"]} for i in itens]


def construir(s: Settings, agora: datetime, run_id: str, limite_vagas: int = 300,
              janela_vagas: int = 30) -> dict[str, dict[str, Any]]:
    snap = market.carregar(Lake(s.lake))
    tax = Taxonomy(s.skills)
    min_n = int(s.scoring["recomendacoes"]["min_vagas_janela"])
    c = snap.canonicas
    primeira = pd.to_datetime(c["primeira_observacao"], utc=True)
    janela = {"start": primeira.min().date().isoformat() if len(c) else None,
              "end": primeira.max().date().isoformat() if len(c) else None}
    fontes = [{"source": f["fonte"], "status_last_run": f["status_ultima_execucao"],
               "last_success_at": _iso(f["ultima_coleta_ok"]), "records_last_run": f["registros_ultima_execucao"],
               "jobs_in_history": f["vagas_no_historico"]} for f in market.fontes(snap)]

    def envelope(dataset: str, data: dict, observacoes: int, window: dict | None = None) -> dict:
        return {"schema_version": SCHEMA_VERSION, "dataset": dataset, "generated_at": _iso(agora),
                "run_id": run_id, "data_window": window or janela,
                "coverage": {"sources": fontes, "observations": observacoes, "note": NOTA}, "data": data}

    # ---- market-summary
    r = market.resumo(snap, agora)
    ult = market.ultima_execucao_ok(snap)
    t, q = r["totais"], r["qualidade"]
    summary = envelope("market-summary", {
        "totals": {"observed": t["vagas_observadas"], "active": t["ativas"], "status_unknown": t["status_desconhecido"],
                   "closed": t["encerradas"], "new_7d": t["novas_7_dias"], "new_30d": t["novas_30_dias"],
                   "cross_source_duplicates": t["duplicatas_entre_fontes"]},
        "by_modality": _contagem(r["por_modalidade"]), "by_seniority": _contagem(r["por_senioridade"]),
        "by_family": _contagem(r["por_familia"]), "by_source": _contagem(r["por_fonte"]),
        "by_state": _contagem(r["por_uf"]),
        "quality": {"runs": q["execucoes"], "failed_runs": q["execucoes_com_falha"],
                    "records_collected": q["registros_coletados"], "records_invalid": q["registros_invalidos"],
                    "invalid_rate_pct": q["taxa_invalidos_pct"], "missing_published_at_pct": q["vagas_sem_data_publicacao_pct"],
                    "missing_company_pct": q["vagas_sem_empresa_pct"]},
        "last_successful_run": {"run_id": ult["run_id"], "status": ult["status"],
                                "finished_at": _iso(ult["finalizada_em"])} if ult else None,
    }, len(c))

    # ---- skill-trends (escopo: famílias de dados, sem recorte pessoal)
    familias = [f for f in s.filtros.get("familias", []) if f != "outra"]
    janela_dias = int(s.scoring["recomendacoes"]["janela_dias"])
    mascara = c["familia"].isin(familias) & (primeira >= agora - timedelta(days=janela_dias))
    atual = market.frequencia_competencias(snap, mascara)
    n_atual = int(mascara.sum())
    mensal = market.tendencias_mensais(snap, familias)
    sen = snap.monthly[snap.monthly["familia"].isin(familias)] if not snap.monthly.empty else snap.monthly
    tot_sen = sen[sen["skill_id"] == "__total__"].groupby("senioridade")["total_vagas"].sum()
    por_sen = sen[sen["skill_id"] != "__total__"].groupby(["senioridade", "skill_id"], as_index=False)["vagas_com_skill"].sum()
    trends = envelope("skill-trends", {
        "taxonomy": [{"id": k.id, "name": k.nome, "category": k.categoria} for k in tax.skills],
        "scope": {"families": familias, "cohort": "mes_da_primeira_observacao"},
        "min_sample": min_n,
        "current": {"window_days": janela_dias, "n": n_atual, "low_sample": n_atual < min_n,
                    "skills": [{"skill_id": x.skill_id, "jobs": int(x.vagas), "required_jobs": int(x.vagas_requisito),
                                "pct": float(x.percentual), "required_pct": float(x.percentual_requisito)}
                               for x in atual.itertuples()]},
        "monthly": [{"month": x.mes, "skill_id": x.skill_id, "jobs": int(x.vagas_com_skill),
                     "total_jobs": int(x.total_vagas), "pct": float(x.percentual),
                     "low_sample": int(x.total_vagas) < min_n} for x in mensal.itertuples()],
        "by_seniority": [{"seniority": x.senioridade, "skill_id": x.skill_id, "jobs": int(x.vagas_com_skill),
                          "total_jobs": int(tot_sen.get(x.senioridade, 0)),
                          "pct": round(100 * x.vagas_com_skill / tot_sen.get(x.senioridade, 1), 1),
                          "low_sample": int(tot_sen.get(x.senioridade, 0)) < min_n} for x in por_sen.itertuples()],
    }, n_atual)

    # ---- jobs (vagas relevantes, sem descrição e sem score pessoal)
    m = relevantes(snap.jobs, snap.skills, s.filtros, agora, janela_vagas)
    sel = snap.jobs[m].copy()
    sel["_ord"] = pd.to_datetime(sel["publicada_em"], utc=True).fillna(pd.to_datetime(sel["primeira_observacao"], utc=True))
    sel = sel.sort_values("_ord", ascending=False)
    total_rel = len(sel)
    sel = sel.head(limite_vagas)
    sk = snap.skills[snap.skills["job_id"].isin(sel["job_id"])]
    todas = sk.groupby("job_id")["skill_id"].apply(lambda x: sorted(set(x))).to_dict()
    req = sk[sk["importancia"] == "requisito"].groupby("job_id")["skill_id"].apply(lambda x: sorted(set(x))).to_dict()
    itens = [{
        "id": j["job_id"], "title": j["titulo"][:300], "company": _nulo(j["empresa"]), "city": _nulo(j["cidade"]) or None,
        "state": _nulo(j["uf"]), "modality": j["modalidade"], "seniority": j["senioridade"], "family": j["familia"],
        "source": j["source"], "url": j["url"], "published_at": _iso(j["publicada_em"]),
        "first_seen_at": _iso(j["primeira_observacao"]), "last_seen_at": _iso(j["ultima_observacao"]),
        "status": j["status"], "skills": todas.get(j["job_id"], []), "required_skills": req.get(j["job_id"], []),
    } for j in sel.to_dict("records") if str(j["url"]).startswith("https://")]
    jobs_doc = envelope("jobs", {
        "selection": {"window_days": janela_vagas, "limit": limite_vagas, "total_relevant": total_rel,
                      "sort": "published_at_desc",
                      "criteria": "famílias de dados, senioridade e modalidade/local conforme config/sources.yaml"},
        "items": itens,
    }, len(itens), {"start": (agora - timedelta(days=janela_vagas)).date().isoformat(), "end": agora.date().isoformat()})

    return {"market-summary": summary, "skill-trends": trends, "jobs": jobs_doc}


def validar(docs: dict[str, dict[str, Any]]) -> None:
    sch = schemas()
    erros = []
    for nome, doc in docs.items():
        v = Draft202012Validator(sch[nome], format_checker=FormatChecker())
        for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path)):
            erros.append(f"{nome}: {'/'.join(map(str, e.path)) or '(raiz)'}: {e.message[:200]}")
    jobs = docs.get("jobs", {}).get("data", {}).get("items", [])
    ids = [j["id"] for j in jobs]
    if len(ids) != len(set(ids)):
        erros.append("jobs: ids duplicados")
    if erros:
        raise ContractError("contrato inválido:\n  " + "\n  ".join(erros[:50]))


def _registros(nome: str, doc: dict) -> int:
    d = doc["data"]
    return {"jobs": lambda: len(d["items"]), "skill-trends": lambda: len(d["monthly"]),
            "market-summary": lambda: d["totals"]["observed"]}[nome]()


def publicar(docs: dict[str, dict[str, Any]], out_dir: Path, run_id: str, agora: datetime) -> Path:
    """Valida tudo ANTES de escrever. Escreve num diretório temporário e troca no fim:
    se algo falhar, out_dir/v1 continua com a versão anterior intacta."""
    validar(docs)
    destino = Path(out_dir) / MAJOR
    tmp = Path(out_dir) / f".{MAJOR}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    arquivos = []
    for nome in FILES:
        corpo = json.dumps(docs[nome], ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        (tmp / f"{nome}.json").write_text(corpo, encoding="utf-8")
        arquivos.append({"dataset": nome, "path": f"{MAJOR}/{nome}.json",
                         "sha256": hashlib.sha256(corpo.encode()).hexdigest(),
                         "records": _registros(nome, docs[nome]), "bytes": len(corpo.encode())})
    manifest = {"schema_version": SCHEMA_VERSION, "generated_at": _iso(agora), "run_id": run_id,
                "pipeline_version": __version__, "files": arquivos}
    v = Draft202012Validator(schemas()["manifest"], format_checker=FormatChecker())
    if list(v.iter_errors(manifest)):
        raise ContractError("manifest inválido")
    (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for nome, sch in schemas().items():
        (tmp / f"{nome}.schema.json").write_text(json.dumps(sch, ensure_ascii=False, indent=2), encoding="utf-8")
    if destino.exists():
        shutil.rmtree(destino)
    tmp.rename(destino)
    return destino


def exportar_schemas(*destinos: Path) -> None:
    for d in destinos:
        d.mkdir(parents=True, exist_ok=True)
        for nome, sch in schemas().items():
            (d / f"{nome}.schema.json").write_text(json.dumps(sch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

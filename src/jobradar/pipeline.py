"""Orquestração de uma execução: coleta → bronze → silver (merge incremental) → gold.

Idempotência: rodar duas vezes no mesmo dia não duplica vagas; apenas registra uma nova
observação e atualiza `ultima_observacao`. Uma fonte com erro não derruba as outras.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
from pydantic import ValidationError

from .collectors.base import Collector, CollectResult
from .scoring import Profile, calcular
from .settings import Settings
from .storage import Lake, utcnow
from .transformations.silver import PREFERENCIA_FONTE, canonizar
from .transformations.skills import SkillMatch, Taxonomy

log = logging.getLogger("jobradar.pipeline")
FUSO = ZoneInfo("America/Sao_Paulo")


@dataclass
class SourceMetrics:
    source: str
    ok: bool
    coletados: int = 0
    validos: int = 0
    invalidos: int = 0
    duplicatas_fonte: int = 0
    novas: int = 0
    requisicoes: int = 0
    retentativas: int = 0
    erros: list[str] = field(default_factory=list)
    duracao_s: float = 0.0


@dataclass
class RunReport:
    run_id: str
    status: str                      # sucesso | parcial | falha
    iniciada_em: datetime
    finalizada_em: datetime | None = None
    fontes: list[SourceMetrics] = field(default_factory=list)
    observadas: int = 0
    novas: int = 0
    duplicatas_entre_fontes: int = 0
    requisitos_alterados: int = 0
    meses_recalculados: list[str] = field(default_factory=list)
    vagas_pontuadas: int = 0
    bronze_particoes_removidas: int = 0
    duracao_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["iniciada_em"] = self.iniciada_em.isoformat()
        d["finalizada_em"] = self.finalizada_em.isoformat() if self.finalizada_em else None
        return d


def run(s: Settings, collectors: list[Collector], run_id: str | None = None,
        agora: datetime | None = None) -> RunReport:
    t0 = time.monotonic()
    agora = agora or utcnow()
    run_id = run_id or agora.strftime("%Y%m%dT%H%M%SZ")
    dia = agora.astimezone(FUSO).date()
    lake = Lake(s.lake)
    lake.ensure_layout()
    tax = Taxonomy(s.skills)
    report = RunReport(run_id=run_id, status="falha", iniciada_em=agora)

    # ---------------- coleta + bronze + parsing ----------------
    linhas: list[dict] = []
    skills_lote: dict[str, list[SkillMatch]] = {}
    problemas: list[dict] = []
    for coletor in collectors:
        ts = time.monotonic()
        try:
            res = coletor.collect(s.termos)
        except Exception as e:  # defesa: coletor com bug não derruba a execução
            log.exception("%s: erro inesperado", coletor.name)
            res = CollectResult(coletor.name)
            res.errors.append(f"{type(e).__name__}: {e}")
        lake.write_bronze(coletor.name, dia, run_id, {
            "run_id": run_id, "source": coletor.name, "ingested_at": agora.isoformat(),
            "params": res.params, "requests": res.requests, "retries": res.retries,
            "errors": res.errors, "record_count": len(res.records), "records": res.records,
        })
        m = SourceMetrics(coletor.name, ok=res.ok, coletados=len(res.records),
                          duplicatas_fonte=res.duplicates_in_source, requisicoes=res.requests,
                          retentativas=res.retries, erros=res.errors)
        for rec in res.records:
            try:
                cj = canonizar(coletor.to_raw_job(rec), tax, agora, run_id)
            except (ValidationError, KeyError, TypeError, ValueError) as e:
                m.invalidos += 1
                problemas.append(_problema(run_id, coletor.name, rec, "registro", "invalido", str(e), agora))
                continue
            m.validos += 1
            for campo in ("empresa", "publicada_em"):
                if cj.row[campo] is None:
                    problemas.append(_problema(run_id, coletor.name, rec, campo, "ausente", "", agora))
            linhas.append(cj.row)
            skills_lote[cj.row["job_id"]] = cj.skills
        m.duracao_s = round(time.monotonic() - ts, 2)
        report.fontes.append(m)
        log.info("%s: %d coletados, %d válidos, %d inválidos, erros=%s",
                 m.source, m.coletados, m.validos, m.invalidos, m.erros)

    fontes_ok = [f for f in report.fontes if f.ok]
    if not fontes_ok:
        report.status = "falha"
        return _finalizar(lake, report, problemas, t0)
    report.status = "sucesso" if len(fontes_ok) == len(report.fontes) else "parcial"

    # ---------------- silver: merge incremental ----------------
    jobs = lake.read("silver/jobs")
    lote = pd.DataFrame(linhas) if linhas else pd.DataFrame(columns=jobs.columns)
    if not lote.empty:
        # Fonte sem id estável: reaproveita o job_id já conhecido para a mesma URL canônica.
        por_url = dict(zip(jobs["source"] + "|" + jobs["url_canonica"], jobs["job_id"]))
        novo_id = [por_url.get(f"{s_}|{u}", j) for s_, u, j in zip(lote["source"], lote["url_canonica"], lote["job_id"])]
        for antigo, novo in zip(lote["job_id"], novo_id):
            if antigo != novo:
                skills_lote[novo] = skills_lote.pop(antigo)
        lote["job_id"] = novo_id
        lote = lote.drop_duplicates("job_id", keep="last")

    ids_lote = set(lote["job_id"])
    conhecidos = set(jobs["job_id"])
    novos = ids_lote - conhecidos
    report.observadas, report.novas = len(ids_lote), len(novos)
    for f in report.fontes:
        f.novas = int(lote.loc[lote["job_id"].isin(novos) & (lote["source"] == f.source)].shape[0])

    j_idx = jobs.set_index("job_id")
    l_idx = lote.set_index("job_id")
    repetidos = l_idx.index.intersection(j_idx.index)
    if len(repetidos):
        l_idx.loc[repetidos, "primeira_observacao"] = j_idx.loc[repetidos, "primeira_observacao"]
    partes = [p for p in (j_idx.drop(index=repetidos), l_idx) if not p.empty]
    jobs = pd.concat(partes).reset_index() if partes else jobs
    jobs = _status(jobs, agora, s.retencao)
    jobs = _canonicas(jobs)
    report.duplicatas_entre_fontes = int((~jobs["is_canonica"] & jobs["job_id"].isin(ids_lote)).sum())

    # Retenção: descrição some depois de N dias sem observação (hash e competências ficam).
    limite_desc = agora - timedelta(days=int(s.retencao.get("descricao_dias_apos_ultima_observacao", 180)))
    jobs.loc[jobs["ultima_observacao"] < limite_desc, "descricao"] = None

    # Competências e observações (histórico de mudanças de requisitos)
    skills = lake.read("silver/job_skills")
    antes = skills.groupby("job_id")["skill_id"].apply(lambda x: set(x)).to_dict()
    novas_skills, observacoes = [], []
    alterados: set[str] = set()
    for row in lote.itertuples():
        atuais = skills_lote.get(row.job_id, [])
        ids = {m.skill_id for m in atuais}
        prev = antes.get(row.job_id)
        mudou = prev is not None and prev != ids
        if mudou:
            alterados.add(row.job_id)
        observacoes.append({
            "job_id": row.job_id, "run_id": run_id, "observada_em": agora,
            "descricao_hash": row.descricao_hash, "titulo": row.titulo,
            "skills": ",".join(sorted(ids)), "mudou_requisitos": mudou,
            "skills_adicionadas": ",".join(sorted(ids - prev)) if mudou else None,
            "skills_removidas": ",".join(sorted(prev - ids)) if mudou else None,
        })
        novas_skills += [{"job_id": row.job_id, "skill_id": m.skill_id, "importancia": m.importancia,
                          "termo": m.termo, "run_id": run_id} for m in atuais]
    report.requisitos_alterados = len(alterados)
    skills = pd.concat([skills[~skills["job_id"].isin(ids_lote)], pd.DataFrame(novas_skills,
                        columns=skills.columns)], ignore_index=True)

    lake.write("silver/jobs", jobs)
    lake.write("silver/job_skills", skills)
    lake.append("silver/observations", pd.DataFrame(observacoes))

    # ---------------- gold ----------------
    report.meses_recalculados = _skill_monthly(lake, jobs, skills, novos | alterados)
    report.vagas_pontuadas = _scores(lake, s, jobs, skills, ids_lote, agora)

    report.bronze_particoes_removidas = lake.prune_bronze(dia, int(s.retencao.get("bronze_dias", 90)))
    return _finalizar(lake, report, problemas, t0)


# ---------------------------------------------------------------- helpers
def _problema(run_id, source, rec, campo, problema, detalhe, agora) -> dict:
    rid = rec.get("id") if isinstance(rec, dict) else None
    return {"run_id": run_id, "source": source, "source_job_id": str(rid) if rid is not None else None,
            "campo": campo, "problema": problema, "detalhe": detalhe[:300], "registrado_em": agora}


def _status(jobs: pd.DataFrame, agora: datetime, ret: dict) -> pd.DataFrame:
    """Regra de expiração (docs/architecture.md):
    encerrada  → prazo de inscrição informado pela fonte já passou (evidência explícita);
    ativa      → observada nos últimos N dias;
    desconhecida → sem observação há mais de N dias. Sumir de uma coleta não encerra a vaga.
    """
    dias = int(ret.get("status_desconhecido_apos_dias", 14))
    prazo = pd.to_datetime(jobs["prazo_em"], utc=True)
    visto = pd.to_datetime(jobs["ultima_observacao"], utc=True)
    encerrada = prazo.notna() & (prazo < agora)
    recente = (agora - visto) <= pd.Timedelta(days=dias)
    jobs["status"] = "desconhecida"
    jobs.loc[recente, "status"] = "ativa"
    jobs.loc[encerrada, "status"] = "encerrada"
    jobs["motivo_status"] = f"nao_observada_ha_mais_de_{dias}_dias"
    jobs.loc[recente, "motivo_status"] = f"observada_nos_ultimos_{dias}_dias"
    jobs.loc[encerrada, "motivo_status"] = "prazo_de_inscricao_vencido"
    return jobs


def _canonicas(jobs: pd.DataFrame) -> pd.DataFrame:
    """Mesma vaga em fontes diferentes: elege uma canônica (ATS direto > agregador)."""
    jobs = jobs.copy()
    jobs["_pref"] = jobs["source"].map(PREFERENCIA_FONTE).fillna(5)
    jobs = jobs.sort_values(["_pref", "primeira_observacao", "job_id"])
    chave = jobs["chave_alternativa"].fillna(jobs["job_id"])
    jobs["canonical_job_id"] = jobs.groupby(chave)["job_id"].transform("first")
    jobs["is_canonica"] = jobs["canonical_job_id"] == jobs["job_id"]
    return jobs.drop(columns="_pref").sort_values("primeira_observacao").reset_index(drop=True)


def _skill_monthly(lake: Lake, jobs: pd.DataFrame, skills: pd.DataFrame, afetados: set[str]) -> list[str]:
    """Agregado mensal incremental: só recalcula meses de vagas novas ou com requisitos alterados.
    Mês = mês da primeira observação (coorte de vagas observadas), no fuso de São Paulo."""
    atual = lake.read("gold/skill_monthly")
    base = jobs[jobs["is_canonica"]].copy()
    base["mes"] = pd.to_datetime(base["primeira_observacao"], utc=True).dt.tz_convert(FUSO).dt.strftime("%Y-%m")
    meses = sorted(set(base["mes"])) if atual.empty else sorted(set(base.loc[base["job_id"].isin(afetados), "mes"]))
    if not meses:
        return []
    con = duckdb.connect()
    con.register("base", base[["job_id", "mes", "familia", "senioridade"]])
    con.register("sk", skills[["job_id", "skill_id", "importancia"]])
    novo = con.execute("""
        WITH totais AS (
            SELECT mes, familia, senioridade, COUNT(*) AS total_vagas
            FROM base WHERE mes IN (SELECT UNNEST(?)) GROUP BY ALL
        )
        SELECT b.mes, b.familia, b.senioridade, s.skill_id,
               COUNT(DISTINCT b.job_id) AS vagas_com_skill,
               COUNT(DISTINCT CASE WHEN s.importancia = 'requisito' THEN b.job_id END) AS vagas_requisito,
               ANY_VALUE(t.total_vagas) AS total_vagas
        FROM base b
        JOIN sk s USING (job_id)
        JOIN totais t USING (mes, familia, senioridade)
        GROUP BY ALL
        UNION ALL
        -- grupos sem nenhuma competência identificada também entram no denominador
        SELECT mes, familia, senioridade, '__total__', 0, 0, total_vagas FROM totais
    """, [meses]).df()
    con.close()
    lake.write("gold/skill_monthly", pd.concat([atual[~atual["mes"].isin(meses)], novo], ignore_index=True))
    return meses


def _scores(lake: Lake, s: Settings, jobs: pd.DataFrame, skills: pd.DataFrame,
            ids_lote: set[str], agora: datetime) -> int:
    perfil = Profile.from_dict(s.profile)
    atual = lake.read("gold/job_scores")
    alvo = jobs[jobs["is_canonica"] & (jobs["status"] != "encerrada")]
    precisa = alvo["job_id"].isin(ids_lote) | ~alvo["job_id"].isin(atual["job_id"]) \
        | alvo["job_id"].isin(atual.loc[atual["perfil_hash"] != perfil.hash, "job_id"])
    alvo = alvo[precisa]
    if alvo.empty:
        return 0
    por_job = skills.groupby("job_id")[["skill_id", "importancia"]].apply(lambda d: d.to_dict("records")).to_dict()
    excl = s.filtros.get("palavras_excludentes", [])
    linhas = []
    for job in alvo.to_dict("records"):
        r = calcular(job, por_job.get(job["job_id"], []), perfil, s.scoring["aderencia"], excl)
        linhas.append({"job_id": job["job_id"], "score": r.score,
                       "explicacao": json.dumps(r.explicacao, ensure_ascii=False),
                       "lacunas": json.dumps(r.lacunas), "sem_evidencia": json.dumps(r.sem_evidencia),
                       "calculado_em": agora, "perfil_hash": perfil.hash})
    novo = pd.DataFrame(linhas)
    lake.write("gold/job_scores", pd.concat([atual[~atual["job_id"].isin(novo["job_id"])], novo], ignore_index=True))
    return len(novo)


def _finalizar(lake: Lake, report: RunReport, problemas: list[dict], t0: float) -> RunReport:
    report.finalizada_em = utcnow()
    report.duracao_s = round(time.monotonic() - t0, 2)
    lake.append("silver/quality_issues", pd.DataFrame(problemas))
    lake.append("meta/source_runs", pd.DataFrame([{
        "run_id": report.run_id, "source": f.source, "ok": f.ok, "coletados": f.coletados,
        "validos": f.validos, "invalidos": f.invalidos, "duplicatas_fonte": f.duplicatas_fonte,
        "novas": f.novas, "requisicoes": f.requisicoes, "retentativas": f.retentativas,
        "erros": "; ".join(f.erros) or None, "finalizada_em": report.finalizada_em,
    } for f in report.fontes]))
    lake.append("meta/runs", pd.DataFrame([{
        "run_id": report.run_id, "iniciada_em": report.iniciada_em, "finalizada_em": report.finalizada_em,
        "status": report.status, "duracao_s": report.duracao_s,
        "metricas": json.dumps(report.to_dict(), ensure_ascii=False, default=str),
    }]))
    log.info("execução %s: %s em %.1fs (%d observadas, %d novas)", report.run_id, report.status,
             report.duracao_s, report.observadas, report.novas)
    return report

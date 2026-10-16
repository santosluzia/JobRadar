"""RawJob → linha canônica da silver (sem estado; o merge com o histórico fica no pipeline)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from ..models import RawJob
from . import normalize
from .skills import SkillMatch, Taxonomy
from .text import normalizar, sha1, url_canonica

# Ordem de preferência quando a mesma vaga aparece em mais de uma fonte:
# link direto do ATS > agregador.
PREFERENCIA_FONTE = {"gupy": 0, "greenhouse": 1, "lever": 2, "adzuna": 9}

RUIDO_TITULO = re.compile(r"\b(vaga|afirmativa|para|pessoas?|mulheres|pcd|remoto|hibrido|presencial)\b|[-–|/()]")


@dataclass
class CanonicalJob:
    row: dict
    skills: list[SkillMatch]


def chave_alternativa(empresa: str | None, titulo: str, uf: str | None) -> str | None:
    """Mesma empresa + mesmo título (sem ruído) + mesma UF = provável mesma vaga em outra fonte."""
    if not empresa:
        return None
    titulo_limpo = " ".join(RUIDO_TITULO.sub(" ", normalizar(titulo)).split())
    return sha1(normalizar(empresa), titulo_limpo, uf or "")


def canonizar(raw: RawJob, tax: Taxonomy, agora: datetime, run_id: str) -> CanonicalJob:
    skills = tax.extrair(raw.title, raw.description)
    ids = {s.skill_id for s in skills}
    senioridade, o_sen = normalize.senioridade(raw.title, raw.description)
    modalidade, o_mod = normalize.modalidade(raw.modality_raw, raw.title, raw.description)
    familia, o_fam = normalize.familia(raw.title, ids)
    uf = normalize.uf(raw.state, raw.location_raw)
    canon = url_canonica(raw.url)
    job_id = sha1(raw.source, raw.source_job_id) if raw.source_job_id else sha1(raw.source, canon)

    row = {
        "job_id": job_id,
        "source": raw.source,
        "source_job_id": raw.source_job_id,
        "url": raw.url,
        "url_canonica": canon,
        "titulo": raw.title,
        "titulo_norm": normalizar(raw.title),
        "empresa": raw.company or None,
        "cidade": raw.city or None,
        "uf": uf,
        "pais": raw.country or None,
        "local_raw": raw.location_raw,
        "modalidade": modalidade.value,
        "senioridade": senioridade.value,
        "familia": familia.value,
        "origem_campos": json.dumps({
            "modalidade": o_mod, "senioridade": o_sen, "familia": o_fam,
            "uf": "fonte" if raw.state else ("local_raw" if uf else "nao_informada"),
            "publicada_em": "fonte" if raw.published_at else "nao_informada",
        }),
        "publicada_em": raw.published_at,
        "prazo_em": raw.deadline_at,
        "primeira_observacao": agora,
        "ultima_observacao": agora,
        "ultima_execucao": run_id,
        "descricao": raw.description,
        "descricao_hash": sha1(raw.description) if raw.description else None,
        "chave_alternativa": chave_alternativa(raw.company, raw.title, uf),
        "atualizado_em": agora,
    }
    return CanonicalJob(row=row, skills=skills)

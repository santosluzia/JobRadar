"""RawJob → linha canônica da silver (sem estado; o merge com o histórico fica no pipeline)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from ..models import RawJob
from . import geografia, normalize
from .skills import SkillMatch, Taxonomy
from .text import normalizar, sha1, url_canonica

# Ordem de preferência quando a mesma vaga aparece em mais de uma fonte:
# link direto do ATS > agregador.
PREFERENCIA_FONTE = {"gupy": 0, "greenhouse": 1, "lever": 2, "ashby": 3, "smartrecruiters": 4, "adzuna": 9}

RUIDO_TITULO = re.compile(r"\b(vaga|afirmativa|para|pessoas?|mulheres|pcd|remoto|hibrido|presencial)\b|[-–|/()]")


@dataclass
class CanonicalJob:
    row: dict
    skills: list[SkillMatch]


def chave_alternativa(empresa: str | None, titulo: str, local: str | None) -> str | None:
    """Mesma empresa + mesmo título (sem ruído) + mesmo local = provável mesma vaga em outra fonte.
    `local` vem de geografia.chave_local: a UF no Brasil (ou vazio), país + cidade nos demais países."""
    if not empresa:
        return None
    titulo_limpo = " ".join(RUIDO_TITULO.sub(" ", normalizar(titulo)).split())
    return sha1(normalizar(empresa), titulo_limpo, local or "")


def canonizar(raw: RawJob, tax: Taxonomy, agora: datetime, run_id: str) -> CanonicalJob:
    skills = tax.extrair(raw.title, raw.description)
    ids = {s.skill_id for s in skills}
    senioridade, o_sen = normalize.senioridade(raw.title, raw.description)
    modalidade, o_mod = normalize.modalidade(raw.modality_raw, raw.title, raw.description)
    familia, o_fam = normalize.familia(raw.title, ids)
    loc = geografia.localizar(raw.country, raw.state, raw.city, raw.location_raw)
    uf = loc.uf
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
        "pais_iso": loc.pais_iso,
        "regiao": loc.regiao,
        "cidade_norm": loc.cidade_norm,
        "local_raw": raw.location_raw,
        "modalidade": modalidade.value,
        "senioridade": senioridade.value,
        "familia": familia.value,
        "origem_campos": json.dumps({
            "modalidade": o_mod, "senioridade": o_sen, "familia": o_fam,
            "uf": "fonte" if raw.state and uf else ("local_raw" if uf else "nao_informada"),
            "pais": loc.origem_pais,
            "publicada_em": "fonte" if raw.published_at else "nao_informada",
        }),
        "publicada_em": raw.published_at,
        "prazo_em": raw.deadline_at,
        "primeira_observacao": agora,
        "ultima_observacao": agora,
        "ultima_execucao": run_id,
        "quadro": raw.board,
        "encerrada_em": None,          # vaga observada agora: se tinha saído do quadro, voltou
        "descricao": raw.description,
        "descricao_hash": sha1(raw.description) if raw.description else None,
        "chave_alternativa": chave_alternativa(raw.company, raw.title,
                                               geografia.chave_local(loc.pais_iso, uf, loc.regiao, loc.cidade_norm)),
        "geografia_versao": geografia.GEOGRAFIA_VERSAO,
        "atualizado_em": agora,
        "taxonomia_versao": tax.versao,
    }
    return CanonicalJob(row=row, skills=skills)

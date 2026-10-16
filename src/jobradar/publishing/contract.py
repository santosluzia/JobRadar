"""Contrato de dados público v1 (JobRadar → portfólio).

Fonte única da verdade dos schemas. `jobradar contract export` grava os JSON Schema em
docs/contracts/v1/ e em publishing/schemas/ — um teste garante que os arquivos estão em dia.

Política de compatibilidade:
- campo novo OPCIONAL → minor (1.1.0), mesmo diretório v1/;
- remover/renomear/mudar tipo → nova major em v2/, publicada em paralelo com v1/ por um período.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0.0"
MAJOR = "v1"
FILES = ("market-summary", "skill-trends", "jobs")

ENUMS = {
    "modality": ["remoto", "hibrido", "presencial", "nao_informada"],
    "seniority": ["estagio", "junior", "pleno", "senior", "lideranca", "nao_informada"],
    "family": ["engenharia_dados", "analytics_engineering", "desenvolvimento_dados",
               "analise_dados", "governanca_qualidade", "outra"],
    "status": ["ativa", "desconhecida", "encerrada"],
}

_dt = {"type": "string", "format": "date-time"}
_dt_null = {"type": ["string", "null"], "format": "date-time"}
_int = {"type": "integer", "minimum": 0}
_pct_null = {"type": ["number", "null"], "minimum": 0, "maximum": 100}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required if required is not None else list(props)}


def _envelope(dataset: str, data: dict[str, Any]) -> dict[str, Any]:
    source = _obj({
        "source": {"type": "string"},
        "status_last_run": {"enum": ["ok", "erro"]},
        "last_success_at": _dt_null,
        "records_last_run": _int,
        "jobs_in_history": _int,
    })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://raw.githubusercontent.com/santosluzia/jobradar/public-data/{MAJOR}/{dataset}.schema.json",
        "title": f"JobRadar {dataset} ({SCHEMA_VERSION})",
        **_obj({
            "schema_version": {"type": "string", "pattern": r"^1\.\d+\.\d+$"},
            "dataset": {"const": dataset},
            "generated_at": _dt,
            "run_id": {"type": "string", "minLength": 1},
            "data_window": _obj({"start": {"type": ["string", "null"], "format": "date"},
                                 "end": {"type": ["string", "null"], "format": "date"}}),
            "coverage": _obj({
                "sources": {"type": "array", "items": source},
                "observations": _int,
                "note": {"type": "string"},
            }),
            "data": data,
        }),
    }


def _contagem() -> dict[str, Any]:
    return {"type": "array", "items": _obj({"value": {"type": "string"}, "jobs": _int,
                                            "pct": {"type": "number", "minimum": 0, "maximum": 100}})}


def schemas() -> dict[str, dict[str, Any]]:
    market = _obj({
        "totals": _obj({k: _int for k in ("observed", "active", "status_unknown", "closed",
                                         "new_7d", "new_30d", "cross_source_duplicates")}),
        "by_modality": _contagem(), "by_seniority": _contagem(), "by_family": _contagem(),
        "by_source": _contagem(), "by_state": _contagem(),
        "quality": _obj({
            "runs": _int, "failed_runs": _int, "records_collected": _int, "records_invalid": _int,
            "invalid_rate_pct": _pct_null, "missing_published_at_pct": _pct_null, "missing_company_pct": _pct_null,
        }),
        "last_successful_run": {"oneOf": [{"type": "null"}, _obj({
            "run_id": {"type": "string"}, "status": {"enum": ["sucesso", "parcial"]}, "finished_at": _dt})]},
    })
    freq = _obj({"skill_id": {"type": "string"}, "jobs": _int, "required_jobs": _int,
                 "pct": {"type": "number", "minimum": 0, "maximum": 100},
                 "required_pct": {"type": "number", "minimum": 0, "maximum": 100}})
    serie = _obj({"month": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}, "skill_id": {"type": "string"},
                  "jobs": _int, "total_jobs": _int, "pct": {"type": "number", "minimum": 0, "maximum": 100},
                  "low_sample": {"type": "boolean"}})
    por_sen = _obj({"seniority": {"enum": ENUMS["seniority"]}, "skill_id": {"type": "string"}, "jobs": _int,
                    "total_jobs": _int, "pct": {"type": "number", "minimum": 0, "maximum": 100},
                    "low_sample": {"type": "boolean"}})
    trends = _obj({
        "taxonomy": {"type": "array", "items": _obj({"id": {"type": "string"}, "name": {"type": "string"},
                                                     "category": {"type": "string"}})},
        "scope": _obj({"families": {"type": "array", "items": {"enum": ENUMS["family"]}},
                       "cohort": {"const": "mes_da_primeira_observacao"}}),
        "min_sample": _int,
        "current": _obj({"window_days": _int, "n": _int, "low_sample": {"type": "boolean"},
                         "skills": {"type": "array", "items": freq}}),
        "monthly": {"type": "array", "items": serie},
        "by_seniority": {"type": "array", "items": por_sen},
    })
    job = _obj({
        "id": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "title": {"type": "string", "minLength": 2, "maxLength": 300},
        "company": {"type": ["string", "null"]},
        "city": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"], "pattern": "^[A-Z]{2}$"},
        "modality": {"enum": ENUMS["modality"]},
        "seniority": {"enum": ENUMS["seniority"]},
        "family": {"enum": ENUMS["family"]},
        "source": {"type": "string"},
        "url": {"type": "string", "pattern": "^https://"},
        "published_at": _dt_null,
        "first_seen_at": _dt,
        "last_seen_at": _dt,
        "status": {"enum": ENUMS["status"]},
        "skills": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "required_skills": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
    })
    jobs = _obj({
        "selection": _obj({"window_days": _int, "limit": _int, "total_relevant": _int,
                           "sort": {"const": "published_at_desc"}, "criteria": {"type": "string"}}),
        "items": {"type": "array", "items": job},
    })
    manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://raw.githubusercontent.com/santosluzia/jobradar/public-data/{MAJOR}/manifest.schema.json",
        "title": f"JobRadar manifest ({SCHEMA_VERSION})",
        **_obj({
            "schema_version": {"type": "string", "pattern": r"^1\.\d+\.\d+$"},
            "generated_at": _dt,
            "run_id": {"type": "string"},
            "pipeline_version": {"type": "string"},
            "files": {"type": "array", "items": _obj({
                "dataset": {"enum": list(FILES)}, "path": {"type": "string"},
                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "records": _int,
                "bytes": _int})},
        }),
    }
    return {
        "market-summary": _envelope("market-summary", market),
        "skill-trends": _envelope("skill-trends", trends),
        "jobs": _envelope("jobs", jobs),
        "manifest": manifest,
    }

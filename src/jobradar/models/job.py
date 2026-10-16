"""Schema canônico. RawJob é o que cada coletor entrega; a normalização vive em transformations/."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Modalidade(str, Enum):
    remoto = "remoto"
    hibrido = "hibrido"
    presencial = "presencial"
    nao_informada = "nao_informada"


class Senioridade(str, Enum):
    estagio = "estagio"
    junior = "junior"
    pleno = "pleno"
    senior = "senior"
    lideranca = "lideranca"
    nao_informada = "nao_informada"


class Familia(str, Enum):
    engenharia_dados = "engenharia_dados"
    analytics_engineering = "analytics_engineering"
    desenvolvimento_dados = "desenvolvimento_dados"
    analise_dados = "analise_dados"
    governanca_qualidade = "governanca_qualidade"
    outra = "outra"


class JobStatus(str, Enum):
    ativa = "ativa"                # vista na última coleta bem-sucedida da fonte
    desconhecida = "desconhecida"  # não vista recentemente, sem evidência de encerramento
    encerrada = "encerrada"        # evidência explícita (prazo de inscrição vencido)


APPLICATION_STATUSES = [
    "nova", "salva", "revisar_curriculo", "candidatado", "entrevista", "recusada", "encerrada",
]


class RawJob(BaseModel):
    """Registro de uma fonte já mapeado para nomes comuns, mas ainda não normalizado."""

    source: str
    source_job_id: str | None = None
    url: str
    title: str = Field(min_length=2)
    company: str | None = None
    location_raw: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    modality_raw: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    description: str | None = None    # texto plano (HTML já removido pelo coletor)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("url ausente ou inválida")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("published_at", "deadline_at")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

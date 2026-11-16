"""Leitura do perfil profissional (privado), validada por Pydantic.

Formato v2 (Etapa 3): vários OBJETIVOS profissionais, cada um com análise e score próprios —
requisitos de cargos diferentes não se misturam numa pontuação só. O formato antigo, com um único
`objetivo`, continua aceito e vira o objetivo `principal`.

As competências (com nível e evidências) são suas, não do objetivo: o mesmo conhecimento vale para
qualquer cargo. O que muda por objetivo são as vagas-alvo (famílias, senioridades, modalidade, local).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..models import Familia, Modalidade, Senioridade

NIVEIS = ("profissional", "projeto", "em_desenvolvimento", "nao_dominada")
Nivel = Literal["profissional", "projeto", "em_desenvolvimento", "nao_dominada"]


class LocaisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ufs: list[str] = Field(default_factory=list)
    cidades: list[str] = Field(default_factory=list)


class ObjetivoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="principal", pattern=r"^[a-z][a-z0-9_]*$")
    nome: str = ""
    familias: list[Familia] = Field(default_factory=list)
    senioridades: list[Senioridade] = Field(default_factory=list)
    modalidades: list[Modalidade] = Field(default_factory=list)
    locais: LocaisConfig = Field(default_factory=LocaisConfig)


class CompetenciaPerfil(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    nivel: Nivel
    evidencias: list[str] = Field(default_factory=list)
    inicio: date | str | None = None
    conclusao: date | str | None = None


class PerfilConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objetivo: ObjetivoConfig | None = None            # formato antigo (um objetivo)
    objetivos: list[ObjetivoConfig] = Field(default_factory=list)
    competencias: list[CompetenciaPerfil] = Field(default_factory=list)

    @model_validator(mode="after")
    def _um_formato(self) -> "PerfilConfig":
        if self.objetivo and self.objetivos:
            raise ValueError("use `objetivos` (lista) OU `objetivo` (formato antigo), não os dois")
        if self.objetivo:
            self.objetivos = [self.objetivo.model_copy(update={"id": self.objetivo.id or "principal"})]
            self.objetivo = None
        ids = [o.id for o in self.objetivos]
        if len(ids) != len(set(ids)):
            raise ValueError(f"ids de objetivo repetidos: {ids}")
        skills = [c.skill for c in self.competencias]
        if len(skills) != len(set(skills)):
            raise ValueError("competência repetida no perfil")
        return self


@dataclass(frozen=True)
class Objetivo:
    id: str
    nome: str
    familias: tuple[str, ...] = ()
    senioridades: tuple[str, ...] = ()
    modalidades: tuple[str, ...] = ()
    ufs: tuple[str, ...] = ()
    cidades: tuple[str, ...] = ()


@dataclass
class Profile:
    niveis: dict[str, str] = field(default_factory=dict)        # skill_id → nível
    evidencias: dict[str, list[str]] = field(default_factory=dict)
    objetivos: list[Objetivo] = field(default_factory=list)
    # Campos do objetivo ATIVO (o primeiro, ou o escolhido em `para`). Score e recomendações leem estes.
    objetivo_id: str = ""
    familias: list[str] = field(default_factory=list)
    senioridades: list[str] = field(default_factory=list)
    modalidades: list[str] = field(default_factory=list)
    ufs: list[str] = field(default_factory=list)
    cidades: list[str] = field(default_factory=list)
    vazio: bool = True
    hash: str = ""

    def nivel(self, skill_id: str) -> str:
        return self.niveis.get(skill_id, "sem_evidencia")

    def para(self, objetivo_id: str) -> "Profile":
        """O mesmo perfil, com o objetivo `objetivo_id` ativo."""
        o = next((x for x in self.objetivos if x.id == objetivo_id), None)
        if o is None:
            raise KeyError(f"objetivo desconhecido: {objetivo_id} (há: {', '.join(x.id for x in self.objetivos)})")
        return replace(self, objetivo_id=o.id, familias=list(o.familias), senioridades=list(o.senioridades),
                       modalidades=list(o.modalidades), ufs=list(o.ufs), cidades=list(o.cidades))

    def por_objetivo(self) -> list["Profile"]:
        """Um perfil por objetivo: cada um com análise independente."""
        return [self.para(o.id) for o in self.objetivos] if self.objetivos else [self]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        if not d:
            return cls()
        try:
            cfg = PerfilConfig.model_validate(d)
        except ValidationError as e:
            raise ValueError(f"perfil inválido: {e}") from e
        objetivos = [Objetivo(o.id, o.nome or o.id, tuple(f.value for f in o.familias),
                              tuple(s.value for s in o.senioridades), tuple(m.value for m in o.modalidades),
                              tuple(u.upper() for u in o.locais.ufs), tuple(str(c).lower() for c in o.locais.cidades))
                     for o in cfg.objetivos] or [Objetivo("principal", "principal")]
        base = cls(
            niveis={c.skill: c.nivel for c in cfg.competencias},
            evidencias={c.skill: [str(e) for e in c.evidencias] for c in cfg.competencias},
            objetivos=objetivos, vazio=False,
            hash=hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12],
        )
        return base.para(objetivos[0].id)

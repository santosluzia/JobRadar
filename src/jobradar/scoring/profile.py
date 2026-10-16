"""Leitura do perfil profissional (privado)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

NIVEIS = ("profissional", "projeto", "em_desenvolvimento", "nao_dominada")


@dataclass
class Profile:
    niveis: dict[str, str] = field(default_factory=dict)        # skill_id → nível
    evidencias: dict[str, list[str]] = field(default_factory=dict)
    familias: list[str] = field(default_factory=list)
    senioridades: list[str] = field(default_factory=list)
    modalidades: list[str] = field(default_factory=list)
    ufs: list[str] = field(default_factory=list)
    cidades: list[str] = field(default_factory=list)
    vazio: bool = True
    hash: str = ""

    def nivel(self, skill_id: str) -> str:
        return self.niveis.get(skill_id, "sem_evidencia")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        if not d:
            return cls()
        niveis, evid = {}, {}
        for c in d.get("competencias") or []:
            nivel = c.get("nivel")
            if nivel not in NIVEIS:
                raise ValueError(f"nível inválido para {c.get('skill')}: {nivel} (use {', '.join(NIVEIS)})")
            niveis[c["skill"]] = nivel
            evid[c["skill"]] = [str(e) for e in c.get("evidencias") or []]
        obj = d.get("objetivo") or {}
        locais = obj.get("locais") or {}
        return cls(
            niveis=niveis, evidencias=evid,
            familias=obj.get("familias") or [], senioridades=obj.get("senioridades") or [],
            modalidades=obj.get("modalidades") or [],
            ufs=[u.upper() for u in locais.get("ufs") or []],
            cidades=[str(c).lower() for c in locais.get("cidades") or []],
            vazio=False,
            hash=hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12],
        )

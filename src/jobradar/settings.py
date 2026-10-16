"""Configuração: YAMLs em config/ + variáveis de ambiente. Nenhum segredo vive em arquivo versionado."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def _yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    sources: dict[str, Any]
    skills: dict[str, Any]
    scoring: dict[str, Any]
    profile: dict[str, Any]
    profile_path: Path | None
    lake: Path

    def env(self, nome: str) -> str | None:
        valor = os.getenv(nome)
        return valor.strip() if valor and valor.strip() else None

    def fonte(self, nome: str) -> dict[str, Any]:
        return self.sources.get("fontes", {}).get(nome, {}) or {}

    @property
    def termos(self) -> list[str]:
        return self.sources["busca"]["termos"]

    @property
    def filtros(self) -> dict[str, Any]:
        return self.sources.get("filtros", {})

    @property
    def retencao(self) -> dict[str, Any]:
        return self.sources.get("retencao", {})


def resolver_perfil(lake: Path, config_dir: Path) -> Path | None:
    """Ordem: $JOBRADAR_PROFILE → <lake>/private/profile.yaml → config/profile.yaml → nenhum."""
    candidatos = [os.getenv("JOBRADAR_PROFILE"), lake / "private" / "profile.yaml", config_dir / "profile.yaml"]
    for c in candidatos:
        if c and Path(c).exists():
            return Path(c)
    return None


def carregar(lake: str | Path | None = None, config_dir: str | Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    cdir = Path(config_dir or os.getenv("JOBRADAR_CONFIG_DIR", CONFIG_DIR))
    lake_path = Path(lake or os.getenv("JOBRADAR_LAKE", ROOT / "lake")).resolve()
    perfil_path = resolver_perfil(lake_path, cdir)
    return Settings(
        sources=_yaml(cdir / "sources.yaml"),
        skills=_yaml(cdir / "skills.yaml"),
        scoring=_yaml(cdir / "scoring.yaml"),
        profile=_yaml(perfil_path) if perfil_path else {},
        profile_path=perfil_path,
        lake=lake_path,
    )

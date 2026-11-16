"""Pasta privada LOCAL ($JOBRADAR_HOME, padrão ~/.jobradar): currículo, diagnósticos e planos.

Fica fora de qualquer repositório git — e se recusa a ficar dentro de um (o workflow grava o lake
com `git add -A`; dentro do `jobradar-data` o conteúdo iria para o histórico do git).
"""
from __future__ import annotations

import os
from pathlib import Path


class PastaInsegura(RuntimeError):
    pass


def _dentro_de_git(p: Path) -> Path | None:
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return d
    return None


def pasta_privada(sub: str, home: Path | None = None) -> Path:
    base = Path(home or os.getenv("JOBRADAR_HOME") or Path.home() / ".jobradar").resolve()
    repo = _dentro_de_git(base)
    if repo is not None:
        raise PastaInsegura(f"{base} está dentro do repositório git {repo}: os dados iriam para o histórico. "
                            "Use uma pasta fora de qualquer repositório (padrão: ~/.jobradar).")
    raiz = base / sub
    raiz.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)       # POSIX: só o dono lê. No Windows, vale a permissão do perfil.
    except OSError:
        pass
    return raiz

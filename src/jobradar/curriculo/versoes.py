"""Versões do currículo e histórico de diagnósticos — LOCAIS, fora de qualquer repositório git.

Pasta: `$JOBRADAR_HOME` (padrão `~/.jobradar`) → `curriculo/versoes/*.json`, `curriculo/diagnosticos/*.json`
e, só se você pedir, `curriculo/originais/`. Por isso:
- nada disto vai para o `jobradar-data` (que o workflow grava com `git add -A`), para o CI ou para o público;
- apagar uma versão apaga de verdade (não sobra no histórico do git).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..privado import PastaInsegura, pasta_privada  # noqa: F401
from .estrutura import Curriculo

_ID = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}$")


def pasta(home: Path | None = None) -> Path:
    """Pasta do currículo dentro da pasta privada (recusa ficar dentro de um repositório git)."""
    raiz = pasta_privada("curriculo", home)
    for sub in ("versoes", "diagnosticos"):
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    return raiz


def _arquivo(raiz: Path, versao_id: str) -> Path:
    if not _ID.match(versao_id):           # nunca monta caminho a partir de texto arbitrário
        raise ValueError(f"id de versão inválido: {versao_id!r}")
    return raiz / "versoes" / f"{versao_id}.json"


def _gravar(caminho: Path, conteudo: str) -> None:
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    os.replace(tmp, caminho)


def salvar(cv: Curriculo, home: Path | None = None, original: bytes | None = None) -> Path:
    raiz = pasta(home)
    destino = _arquivo(raiz, cv.versao_id)
    _gravar(destino, cv.model_dump_json(indent=2))
    if original is not None:
        (raiz / "originais").mkdir(exist_ok=True)
        ext = {"pdf": ".pdf", "docx": ".docx"}.get(cv.origem.get("tipo", ""), ".txt")
        (raiz / "originais" / f"{cv.versao_id}{ext}").write_bytes(original)
    return destino


def carregar(versao_id: str | None = None, home: Path | None = None) -> Curriculo | None:
    """Versão pedida, ou a mais recente."""
    raiz = pasta(home)
    if versao_id is None:
        ids = listar(home)
        if not ids:
            return None
        versao_id = ids[-1]["versao_id"]
    arq = _arquivo(raiz, versao_id)
    return Curriculo.model_validate_json(arq.read_text(encoding="utf-8")) if arq.exists() else None


def listar(home: Path | None = None) -> list[dict[str, Any]]:
    saida = []
    for arq in sorted(pasta(home).glob("versoes/*.json")):
        cv = Curriculo.model_validate_json(arq.read_text(encoding="utf-8"))
        saida.append({"versao_id": cv.versao_id, "criado_em": cv.criado_em, "nota": cv.nota,
                      "arquivo": cv.origem.get("nome", ""), "experiencias": len(cv.experiencias),
                      "competencias": len(cv.niveis())})
    return sorted(saida, key=lambda v: (v["criado_em"], v["versao_id"]))


def apagar(versao_id: str | None = None, home: Path | None = None, tudo: bool = False) -> int:
    """Apaga uma versão (com o original e os diagnósticos dela) ou, com `tudo`, toda a pasta de currículo."""
    raiz = pasta(home)
    alvos = list(raiz.rglob("*")) if tudo else (
        [_arquivo(raiz, versao_id)] + list(raiz.glob(f"originais/{versao_id}.*"))
        + list(raiz.glob(f"diagnosticos/*_{versao_id}_*.json")))
    n = 0
    for a in sorted(alvos, key=lambda p: len(p.parts), reverse=True):
        if a.is_file():
            a.unlink()
            n += 1
        elif tudo and a.is_dir():
            a.rmdir()
    return n


def salvar_diagnostico(diag: dict[str, Any], home: Path | None = None) -> Path:
    raiz = pasta(home)
    nome = f"{diag['gerado_em'][:19].replace(':', '').replace('-', '')}_{diag['versao_id'] or 'sem-cv'}_{diag['objetivo_id']}.json"
    destino = raiz / "diagnosticos" / re.sub(r"[^\w.-]", "_", nome)
    _gravar(destino, json.dumps(diag, ensure_ascii=False, indent=2, default=str))
    return destino


def historico(home: Path | None = None, objetivo_id: str | None = None) -> list[dict[str, Any]]:
    saida = []
    for arq in sorted(pasta(home).glob("diagnosticos/*.json")):
        d = json.loads(arq.read_text(encoding="utf-8"))
        if objetivo_id is None or d.get("objetivo_id") == objetivo_id:
            saida.append(d)
    return saida


def comparar(a: Curriculo, b: Curriculo) -> dict[str, Any]:
    """O que mudou de `a` (antiga) para `b` (nova): experiências e competências demonstradas."""
    chave = lambda e: f"{e.cargo} · {e.empresa}".strip(" ·")  # noqa: E731
    ea, eb = {chave(e): e for e in a.experiencias}, {chave(e): e for e in b.experiencias}
    alteradas = [k for k in ea.keys() & eb.keys()
                 if ea[k].model_dump(exclude={"competencias", "editados"}) != eb[k].model_dump(exclude={"competencias", "editados"})]
    na, nb = a.niveis(), b.niveis()
    return {
        "de": a.versao_id, "para": b.versao_id,
        "experiencias_novas": sorted(eb.keys() - ea.keys()),
        "experiencias_removidas": sorted(ea.keys() - eb.keys()),
        "experiencias_alteradas": sorted(alteradas),
        "competencias_novas": {k: nb[k] for k in sorted(nb.keys() - na.keys())},
        "competencias_removidas": {k: na[k] for k in sorted(na.keys() - nb.keys())},
        "competencias_mudaram_de_nivel": {k: [na[k], nb[k]] for k in sorted(na.keys() & nb.keys()) if na[k] != nb[k]},
        "projetos": [len(a.projetos), len(b.projetos)],
        "certificacoes": [len(a.certificacoes), len(b.certificacoes)],
    }

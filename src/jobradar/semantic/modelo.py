"""Modelo de embeddings LOCAL: baixado uma vez, por revisão fixa, e conferido por SHA-256.

- Só código aberto (model2vec, licença MIT; modelo potion-multilingual-128M, licença MIT).
- O download é do arquivo público do modelo; NENHUM texto de vaga ou dado pessoal sai da máquina:
  a codificação roda localmente, na CPU.
- Arquivo com hash diferente do esperado → erro (não usa modelo adulterado ou trocado).
- Dependência opcional: `pip install -e ".[semantica]"`. Sem ela, a camada fica indisponível
  e o resto do JobRadar funciona igual (a camada é desligada por padrão).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from ..transformations.skills import SemanticaConfig
from .extrator import Codificador


class ModeloInvalido(RuntimeError):
    pass


def pasta_cache() -> Path:
    return Path(os.getenv("JOBRADAR_MODEL_CACHE") or Path.home() / ".cache" / "jobradar" / "modelos")


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def conferir(pasta: Path, esperado: dict[str, str]) -> None:
    for nome, sha in esperado.items():
        arq = pasta / nome
        if not arq.exists():
            raise ModeloInvalido(f"arquivo do modelo ausente: {arq}")
        obtido = _sha256(arq)
        if obtido != sha:
            raise ModeloInvalido(f"hash diferente em {nome}: esperado {sha[:12]}…, obtido {obtido[:12]}…")


def baixar(cfg: SemanticaConfig, cache: Path | None = None) -> Path:
    """Pasta local com os arquivos do modelo na revisão fixa, já conferidos."""
    destino = (cache or pasta_cache()) / cfg.modelo.replace("/", "--") / cfg.revisao
    try:
        conferir(destino, cfg.sha256)
        return destino                      # já baixado e íntegro: nenhuma requisição
    except ModeloInvalido:
        pass
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:  # pragma: no cover - depende do ambiente
        raise ModeloInvalido('camada semântica requer: pip install -e ".[semantica]"') from e
    snapshot_download(repo_id=cfg.modelo, revision=cfg.revisao, allow_patterns=sorted(cfg.sha256),
                      local_dir=destino)
    conferir(destino, cfg.sha256)
    return destino


def carregar_codificador(cfg: SemanticaConfig, cache: Path | None = None) -> Codificador:
    pasta = baixar(cfg, cache)
    try:
        from model2vec import StaticModel
    except ImportError as e:  # pragma: no cover
        raise ModeloInvalido('camada semântica requer: pip install -e ".[semantica]"') from e
    modelo = StaticModel.from_pretrained(pasta)   # caminho local: não consulta a rede

    def codificar(textos: list[str]) -> np.ndarray:
        return modelo.encode(textos, use_multiprocessing=False)
    return codificar

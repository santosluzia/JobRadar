"""Retenção e apagamento dos dados pessoais (Etapa 8, docs/privacidade.md).

Na pasta privada LOCAL ($JOBRADAR_HOME, padrão ~/.jobradar):
- currículo: guarda as N versões mais recentes (padrão 12) — as mais antigas saem com o original e os
  diagnósticos delas;
- diagnósticos do currículo e planos de evolução salvos: guardados por M meses (padrão 24).
A regra roda a cada importação de currículo e por `jobradar privacidade limpar`.

`apagar_tudo` remove a pasta privada local inteira e o resumo do currículo (com o histórico de resumos)
do lake. Perfil, progresso de estudo e registros de e-mail ficam: são configuração e histórico que você
mantém no repositório privado (veja docs/privacidade.md para apagá-los também, inclusive do histórico do git).
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .privado import pasta_privada

PADRAO = {"max_versoes_curriculo": 12, "meses_diagnosticos": 24}
_DATA_NO_NOME = re.compile(r"^(\d{8})T")


def _config(cfg: dict[str, Any] | None) -> dict[str, int]:
    c = {**PADRAO, **{k: v for k, v in (cfg or {}).items() if k in PADRAO and v is not None}}
    if c["max_versoes_curriculo"] < 1 or c["meses_diagnosticos"] < 1:
        raise ValueError("retenção: os limites precisam ser ≥ 1")
    return {k: int(v) for k, v in c.items()}


def _antigo(arq: Path, limite: datetime) -> bool:
    """Data pelo prefixo do nome (AAAAMMDDTHHMMSS, gravado pelo JobRadar); sem prefixo, nunca apaga."""
    m = _DATA_NO_NOME.match(arq.name)
    if not m:
        return False
    return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc) < limite


def limpar(home: Path | None = None, cfg: dict[str, Any] | None = None,
           agora: datetime | None = None) -> dict[str, int]:
    from .curriculo import versoes
    c = _config(cfg)
    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(days=round(c["meses_diagnosticos"] * 30.44))
    saida = {"versoes_curriculo": 0, "arquivos_curriculo": 0, "diagnosticos": 0, "planos": 0}

    todas = versoes.listar(home)
    for v in todas[: max(0, len(todas) - c["max_versoes_curriculo"])]:
        saida["arquivos_curriculo"] += versoes.apagar(v["versao_id"], home)
        saida["versoes_curriculo"] += 1
    for arq in versoes.pasta(home).glob("diagnosticos/*.json"):
        if _antigo(arq, limite):
            arq.unlink()
            saida["diagnosticos"] += 1
    for arq in pasta_privada("evolucao", home).glob("*.json"):
        if _antigo(arq, limite):
            arq.unlink()
            saida["planos"] += 1
    return saida


def apagar_tudo(lake_root: Path | None, home: Path | None = None) -> dict[str, Any]:
    """Remove a pasta privada local inteira e o resumo do currículo no lake. Não tem volta."""
    from .evolucao import resumo_cv
    base = pasta_privada("", home)          # mesma checagem: recusa pasta dentro de repositório git
    arquivos = sum(1 for p in base.rglob("*") if p.is_file())
    shutil.rmtree(base, ignore_errors=False)
    resumo = resumo_cv.remover(Path(lake_root)) if lake_root else False
    return {"pasta": str(base), "arquivos_locais": arquivos, "resumo_no_lake": resumo}

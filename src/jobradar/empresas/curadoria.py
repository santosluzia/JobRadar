"""Fila de curadoria: as empresas `status: candidata` do catálogo (ADR 0012).

Edita `config/empresas.yaml` como TEXTO, uma entrada por vez, para preservar os comentários e o formato
do arquivo (um dump do YAML inteiro apagaria os comentários). Toda alteração é validada com o catálogo
inteiro antes de gravar: se o resultado for inválido, o arquivo não muda.

- `adicionar_candidata`: acrescenta a empresa no fim do arquivo, com `status: candidata` e
  `origem: descoberta`. Candidata não entra na coleta.
- `aprovar`: `candidata`/`pausada` → `ativa`, com `verificada_em` = data da verificação usada.
- `descartar`: → `descartada`, com o motivo em `observacoes` (fica registrado para não ser sugerida de novo).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .catalogo import Catalogo, Empresa, carregar_catalogo

ORDEM = ["id", "nome", "pais", "segmento", "site", "pagina_carreiras", "ats", "board", "status", "verificada_em",
         "origem", "nome_fixo", "observacoes"]
CABECALHO_CANDIDATAS = "  # ------------------------------------------------------------ Candidatas (descoberta assistida)"
LARGURA = 112


class CuradoriaErro(ValueError):
    pass


def _valor(v: Any) -> str:
    """Valor escrito como o YAML o escreveria DENTRO de `{...}`: dumpar numa lista em estilo flow faz o
    YAML pôr aspas quando o texto tem vírgula, chaves ou dois-pontos."""
    texto = yaml.safe_dump([v], default_flow_style=True, allow_unicode=True, width=10**6).strip()
    return texto[1:-1]


def formatar(dados: dict[str, Any]) -> str:
    """Entrada no estilo do arquivo: `  - {id: x, nome: X, ...}`, quebrando a linha antes de passar da
    largura (continuação alinhada com a chave, como nas entradas escritas à mão)."""
    pares = [f"{k}: {_valor(dados[k])}" for k in ORDEM if k in dados and dados[k] is not None]
    linhas, atual = [], "  - {"
    for i, par in enumerate(pares):
        trecho = par + ("," if i < len(pares) - 1 else "}")
        if len(atual) + len(trecho) + 1 > LARGURA and not atual.endswith("{"):
            linhas.append(atual.rstrip())
            atual = "     "
        atual += trecho if atual.endswith(("{", "     ")) else " " + trecho
    linhas.append(atual)
    return "\n".join(linhas)


def _validar(texto: str) -> Catalogo:
    try:
        return carregar_catalogo(yaml.safe_load(texto))
    except Exception as e:   # YAML ou Pydantic: o arquivo não é gravado
        raise CuradoriaErro(f"o catálogo ficaria inválido, nada foi gravado: {e}") from e


def _gravar(caminho: Path, texto: str) -> Catalogo:
    cat = _validar(texto)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    tmp.replace(caminho)
    return cat


def adicionar_candidata(caminho: Path, empresa: Empresa) -> Catalogo:
    if empresa.status != "candidata":
        raise CuradoriaErro("a descoberta só inclui empresas como candidata; a ativação é pelo comando aprovar")
    texto = caminho.read_text(encoding="utf-8")
    atual = _validar(texto)
    if any(e.id == empresa.id for e in atual.empresas):
        raise CuradoriaErro(f"já existe empresa com id '{empresa.id}' no catálogo")
    if empresa.board and atual.por_quadro(empresa.ats, empresa.board):
        raise CuradoriaErro(f"o quadro {empresa.ats}/{empresa.board} já está no catálogo")
    texto = re.sub(r"(?m)^empresas:\s*\[\]\s*$", "empresas:", texto)
    if not re.search(r"(?m)^empresas:\s*$", texto):
        raise CuradoriaErro("não achei a lista 'empresas:' no arquivo")
    bloco = formatar(empresa.model_dump() | {"nome_fixo": empresa.nome_fixo or None})   # False não vai ao arquivo
    if CABECALHO_CANDIDATAS not in texto:
        bloco = f"\n{CABECALHO_CANDIDATAS}\n{bloco}"
    return _gravar(caminho, texto.rstrip("\n") + "\n" + bloco + "\n")


def _localizar(linhas: list[str], id_: str) -> tuple[int, int]:
    """Primeira e última linha da entrada `- {id: <id>, ...}` (a entrada termina na linha com `}`)."""
    inicio = re.compile(r"^\s*-\s*\{\s*id:\s*['\"]?" + re.escape(id_) + r"['\"]?\s*,")
    for i, linha in enumerate(linhas):
        if inicio.match(linha):
            for j in range(i, len(linhas)):
                if linhas[j].split("#", 1)[0].rstrip().endswith("}"):
                    return i, j
            break
    raise CuradoriaErro(f"empresa '{id_}' não encontrada no catálogo (ou fora do formato `- {{id: ..., ...}}`)")


def alterar(caminho: Path, id_: str, **campos: Any) -> Catalogo:
    texto = caminho.read_text(encoding="utf-8")
    linhas = texto.split("\n")
    i, j = _localizar(linhas, id_)
    atual = yaml.safe_load("\n".join(linhas[i:j + 1]).strip().removeprefix("-").strip())
    novo = {**atual, **campos}
    linhas[i:j + 1] = formatar({k: v for k, v in novo.items() if v is not None}).split("\n")
    return _gravar(caminho, "\n".join(linhas))


def aprovar(caminho: Path, empresa: Empresa, verificada_em: date, nota: str | None = None) -> Catalogo:
    """`nota`: registrada em observacoes (ex.: aprovação forçada com pendências)."""
    if empresa.status not in ("candidata", "pausada"):
        raise CuradoriaErro(f"'{empresa.id}' está com status {empresa.status}; só candidata ou pausada é aprovada")
    extra = {}
    if nota:
        extra["observacoes"] = f"{empresa.observacoes} | {nota}" if empresa.observacoes else nota
    return alterar(caminho, empresa.id, status="ativa", verificada_em=verificada_em, **extra)


def descartar(caminho: Path, empresa: Empresa, motivo: str, hoje: date) -> Catalogo:
    if not motivo.strip():
        raise CuradoriaErro("informe o motivo do descarte (--motivo)")
    nota = f"descartada em {hoje.isoformat()}: {motivo.strip()}"
    obs = f"{empresa.observacoes} | {nota}" if empresa.observacoes else nota
    return alterar(caminho, empresa.id, status="descartada", observacoes=obs)

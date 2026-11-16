"""Resumo do currículo para o CI (Etapa 5), SÓ POR ADESÃO: competência → nível de evidência.

O currículo vive só na sua máquina (~/.jobradar). Para o Radar diário — que roda no CI — saber o que o
currículo demonstra, `jobradar curriculo compartilhar-resumo` grava em `<lake>/private/curriculo_resumo.json`
APENAS: versão, data, versão da taxonomia e {skill_id: nível}. Nada de texto, empresa, cargo, frase,
período ou contato. `jobradar curriculo remover-resumo` apaga.

O objeto carregado imita a interface mínima de `Curriculo` usada pelo diagnóstico/plano
(niveis, evidencias, experiencias, versao_id), sem nenhum conteúdo textual.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CAMINHO = Path("private") / "curriculo_resumo.json"
HISTORICO = Path("private") / "curriculo_resumos_historico.json"   # Etapa 6: um resumo por versão (só níveis)
NIVEIS_VALIDOS = {"comprovada", "projeto", "declarada", "parcial"}


@dataclass
class ResumoCurriculo:
    versao_id: str
    gerado_em: str
    taxonomia_versao: str
    _niveis: dict[str, str]
    experiencias: list = field(default_factory=list)
    projetos: list = field(default_factory=list)
    certificacoes: list = field(default_factory=list)
    competencias_declaradas: list = field(default_factory=list)

    def niveis(self) -> dict[str, str]:
        return dict(self._niveis)

    def evidencias(self) -> dict[str, list]:
        return {}            # o resumo não carrega frases do currículo, de propósito


def gravar(lake_root: Path, versao_id: str, gerado_em: str, taxonomia_versao: str, niveis: dict[str, str]) -> Path:
    invalidos = {k: v for k, v in niveis.items() if v not in NIVEIS_VALIDOS}
    if invalidos:
        raise ValueError(f"níveis inválidos no resumo: {invalidos}")
    destino = Path(lake_root) / CAMINHO
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo: dict[str, Any] = {"versao_id": versao_id, "gerado_em": gerado_em, "taxonomia_versao": taxonomia_versao,
                                "niveis": dict(sorted(niveis.items()))}
    destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    hist = [h for h in historico(lake_root) if h["versao_id"] != versao_id] + [conteudo]
    (Path(lake_root) / HISTORICO).write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def historico(lake_root: Path) -> list[dict[str, Any]]:
    """Resumos compartilhados, do mais antigo ao mais novo (cada um: versão, data e níveis)."""
    p = Path(lake_root) / HISTORICO
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def comparar_niveis(antes: dict[str, str], depois: dict[str, str]) -> dict[str, Any]:
    ordem = {"parcial": 1, "declarada": 2, "projeto": 3, "comprovada": 4}
    mudou = {k: [antes[k], depois[k]] for k in sorted(antes.keys() & depois.keys()) if antes[k] != depois[k]}
    return {"novas": {k: depois[k] for k in sorted(depois.keys() - antes.keys())},
            "removidas": {k: antes[k] for k in sorted(antes.keys() - depois.keys())},
            "subiram": {k: v for k, v in mudou.items() if ordem[v[1]] > ordem[v[0]]},
            "desceram": {k: v for k, v in mudou.items() if ordem[v[1]] < ordem[v[0]]}}


def carregar(lake_root: Path) -> ResumoCurriculo | None:
    p = Path(lake_root) / CAMINHO
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    niveis = {k: v for k, v in (d.get("niveis") or {}).items() if v in NIVEIS_VALIDOS}
    return ResumoCurriculo(str(d.get("versao_id", "")), str(d.get("gerado_em", "")), str(d.get("taxonomia_versao", "")),
                           niveis)


def remover(lake_root: Path) -> bool:
    """Apaga o resumo atual E o histórico de resumos."""
    removeu = False
    for rel in (CAMINHO, HISTORICO):
        p = Path(lake_root) / rel
        if p.exists():
            p.unlink()
            removeu = True
    return removeu

"""Extração de competências a partir de título e descrição, com taxonomia configurável.

Heurística de importância (documentada como heurística, não como verdade):
- aparece no título ou numa seção comum → "requisito";
- aparece só depois de um marcador de "desejável/diferencial" → "desejavel".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .text import normalizar


@dataclass(frozen=True)
class Skill:
    id: str
    nome: str
    categoria: str
    padroes: tuple[re.Pattern, ...]
    esforco: str
    projeto: bool


@dataclass(frozen=True)
class SkillMatch:
    skill_id: str
    importancia: str   # requisito | desejavel
    termo: str         # trecho que casou (evidência da extração)


class Taxonomy:
    def __init__(self, cfg: dict[str, Any]):
        self.skills = [
            Skill(s["id"], s["nome"], s["categoria"], tuple(re.compile(p) for p in s["padroes"]),
                  s.get("esforco", "medio"), bool(s.get("projeto", True)))
            for s in cfg["competencias"]
        ]
        self.por_id = {s.id: s for s in self.skills}
        self._desejavel = re.compile("|".join(cfg.get("marcadores_desejavel", [])) or r"$^")
        self._requisito = re.compile("|".join(cfg.get("marcadores_requisito", [])) or r"$^")

    def _secoes(self, titulo: str, descricao: str | None) -> list[tuple[str, str]]:
        secoes = [("requisito", normalizar(titulo))]
        modo = "requisito"
        for linha in (descricao or "").splitlines():
            n = normalizar(linha)
            if not n:
                continue
            curto = len(n) <= 60  # marcadores costumam ser cabeçalhos curtos
            if self._desejavel.search(n) and (curto or n.endswith(":")):
                modo = "desejavel"
            elif self._requisito.search(n) and (curto or n.endswith(":")):
                modo = "requisito"
            elif self._desejavel.search(n):  # "Inglês é um diferencial" na própria linha
                secoes.append(("desejavel", n))
                continue
            secoes.append((modo, n))
        return secoes

    def extrair(self, titulo: str, descricao: str | None) -> list[SkillMatch]:
        secoes = self._secoes(titulo, descricao)
        achados: dict[str, SkillMatch] = {}
        for skill in self.skills:
            for modo, texto in secoes:
                for p in skill.padroes:
                    m = p.search(texto)
                    if not m:
                        continue
                    atual = achados.get(skill.id)
                    if atual is None or (atual.importancia == "desejavel" and modo == "requisito"):
                        achados[skill.id] = SkillMatch(skill.id, modo, m.group(0))
                    break
                if achados.get(skill.id, None) and achados[skill.id].importancia == "requisito":
                    break
        return sorted(achados.values(), key=lambda a: a.skill_id)

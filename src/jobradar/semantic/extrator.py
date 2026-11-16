"""Achados por similaridade de embeddings: frase da vaga × frases-âncora da taxonomia.

Só complementa as regras: roda para as competências que as regras NÃO acharam na vaga, só
com as competências que têm `descricoes` (âncoras) e só nas frases que não são contexto.
Cada achado guarda a frase de evidência, a similaridade e o limiar usado.

O codificador é qualquer função `list[str] -> matriz (n, d)`; quem carrega o modelo é
`semantic.modelo` (local, revisão fixa, hash conferido). Nada aqui faz chamada de rede.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..transformations.skills import Taxonomy, recortar

Codificador = Callable[[list[str]], np.ndarray]
MAX_FRASES = 400          # teto por vaga (descrição limitada a 20 mil caracteres na ingestão)
MIN_CARACTERES = 12       # frase curta demais ("Python;") já é coberta pelas regras


@dataclass(frozen=True)
class AchadoSemantico:
    skill_id: str
    importancia: str
    evidencia: str
    similaridade: float
    confianca: str        # media | baixa
    tipo: str


def _normalizar_linhas(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(n == 0, 1, n)


class ExtratorSemantico:
    def __init__(self, tax: Taxonomy, codificar: Codificador, limiar: float, limiar_media: float,
                 tipos: tuple[str, ...] = ("tecnica",)):
        self.tax, self.codificar = tax, codificar
        self.limiar, self.limiar_media = limiar, limiar_media
        ancoras, donos = [], []
        for s in tax.todas:
            if s.tipo in tipos and s.descricoes:
                ancoras += list(s.descricoes)
                donos += [s.id] * len(s.descricoes)
        self.donos = np.array(donos)
        self.skills = sorted(set(donos))
        self.ancoras = _normalizar_linhas(codificar(ancoras)) if ancoras else np.zeros((0, 1), np.float32)

    def extrair(self, titulo: str, descricao: str | None, ja_achadas: set[str]) -> list[AchadoSemantico]:
        alvo = [s for s in self.skills if s not in ja_achadas]
        # [1:] tira o título: nome de cargo ("Analista de Dados") parece com tudo e não é evidência.
        frases = [u for u in self.tax.unidades(titulo, descricao)[1:]
                  if u.modo != "contexto" and not u.formacao and len(u.norm) >= MIN_CARACTERES
                  and not u.norm.endswith(":")][:MAX_FRASES]   # cabeçalho ("Requisitos:") não é evidência
        if not alvo or not frases:
            return []
        sim = _normalizar_linhas(self.codificar([u.original for u in frases])) @ self.ancoras.T  # frases × âncoras
        achados = []
        for sid in alvo:
            col = sim[:, self.donos == sid].max(axis=1)        # melhor âncora da competência, por frase
            # Requisito vence desejável (como nas regras): primeiro olha só as frases de requisito.
            for modos in (("requisito",), ("requisito", "desejavel")):
                idx = [i for i, u in enumerate(frases) if u.modo in modos]
                if not idx:
                    continue
                i = max(idx, key=lambda k: col[k])
                if col[i] >= self.limiar:
                    u = frases[i]
                    achados.append(AchadoSemantico(
                        sid, u.modo, recortar(u.original, u.norm, 0, len(u.norm)), round(float(col[i]), 4),
                        "media" if col[i] >= self.limiar_media else "baixa", self.tax.por_id[sid].tipo))
                    break
        return achados

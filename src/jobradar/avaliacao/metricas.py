"""Precisão, revocação (recall) e F1 da extração contra o conjunto-ouro.

Micro-média: soma acertos (TP), falsos positivos (FP) e falsos negativos (FN) de todas as vagas.
Também quebra por tipo de texto (completo × trecho), por tipo de competência e por competência,
e guarda exemplos de erro para a análise — que é o que diz QUAL regra ajustar.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..transformations.skills import SkillMatch, Taxonomy
from .ouro import ItemOuro

Extrator = Callable[[ItemOuro], list[SkillMatch]]


@dataclass
class Contagem:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precisao(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precisao, self.recall
        return 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)


@dataclass
class Metricas:
    nome: str
    geral: Contagem = field(default_factory=Contagem)
    por_texto: dict[str, Contagem] = field(default_factory=lambda: defaultdict(Contagem))
    por_tipo: dict[str, Contagem] = field(default_factory=lambda: defaultdict(Contagem))
    por_skill: dict[str, Contagem] = field(default_factory=lambda: defaultdict(Contagem))
    por_metodo_fp: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    por_metodo_tp: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    importancia_ok: int = 0
    importancia_total: int = 0
    erros: list[dict] = field(default_factory=list)
    itens: int = 0
    rascunhos: int = 0


def avaliar(nome: str, itens: Iterable[ItemOuro], extrator: Extrator, tax: Taxonomy,
            tipos: tuple[str, ...] = ("tecnica",)) -> Metricas:
    """Compara o extrator com a anotação, só nas competências dos `tipos` pedidos."""
    m = Metricas(nome)
    tipo_de = {s.id: s.tipo for s in tax.todas}
    for item in itens:
        m.itens += 1
        m.rascunhos += 0 if item.revisado else 1
        ouro = {s for s in (item.competencias or []) if tipo_de.get(s, "tecnica") in tipos}
        achados = {a.skill_id: a for a in extrator(item) if tipo_de.get(a.skill_id, "tecnica") in tipos}
        texto = "completo" if item.completa else "trecho"
        for sid in ouro | set(achados):
            a = achados.get(sid)
            certo = sid in ouro
            tipo = tipo_de.get(sid, "tecnica")
            for c in (m.geral, m.por_texto[texto], m.por_tipo[tipo], m.por_skill[sid]):
                if a and certo:
                    c.tp += 1
                elif a:
                    c.fp += 1
                else:
                    c.fn += 1
            if a and certo:
                m.por_metodo_tp[a.metodo] += 1
                m.importancia_total += 1
                esperado = "desejavel" if sid in item.desejaveis else "requisito"
                m.importancia_ok += a.importancia == esperado
            elif a:
                m.por_metodo_fp[a.metodo] += 1
            if not (a and certo):
                m.erros.append({"tipo_erro": "FP" if a else "FN", "skill_id": sid, "job_id": item.job_id,
                                "texto": texto, "metodo": a.metodo if a else None,
                                "evidencia": a.evidencia if a else None})
    return m


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{100 * v:.1f}%"


def relatorio(resultados: list[Metricas], top_skills: int = 15) -> str:
    """Relatório em Markdown: só métricas agregadas e ids de competência (nada de texto de vaga)."""
    if not resultados:
        return "Nenhum resultado."
    r0 = resultados[0]
    linhas = [f"Itens avaliados: **{r0.itens}**" + (f" (⚠️ {r0.rascunhos} rascunho(s) não revisado(s))"
                                                    if r0.rascunhos else ""), "",
              "| Extrator | Precisão | Recall | F1 | TP | FP | FN | Importância correta |",
              "|---|---|---|---|---|---|---|---|"]
    for m in resultados:
        g = m.geral
        imp = _pct(m.importancia_ok / m.importancia_total) if m.importancia_total else "—"
        linhas.append(f"| {m.nome} | {_pct(g.precisao)} | {_pct(g.recall)} | {_pct(g.f1)} | {g.tp} | {g.fp} | {g.fn} | {imp} |")
    linhas += ["", "**Por tipo de texto** (completo = ATS; trecho = Adzuna, ~500 caracteres)", "",
               "| Extrator | Texto | Precisão | Recall | F1 |", "|---|---|---|---|---|"]
    for m in resultados:
        for t, c in sorted(m.por_texto.items()):
            linhas.append(f"| {m.nome} | {t} | {_pct(c.precisao)} | {_pct(c.recall)} | {_pct(c.f1)} |")
    linhas += ["", "**Achados por método** (acertos / falsos positivos)", "",
               "| Extrator | Método | TP | FP | Precisão |", "|---|---|---|---|---|"]
    for m in resultados:
        for met in sorted(set(m.por_metodo_tp) | set(m.por_metodo_fp)):
            tp, fp = m.por_metodo_tp.get(met, 0), m.por_metodo_fp.get(met, 0)
            linhas.append(f"| {m.nome} | {met} | {tp} | {fp} | {_pct(tp / (tp + fp) if tp + fp else None)} |")
    ult = resultados[-1]
    linhas += ["", f"**Por competência — {ult.nome}** (as {top_skills} com mais erros)", "",
               "| Competência | TP | FP | FN | Precisão | Recall |", "|---|---|---|---|---|---|"]
    for sid, c in sorted(ult.por_skill.items(), key=lambda kv: -(kv[1].fp + kv[1].fn))[:top_skills]:
        linhas.append(f"| {sid} | {c.tp} | {c.fp} | {c.fn} | {_pct(c.precisao)} | {_pct(c.recall)} |")
    return "\n".join(linhas)

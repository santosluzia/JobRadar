"""Medição da classificação do cargo contra o conjunto-ouro (ADR 0014).

- **Família:** acurácia e F1 macro sobre as famílias presentes no ouro (meta do roadmap: F1 ≥ 0,90),
  com precisão, recall e F1 por família e as confusões mais frequentes.
- **Subfamília:** acurácia, só nas vagas em que a família acertou (o erro de família já é contado acima).
- **Idioma da vaga:** acurácia (meta: ≥ 0,95).
- **Idiomas exigidos:** precisão e recall por idioma exigido; acerto de nível e de importância nos pares
  que casaram.

Sempre com n. Abaixo de `AMOSTRA_MIN` itens, o resultado sai marcado como amostra pequena.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..transformations import classificacao as cl
from ..transformations import normalize
from ..transformations.skills import Taxonomy
from .metricas import Contagem
from .ouro import ItemOuro

AMOSTRA_MIN = 30
META_FAMILIA_F1 = 0.90
META_IDIOMA = 0.95


@dataclass
class Previsao:
    familia: str
    subfamilia: str
    idioma_vaga: str
    idiomas: dict[str, cl.Exigencia]


def prever(item: ItemOuro, tax: Taxonomy) -> Previsao:
    """A classificação atual da vaga, como o pipeline faria (família pelas regras de título e competências)."""
    ids = {m.skill_id for m in tax.extrair(item.titulo, item.descricao) if m.tipo == "tecnica"}
    fam = normalize.familia(item.titulo, ids)[0].value
    c = cl.classificar(item.titulo, item.descricao, fam, tax, item.pais_iso)
    return Previsao(fam, c.subfamilia, c.idioma_vaga, {e.idioma: e for e in c.idiomas_exigidos})


@dataclass
class ResultadoClassificacao:
    n: int
    familia_acertos: int = 0
    por_familia: dict[str, Contagem] = field(default_factory=dict)
    confusoes: Counter = field(default_factory=Counter)
    subfamilia_n: int = 0
    subfamilia_acertos: int = 0
    idioma_acertos: int = 0
    exigencias: dict[str, Contagem] = field(default_factory=dict)
    nivel_n: int = 0
    nivel_acertos: int = 0
    importancia_acertos: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def amostra_pequena(self) -> bool:
        return self.n < AMOSTRA_MIN

    @property
    def familia_acuracia(self) -> float | None:
        return self.familia_acertos / self.n if self.n else None

    @property
    def familia_f1_macro(self) -> float | None:
        f1s = [c.f1 for c in self.por_familia.values() if c.f1 is not None]
        return sum(f1s) / len(f1s) if f1s else None

    @property
    def subfamilia_acuracia(self) -> float | None:
        return self.subfamilia_acertos / self.subfamilia_n if self.subfamilia_n else None

    @property
    def idioma_acuracia(self) -> float | None:
        return self.idioma_acertos / self.n if self.n else None


def medir(itens: list[ItemOuro], tax: Taxonomy) -> ResultadoClassificacao:
    r = ResultadoClassificacao(n=len(itens))
    for item in itens:
        ouro, p = item.classificacao, prever(item, tax)
        assert ouro is not None
        for fam in {ouro.familia, p.familia}:
            r.por_familia.setdefault(fam, Contagem())
        if p.familia == ouro.familia:
            r.familia_acertos += 1
            r.por_familia[ouro.familia].tp += 1
            r.subfamilia_n += 1
            if p.subfamilia == ouro.subfamilia:
                r.subfamilia_acertos += 1
            else:
                r.erros.append(f"subfamília {p.subfamilia} ≠ {ouro.subfamilia}: {item.titulo}")
        else:
            r.por_familia[p.familia].fp += 1
            r.por_familia[ouro.familia].fn += 1
            r.confusoes[(ouro.familia, p.familia)] += 1
            r.erros.append(f"família {p.familia} ≠ {ouro.familia}: {item.titulo}")
        if p.idioma_vaga == ouro.idioma_vaga:
            r.idioma_acertos += 1
        else:
            r.erros.append(f"idioma {p.idioma_vaga} ≠ {ouro.idioma_vaga}: {item.titulo}")
        esperados = {i.idioma: i for i in ouro.idiomas}
        for lingua in set(esperados) | set(p.idiomas):
            c = r.exigencias.setdefault(lingua, Contagem())
            if lingua in esperados and lingua in p.idiomas:
                c.tp += 1
                r.nivel_n += 1
                r.nivel_acertos += esperados[lingua].nivel == p.idiomas[lingua].nivel
                r.importancia_acertos += esperados[lingua].importancia == p.idiomas[lingua].importancia
            elif lingua in p.idiomas:
                c.fp += 1
                r.erros.append(f"exige {lingua} (falso positivo): {item.titulo}")
            else:
                c.fn += 1
                r.erros.append(f"exige {lingua} (não detectado): {item.titulo}")
    return r


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{100 * v:.1f}%"


def relatorio(r: ResultadoClassificacao, max_erros: int = 25) -> str:
    aviso = f" · **amostra pequena** (n < {AMOSTRA_MIN})" if r.amostra_pequena else ""
    f1 = r.familia_f1_macro
    meta_f = "" if f1 is None else (" ✓ meta" if f1 >= META_FAMILIA_F1 else f" ✗ meta {META_FAMILIA_F1:.2f}")
    idi = r.idioma_acuracia
    meta_i = "" if idi is None else (" ✓ meta" if idi >= META_IDIOMA else f" ✗ meta {META_IDIOMA:.2f}")
    linhas = [
        f"n = {r.n} vagas rotuladas{aviso}",
        "",
        "| Medida | Valor |",
        "|---|---|",
        f"| Família: F1 macro | {_pct(f1)}{meta_f} |",
        f"| Família: acurácia | {_pct(r.familia_acuracia)} |",
        f"| Subfamília: acurácia (família certa, n = {r.subfamilia_n}) | {_pct(r.subfamilia_acuracia)} |",
        f"| Idioma da vaga: acurácia | {_pct(idi)}{meta_i} |",
        f"| Nível do idioma exigido (n = {r.nivel_n}) | "
        f"{_pct(r.nivel_acertos / r.nivel_n if r.nivel_n else None)} |",
        f"| Importância do idioma exigido | {_pct(r.importancia_acertos / r.nivel_n if r.nivel_n else None)} |",
        "",
        "| Família | Precisão | Recall | F1 | n (ouro) |",
        "|---|---|---|---|---|",
    ]
    for fam, c in sorted(r.por_familia.items()):
        linhas.append(f"| {fam} | {_pct(c.precisao)} | {_pct(c.recall)} | {_pct(c.f1)} | {c.tp + c.fn} |")
    if r.exigencias:
        linhas += ["", "| Idioma exigido | Precisão | Recall | n (ouro) |", "|---|---|---|---|"]
        for lingua, c in sorted(r.exigencias.items()):
            linhas.append(f"| {lingua} | {_pct(c.precisao)} | {_pct(c.recall)} | {c.tp + c.fn} |")
    if r.confusoes:
        linhas += ["", "Confusões (ouro → previsto): " + "; ".join(
            f"{a} → {b} ({n})" for (a, b), n in r.confusoes.most_common(8))]
    if r.erros:
        linhas += ["", f"Erros ({len(r.erros)}):"] + [f"- {e}" for e in r.erros[:max_erros]]
    return "\n".join(linhas)

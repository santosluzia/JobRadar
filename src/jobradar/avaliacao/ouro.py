"""Conjunto-ouro: amostra de vagas com as competências anotadas por pessoa.

Regras de anotação (docs/avaliacao.md):
- anote a competência se a VAGA pede ou cita como parte do trabalho (requisito ou desejável),
  inclusive quando uma frase a implica sem ambiguidade ("pipelines de ingestão" → etl);
- não anote o que aparece só no texto sobre a empresa, benefícios ou processo seletivo;
- use os ids de config/skills.yaml; competência que falta na taxonomia vai em `notas`.

Um item só entra na medição oficial com `revisado: true`. Rascunhos (`revisado: false`) servem
para testar a ferramenta, e o relatório avisa quando eles foram usados.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..storage import Lake

CAMINHO_OURO = Path("avaliacao") / "conjunto_ouro.yaml"


class IdiomaOuro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idioma: str                       # en | es | pt
    nivel: str = "nao_informado"      # fluente | avancado | intermediario | basico | nao_informado
    importancia: str = "requisito"    # requisito | desejavel


class ClassificacaoOuro(BaseModel):
    """Rótulos de classificação do cargo (ADR 0014), revisados à parte das competências: uma vaga pode ter
    a família revisada e as competências ainda em rascunho, ou o contrário. Regras em docs/avaliacao.md."""
    model_config = ConfigDict(extra="forbid")

    familia: str
    subfamilia: str
    idioma_vaga: str                                     # pt | en | es | indeterminado
    idiomas: list[IdiomaOuro] = Field(default_factory=list)   # idiomas que a vaga exige (vazio = nenhum)
    revisado: bool = False
    anotador: str | None = None
    notas: str = ""


class ItemOuro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    fonte: str
    familia: str
    titulo: str
    descricao: str
    revisado: bool = False
    anotador: str | None = None
    competencias: list[str] | None = None     # None = ainda não anotado
    desejaveis: list[str] = Field(default_factory=list)   # subconjunto de `competencias`
    notas: str = ""
    # "ajuste" = usado para calibrar regras; "teste" = sorteado DEPOIS do ajuste e anotado sem ver a
    # saída do extrator. A métrica que vale é a do lote "teste" (a de ajuste é otimista).
    lote: str = "ajuste"
    pais_iso: str | None = None                          # para a exigência inferida pelo idioma da vaga
    classificacao: ClassificacaoOuro | None = None       # None = cargo ainda não rotulado

    @property
    def completa(self) -> bool:
        """Descrição completa (ATS) × trecho de 500 caracteres (Adzuna)."""
        return self.fonte != "adzuna"


class ConjuntoOuro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: int = 1
    taxonomia_versao: str               # versão da taxonomia cujos ids a anotação usa
    itens: list[ItemOuro] = Field(default_factory=list)

    def anotados(self, incluir_rascunhos: bool = False, lote: str | None = None) -> list[ItemOuro]:
        return [i for i in self.itens if i.competencias is not None and (i.revisado or incluir_rascunhos)
                and (lote is None or i.lote == lote)]

    def rotulados(self, incluir_rascunhos: bool = False, lote: str | None = None) -> list[ItemOuro]:
        """Itens com rótulos de classificação (revisados, ou também os rascunhos)."""
        return [i for i in self.itens if i.classificacao is not None
                and (i.classificacao.revisado or incluir_rascunhos) and (lote is None or i.lote == lote)]


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, valor: str) -> yaml.ScalarNode:
    estilo = "|" if "\n" in valor else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", valor, style=estilo)


_Dumper.add_representer(str, _str)


def carregar_ouro(lake_root: Path) -> ConjuntoOuro | None:
    p = Path(lake_root) / CAMINHO_OURO
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return ConjuntoOuro.model_validate(yaml.safe_load(f) or {})


def salvar_ouro(lake_root: Path, conjunto: ConjuntoOuro) -> Path:
    p = Path(lake_root) / CAMINHO_OURO
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Conjunto-ouro do JobRadar — PRIVADO (texto de vagas de terceiros + anotações).\n"
                "# Regras de anotação: docs/avaliacao.md. Só itens com revisado: true entram na medição oficial.\n")
        yaml.dump(conjunto.model_dump(), f, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)
    tmp.replace(p)
    return p


def amostrar(lake: Lake, taxonomia_versao: str, familias: list[str], n_completas: int = 25,
             n_trechos: int = 15, semente: int = 42, existente: ConjuntoOuro | None = None,
             lote: str = "ajuste") -> ConjuntoOuro:
    """Sorteia vagas canônicas das famílias de dados ainda fora do conjunto, estratificando por
    tipo de texto: descrição completa (ATS) e trecho curto (Adzuna, ~91% do volume)."""
    jobs = lake.read("silver/jobs")
    base = jobs[jobs["is_canonica"].fillna(False) & jobs["familia"].isin(familias) & jobs["descricao"].notna()]
    conjunto = existente or ConjuntoOuro(taxonomia_versao=taxonomia_versao)
    ja = {i.job_id for i in conjunto.itens}
    base = base[~base["job_id"].isin(ja)].sort_values("job_id")   # ordem estável → sorteio reprodutível
    partes = []
    for completa, n in ((True, n_completas), (False, n_trechos)):
        grupo = base[(base["source"] != "adzuna") == completa]
        partes.append(grupo.sample(min(n, len(grupo)), random_state=semente) if n else grupo.iloc[0:0])
    for j in pd.concat(partes).itertuples():
        conjunto.itens.append(ItemOuro(job_id=j.job_id, fonte=j.source, familia=j.familia, titulo=j.titulo,
                                       descricao=j.descricao, lote=lote, pais_iso=_txt(j.pais_iso)))
    return conjunto


def _txt(v) -> str | None:
    return v if isinstance(v, str) and v else None


def amostrar_classificacao(lake: Lake, por_familia: int = 8, adjacentes: int = 10, outros_idiomas: int = 8,
                           semente: int = 42, existente: ConjuntoOuro | None = None, taxonomia_versao: str = "",
                           lote: str = "ajuste") -> ConjuntoOuro:
    """Sorteia vagas para rotular a CLASSIFICAÇÃO (família, subfamília, idiomas), fora as que já estão.

    Estratos (pela classificação atual, só para cobrir todos os casos; o rótulo é dado sem olhar para ela):
    `por_familia` de cada família, inclusive `outra`; `adjacentes` de `outra` com subfamília de cargo
    adjacente a dados (ciência de dados, ML, liderança, produto), onde a fronteira é mais difícil; e
    `outros_idiomas` vagas que não estão em português. Vagas sem descrição ficam de fora."""
    jobs = lake.read("silver/jobs")
    base = jobs[jobs["is_canonica"].fillna(False) & jobs["descricao"].notna()]
    conjunto = existente or ConjuntoOuro(taxonomia_versao=taxonomia_versao)
    ja = {i.job_id for i in conjunto.itens}
    base = base[~base["job_id"].isin(ja)].sort_values("job_id")
    escolhidos: list[pd.DataFrame] = []

    def tirar(grupo: pd.DataFrame, n: int) -> None:
        usados = set(pd.concat(escolhidos)["job_id"]) if escolhidos else set()
        grupo = grupo[~grupo["job_id"].isin(usados)]
        if n and len(grupo):
            escolhidos.append(grupo.sample(min(n, len(grupo)), random_state=semente))

    for fam in sorted(base["familia"].dropna().unique()):
        tirar(base[base["familia"] == fam], por_familia)
    sub = base["subfamilia"].fillna("")
    tirar(base[(base["familia"] == "outra") & ~sub.isin(["", "fora_de_dados"])], adjacentes)
    tirar(base[base["idioma_vaga"].fillna("pt") != "pt"], outros_idiomas)
    for j in (pd.concat(escolhidos).itertuples() if escolhidos else []):
        conjunto.itens.append(ItemOuro(job_id=j.job_id, fonte=j.source, familia=j.familia, titulo=j.titulo,
                                       descricao=j.descricao, lote=lote, pais_iso=_txt(j.pais_iso)))
    return conjunto

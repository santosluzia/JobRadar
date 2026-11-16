"""Extração de competências por regras, com taxonomia versionada (config/skills.yaml).

Dois tipos de regra, ambos determinísticos e sem chamada externa:
- termo    → o nome da competência ou um sinônimo direto ("pyspark", "power query"): confiança alta;
- conceito → uma frase que implica a competência sem citá-la ("pipelines escaláveis" → ETL/ELT):
             confiança média. É inferência por regra, então a precisão é medida no conjunto-ouro.

Cada achado guarda a FRASE da vaga que o justifica (evidência), o método e a versão da taxonomia.

Heurística de importância (documentada como heurística, não como verdade):
- aparece no título ou numa seção comum → "requisito";
- aparece só depois de um marcador de "desejável/diferencial" → "desejavel".

Tipos: só competências `tecnica` alimentam gold, score, recomendações e dados públicos.
`comportamental` e `idioma` ficam na silver para uso privado (currículo, relatórios).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .text import normalizar

TIPOS = ("tecnica", "comportamental", "idioma")
METODOS = ("termo", "conceito", "embedding")
VERSAO_LEGADA = "1.0.0"   # linhas gravadas antes de a taxonomia ter versão
LIMITE_EVIDENCIA = 240

# Frases: quebra em fim de frase, ponto e vírgula e marcadores de lista. Não quebra "e.g." nem "3.5".
# Também quebra ponto colado em maiúscula ("…MEC.Arquitetura") e ";" sem espaço ("SQL;Python"), comuns na Gupy.
_FIM_DE_FRASE = re.compile(
    r"(?<=[.!?])\s*(?=[A-ZÀ-Ý•\-–(\"'])|(?<=[.!?])\s+(?=[0-9])|(?<=;)\s*|\s*[•▪●◦]\s*|\s+[-–]\s+(?=[A-ZÀ-Ý])")
# A Gupy entrega a descrição numa linha só, com cabeçalhos e listas colados no texto
# ("…em GCP.- Desenvolver…", "atribuiçõesArquitetura…", "Diferenciais:- Docker"). Antes de olhar
# as seções, devolve as quebras de linha que o HTML tinha.
_CABECALHO_MODELO = re.compile(   # cabeçalhos fixos do modelo de vaga da Gupy: quebra antes e depois
    r"(Responsabilidades e atribui[çc][õo]es|Requisitos e qualifica[çc][õo]es|Informa[çc][õo]es adicionais"
    r"|Etapas do processo)", re.I)
# "…áreas de negócio.DiferenciaisPython.": cabeçalho colado nas duas pontas, sem dois-pontos.
_CABECALHO_COLADO = re.compile(r"(?<=[a-zà-ÿ.;])(Diferenciais|Desej[áa]veis|Requisitos)(?=[A-ZÀ-Ý])")
_CABECALHO_COM_DOIS_PONTOS = re.compile(
    r"(?<=\S)(?=(Diferencia(l|is)|Desej[áa]ve(l|is)|Requisitos( obrigat[óo]rios| desej[áa]veis| t[ée]cnicos)?"
    r"|Benef[íi]cios|Qualifica[çc][õo]es|Conhecimentos( t[ée]cnicos| desej[áa]veis)?)\s*:)")
_LISTA_COLADA = re.compile(r"(?<=[.;:!?])\s*[-–•▪●]\s*(?=\S)")


def segmentar(texto: str) -> list[str]:
    """Linhas da descrição, com cabeçalhos e itens de lista colados separados."""
    t = _CABECALHO_MODELO.sub(lambda m: "\n" + m.group(0) + "\n", texto)
    t = _CABECALHO_COLADO.sub(lambda m: "\n" + m.group(0) + "\n", t)
    t = _CABECALHO_COM_DOIS_PONTOS.sub("\n", t)
    t = _LISTA_COLADA.sub("\n", t)
    return [linha.strip() for linha in t.splitlines() if linha.strip()]


def _normalizar_com_mapa(original: str) -> tuple[str, list[int]]:
    """Igual a `normalizar`, mas devolve também, para cada caractere normalizado, a posição dele
    no texto original — para recortar a evidência em volta do trecho que casou."""
    saida: list[str] = []
    mapa: list[int] = []
    for i, ch in enumerate(original):
        pedaco = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode().lower()
        for c in pedaco:
            if c.isspace():
                if saida and saida[-1] != " ":
                    saida.append(" "); mapa.append(i)
            else:
                saida.append(c); mapa.append(i)
    while saida and saida[-1] == " ":
        saida.pop(); mapa.pop()
    return "".join(saida), mapa


def recortar(original: str, norm: str, inicio: int, fim: int, limite: int = LIMITE_EVIDENCIA) -> str:
    """Evidência: a frase original inteira se couber; senão, uma janela centrada no trecho que casou."""
    texto = " ".join(original.split())
    if len(texto) <= limite:
        return texto
    n2, mapa = _normalizar_com_mapa(texto)
    if n2 != norm or not mapa:     # mapeamento não confiável: recorta do começo
        return texto[: limite - 1].rstrip() + "…"
    a, b = mapa[min(inicio, len(mapa) - 1)], mapa[min(max(fim - 1, 0), len(mapa) - 1)] + 1
    folga = max((limite - (b - a)) // 2, 0)
    ini, fim_ = max(a - folga, 0), min(b + folga, len(texto))
    if ini == 0:                  # encostou numa ponta: usa a folga do outro lado
        fim_ = min(limite, len(texto))
    elif fim_ == len(texto):
        ini = max(len(texto) - limite, 0)
    trecho = texto[ini:fim_].strip()
    return ("…" if ini > 0 else "") + trecho + ("…" if fim_ < len(texto) else "")


# ------------------------------------------------------------------ configuração (Pydantic)
def _compila(padroes: list[str], campo: str, sid: str) -> list[str]:
    for p in padroes:
        try:
            re.compile(p)
        except re.error as e:
            raise ValueError(f"{sid}.{campo}: regex inválida {p!r}: {e}") from e
    return padroes


class CompetenciaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    nome: str
    categoria: str
    tipo: Literal["tecnica", "comportamental", "idioma"] = "tecnica"
    padroes: list[str] = Field(min_length=1)
    conceitos: list[str] = Field(default_factory=list)
    # Frases curtas que descrevem a competência; âncoras da camada de embeddings (desligada por padrão).
    descricoes: list[str] = Field(default_factory=list)
    # Competência que também é nome de curso ("Graduação em Estatística"): não conta em frase de formação.
    ignorar_em_formacao: bool = False
    esforco: Literal["baixo", "medio", "alto"] = "medio"
    projeto: bool = True

    @model_validator(mode="after")
    def _regex_validas(self) -> "CompetenciaConfig":
        _compila(self.padroes, "padroes", self.id)
        _compila(self.conceitos, "conceitos", self.id)
        return self


class SemanticaConfig(BaseModel):
    """Camada de embeddings local. Modelo baixado uma vez por revisão fixa e conferido por hash."""
    model_config = ConfigDict(extra="forbid")

    ativa: bool = False
    backend: Literal["model2vec"] = "model2vec"   # fastembed foi medido e descartado (ADR 0001)
    modelo: str = ""                       # repositório no Hugging Face
    revisao: str = ""                      # commit fixo (nunca "main")
    sha256: dict[str, str] = Field(default_factory=dict)   # arquivo do modelo → hash esperado
    limiar: float = Field(default=0.65, ge=0, le=1)         # similaridade mínima para aceitar
    limiar_media: float = Field(default=0.75, ge=0, le=1)   # a partir daqui, confiança "media"
    tipos: list[Literal["tecnica", "comportamental", "idioma"]] = Field(default_factory=lambda: ["tecnica"])

    @model_validator(mode="after")
    def _pinado(self) -> "SemanticaConfig":
        if self.ativa and not (self.modelo and re.fullmatch(r"[0-9a-f]{40}", self.revisao) and self.sha256):
            raise ValueError("extracao.semantica ativa exige modelo, revisao (commit de 40 hex) e sha256")
        return self


class ExtracaoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantica: SemanticaConfig = Field(default_factory=SemanticaConfig)
    gold_hibrida: bool = False


class CandidatasConfig(BaseModel):
    """Fila de curadoria (`jobradar competencias candidatas`)."""
    model_config = ConfigDict(extra="forbid")

    stopwords: list[str] = Field(default_factory=list)
    ignorar: list[str] = Field(default_factory=list)   # regex de termos já avaliados e recusados


class TaxonomiaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: str = Field(default=VERSAO_LEGADA, pattern=r"^\d+\.\d+\.\d+$")
    competencias: list[CompetenciaConfig]
    marcadores_desejavel: list[str] = Field(default_factory=list)
    marcadores_requisito: list[str] = Field(default_factory=list)
    marcadores_contexto: list[str] = Field(default_factory=list)
    frases_contexto: list[str] = Field(default_factory=list)
    frases_vaga: list[str] = Field(default_factory=list)
    frases_formacao: list[str] = Field(default_factory=list)
    extracao: ExtracaoConfig = Field(default_factory=ExtracaoConfig)
    candidatas: CandidatasConfig = Field(default_factory=CandidatasConfig)

    @field_validator("competencias")
    @classmethod
    def _ids_unicos(cls, v: list[CompetenciaConfig]) -> list[CompetenciaConfig]:
        vistos: set[str] = set()
        repetidos = {c.id for c in v if c.id in vistos or vistos.add(c.id)}
        if repetidos:
            raise ValueError(f"ids repetidos na taxonomia: {sorted(repetidos)}")
        return v


# ------------------------------------------------------------------ domínio
@dataclass(frozen=True)
class Skill:
    id: str
    nome: str
    categoria: str
    padroes: tuple[re.Pattern, ...]
    esforco: str
    projeto: bool
    tipo: str = "tecnica"
    conceitos: tuple[re.Pattern, ...] = ()
    descricoes: tuple[str, ...] = ()
    ignorar_em_formacao: bool = False


@dataclass(frozen=True)
class SkillMatch:
    skill_id: str
    importancia: str           # requisito | desejavel
    termo: str                 # trecho que casou
    metodo: str = "termo"      # termo | conceito | embedding
    evidencia: str = ""        # frase original da vaga que justifica o achado
    confianca: str = "alta"    # alta (termo) | media (conceito) | baixa
    tipo: str = "tecnica"
    # TODAS as menções da competência na vaga: (frase, início, fim) no texto normalizado da frase.
    # Servem para a coocorrência não contar como par duas competências da MESMA menção
    # ("Azure Data Factory" → azure + data_factory; "PySpark" → python + spark).
    posicoes: tuple[tuple[int, int, int], ...] = ()


@dataclass(frozen=True)
class Unidade:
    """Uma frase da vaga, já com a seção (requisito/desejável) em que aparece."""
    modo: str          # requisito | desejavel | contexto
    norm: str
    original: str
    formacao: bool = False   # frase de formação acadêmica ("Graduação em …")


@dataclass(frozen=True)
class Marcadores:
    desejavel: re.Pattern
    requisito: re.Pattern
    contexto: re.Pattern          # cabeçalho de seção sobre a empresa/benefícios
    frase_contexto: re.Pattern    # frase institucional ("somos…", "acreditamos…")
    frase_vaga: re.Pattern = re.compile(r"$^")       # frase que descreve a vaga ("buscamos…")
    frase_formacao: re.Pattern = re.compile(r"$^")   # "Graduação em Estatística…" (não é competência)


def _rx(padroes: list[str]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in padroes) or r"$^")


def _cabecalho(n: str, rx: re.Pattern, curto: bool) -> bool:
    """Linha é cabeçalho de seção: termina em ":" ou é curta e COMEÇA pelo marcador.
    ("Diferenciais", "Requisitos e qualificações" sim; "Inglês é um diferencial" não.)"""
    m = rx.search(n)
    if m is None or m.start() > 12 and not n.endswith(":"):
        return False
    # "Diferencial: Conhecer Telecom; …" — cabeçalho no começo de uma linha longa também vale
    return n.endswith(":") or curto or ":" in n[m.end(): m.end() + 25]


def unidades(titulo: str, descricao: str | None, mk: Marcadores) -> list[Unidade]:
    """Título + frases da descrição, cada uma marcada como requisito, desejável ou contexto.

    Contexto = seção sobre a empresa, benefícios ou etapas, e frases institucionais: não geram
    competência (a empresa "aplicar IA nos processos" não é requisito da vaga). O texto ANTES do
    primeiro cabeçalho reconhecido também é contexto — mas só se a vaga tiver cabeçalhos; snippet
    sem estrutura (Adzuna) fica todo como requisito."""
    saida = [Unidade("requisito", normalizar(titulo), (titulo or "").strip())]
    corpo: list[tuple[str | None, str, str, bool]] = []   # (modo da seção, norm, original, curto)
    modo: str | None = None   # None = antes do primeiro cabeçalho
    for linha in segmentar(descricao or ""):
        n = normalizar(linha)
        if not n:
            continue
        curto = len(n) <= 60
        for novo, rx in (("desejavel", mk.desejavel), ("requisito", mk.requisito), ("contexto", mk.contexto)):
            if _cabecalho(n, rx, curto):
                modo = novo
                break
        corpo.append((modo, n, linha, curto))
    tem_cabecalho = any(m is not None for m, *_ in corpo)
    inicio = "contexto" if tem_cabecalho else "requisito"
    for modo, n, linha, curto in corpo:
        if modo is None and inicio == "contexto" and mk.frase_vaga.search(n):
            inicio = "requisito"   # o texto de abertura passou a falar da vaga
        modo = modo or inicio
        for frase in _FIM_DE_FRASE.split(linha):
            fn = normalizar(frase)
            if not fn:
                continue
            m = modo
            if m != "contexto" and mk.frase_contexto.search(fn):
                m = "contexto"
            # "Inglês é um diferencial" na própria frase vale só para ela
            elif m == "requisito" and mk.desejavel.search(fn):
                m = "desejavel"
            saida.append(Unidade(m, fn, frase.strip(), bool(mk.frase_formacao.search(fn))))
    return saida


class Taxonomy:
    def __init__(self, cfg: dict[str, Any]):
        self.config = TaxonomiaConfig.model_validate(cfg)
        self.versao = self.config.versao
        todas = [
            Skill(c.id, c.nome, c.categoria, tuple(re.compile(p) for p in c.padroes), c.esforco, c.projeto,
                  c.tipo, tuple(re.compile(p) for p in c.conceitos), tuple(c.descricoes), c.ignorar_em_formacao)
            for c in self.config.competencias
        ]
        self.todas = todas
        # `skills` = só técnicas: é o que gold, score, recomendações e contrato público enxergam.
        self.skills = [s for s in todas if s.tipo == "tecnica"]
        self.nao_tecnicas = [s for s in todas if s.tipo != "tecnica"]
        self.por_id = {s.id: s for s in todas}
        c = self.config
        self.marcadores = Marcadores(_rx(c.marcadores_desejavel), _rx(c.marcadores_requisito),
                                     _rx(c.marcadores_contexto), _rx(c.frases_contexto),
                                     _rx(c.frases_vaga), _rx(c.frases_formacao))

    @property
    def ids_tecnicos(self) -> set[str]:
        return {s.id for s in self.skills}

    def unidades(self, titulo: str, descricao: str | None) -> list[Unidade]:
        return unidades(titulo, descricao, self.marcadores)

    def extrair(self, titulo: str, descricao: str | None) -> list[SkillMatch]:
        """Todas as competências (técnicas e não técnicas). Por competência, fica o melhor achado:
        requisito vence desejável; no mesmo nível, termo vence conceito."""
        frases = self.unidades(titulo, descricao)
        achados: dict[str, SkillMatch] = {}
        for skill in self.todas:
            for metodo, padroes, conf in (("termo", skill.padroes, "alta"), ("conceito", skill.conceitos, "media")):
                atual = achados.get(skill.id)
                if atual is not None and atual.importancia == "requisito":
                    break   # já tem o melhor possível com método melhor ou igual
                for u in frases:
                    if u.modo == "contexto" or (atual is not None and u.modo == "desejavel") \
                            or (u.formacao and skill.ignorar_em_formacao):
                        continue   # contexto não conta; desejável não melhora o que já existe
                    m = next((m for p in padroes if (m := p.search(u.norm))), None)
                    if m is None:
                        continue
                    ev = recortar(u.original, u.norm, m.start(), m.end())
                    atual = SkillMatch(skill.id, u.modo, m.group(0), metodo, ev, conf, skill.tipo)
                    achados[skill.id] = atual
                    if u.modo == "requisito":
                        break
        return sorted((replace(a, posicoes=self._posicoes(self.por_id[sid], frases)) for sid, a in achados.items()),
                      key=lambda a: a.skill_id)

    @staticmethod
    def _posicoes(skill: Skill, frases: list[Unidade]) -> tuple[tuple[int, int, int], ...]:
        """Todas as menções (termo ou conceito) da competência nas frases que contam."""
        spans = set()
        for i, u in enumerate(frases):
            if u.modo == "contexto" or (u.formacao and skill.ignorar_em_formacao):
                continue
            for p in (*skill.padroes, *skill.conceitos):
                spans.update((i, m.start(), m.end()) for m in p.finditer(u.norm) if m.end() > m.start())
        return tuple(sorted(spans))


def so_tecnicas(skills: pd.DataFrame) -> pd.DataFrame:
    """Linhas de silver/job_skills que alimentam gold, score e dados públicos.
    Linhas antigas (sem `tipo`) eram todas técnicas."""
    if "tipo" not in skills.columns or skills.empty:
        return skills
    return skills[skills["tipo"].fillna("tecnica") == "tecnica"]


def efetivas(regras: pd.DataFrame, semantica: pd.DataFrame | None = None, hibrida: bool = False) -> pd.DataFrame:
    """Competências que contam para gold, score e dados públicos — UM ponto de decisão.

    Padrão: só as técnicas achadas por regra. Com `gold_hibrida`, soma as técnicas da camada
    semântica (que já foram gravadas só acima do limiar e só onde a regra não achou nada)."""
    base = so_tecnicas(regras)
    if not hibrida or semantica is None or semantica.empty:
        return base
    extra = so_tecnicas(semantica[semantica["skill_id"].notna()])   # linha sem skill = vaga sem achado
    chave = base["job_id"] + "|" + base["skill_id"]
    extra = extra[~(extra["job_id"] + "|" + extra["skill_id"]).isin(set(chave))]
    colunas = list(base.columns) + [c for c in ("metodo",) if c not in base.columns]
    extra = extra.assign(metodo="embedding", termo=None).reindex(columns=colunas)
    return pd.concat([base, extra], ignore_index=True)


def versoes(skills: pd.DataFrame) -> dict[str, str]:
    """job_id → versão da taxonomia com que as competências da vaga foram extraídas."""
    if skills.empty:
        return {}
    v = skills["taxonomia_versao"].fillna(VERSAO_LEGADA) if "taxonomia_versao" in skills.columns \
        else pd.Series(VERSAO_LEGADA, index=skills.index)
    return dict(zip(skills["job_id"], v))


def linhas(job_id: str, achados: list[SkillMatch], run_id: str, versao: str) -> list[dict]:
    """SkillMatch → linhas de silver/job_skills."""
    return [{"job_id": job_id, "skill_id": m.skill_id, "importancia": m.importancia, "termo": m.termo,
             "run_id": run_id, "metodo": m.metodo, "evidencia": m.evidencia or None,
             "confianca": m.confianca, "tipo": m.tipo, "taxonomia_versao": versao,
             "posicoes": json.dumps([list(p) for p in m.posicoes]) if m.posicoes else None} for m in achados]

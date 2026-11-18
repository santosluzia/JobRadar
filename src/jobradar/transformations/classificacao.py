"""Classificação complementar do cargo: subfamília, idioma da vaga e idiomas exigidos (ADR 0014).

Fica fora de `normalize.py` porque tem versão própria (`CLASSIFICACAO_VERSAO`) e migração incremental
do histórico (`atualizar`), como a geografia. A família continua em `normalize.familia` e sobe com a
versão da taxonomia (o `reextrair` a reaplica). A subfamília depende da família e é recalculada junto.

Cada valor registra a origem em `origem_campos` (titulo | familia | descricao | nao_informada).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from .normalize import titulo_sem_genero
from .text import normalizar

if TYPE_CHECKING:
    from .skills import Taxonomy, Unidade

CLASSIFICACAO_VERSAO = "1.0.0"

# --------------------------------------------------------------------------- subfamília
# Por família, a primeira regra que casa com o título vale; sem regra, a subfamília geral da família.
# Em `outra`, as subfamílias marcam cargos ADJACENTES a dados (ciência de dados, ML, liderança, produto),
# que ficam fora do escopo das famílias de dados, do score e do contrato público.
SUBFAMILIAS: dict[str, tuple[list[tuple[str, str]], str]] = {
    "engenharia_dados": ([
        ("arquitetura_dados", r"arquitet[oa]s?|arquitetura|architect"),
        ("dataops", r"\bdataops\b"),
        ("plataforma_dados", r"plataforma|platforms?\b"),
    ], "engenharia_dados"),
    "analytics_engineering": ([], "analytics_engineering"),
    "desenvolvimento_dados": ([
        ("bi_desenvolvimento", r"\bbi\b|power ?bi|tableau|qlik|looker|visuali[sz]"),
        ("banco_dados", r"pl ?/ ?sql|oracle|\bsql\b|banco[s]? (de )?dados|bases? de datos|database"),
        ("etl_integracao", r"\betl\b|integra"),
    ], "desenvolvimento_dados"),
    "analise_dados": ([
        ("bi_visualizacao", r"\bbi\b|business intelligence|inteligencia de negocios|power ?bi|tableau|qlik|looker|"
                            r"visuali[sz]|dataviz"),
    ], "analise_dados"),
    "governanca_qualidade": ([
        ("mdm", r"\bmdm\b|master data|dados mestres"),   # antes de qualidade: "Master Data Quality" é MDM
        ("qualidade_dados", r"qualidade|quality|calidad"),
        ("integracao_dados", r"integracao|integracion|integration"),
    ], "governanca_dados"),
    "administracao_dados": ([
        # AD (modelagem, dicionário e padrões de dados) × DBA (operação do banco)
        ("administracao_dados", r"^(?!.*(banco|bases? de datos|database)).*administr\w* (de )?dados|data administrator"),
    ], "dba"),
    "outra": ([
        ("ciencia_dados", r"cientista de dados|(data|applied|research|machine learning) scientist|ciencia de dados|data science|cientific[oa] de datos|ciencia de datos"),
        ("machine_learning", r"machine learning|\bml ?ops\b|\bml engineer|aprendizado de maquina"),
        ("produto_dados", r"data product|produto de dados|product (manager|owner) (de )?dados"),
        ("lideranca_dados", r"\b(head|gerente|diretor[a]?|director|manager|coordenador[a]?|lider|lead|jefe)\b"
                            r".{0,25}\b(dados|data|analytics|datos|bi)\b"),
    ], "fora_de_dados"),
}
_SUB_RX = {f: ([(s, re.compile(p)) for s, p in regras], geral) for f, (regras, geral) in SUBFAMILIAS.items()}
SUBFAMILIAS_VALIDAS = {f: {s for s, _ in regras} | {geral} for f, (regras, geral) in SUBFAMILIAS.items()}


def subfamilia(titulo: str | None, familia: str | None) -> tuple[str, str]:
    """(subfamília, origem). Origem `titulo` quando uma regra casou; `familia` quando é a geral."""
    regras, geral = _SUB_RX.get(familia or "outra", _SUB_RX["outra"])
    t = titulo_sem_genero(titulo)
    for valor, rx in regras:
        if rx.search(t):
            return valor, "titulo"
    return geral, "familia"


# --------------------------------------------------------------------------- idioma da vaga
# Palavras funcionais frequentes e EXCLUSIVAS de cada idioma (texto sem acento). Palavras comuns a
# português e espanhol ("de", "para", "en"...) ficam de fora: não ajudam a separar os dois.
_FUNCIONAIS = {
    "pt": {"e", "em", "do", "da", "na", "os", "um", "voce", "nao", "sao", "com", "uma", "dos", "das", "nossa", "nosso", "ao", "aos", "pelo", "pela",
           "seu", "sua", "isso", "tambem", "trabalho", "conhecimento", "conhecimentos", "vaga",
           "mais", "ou", "atuar", "desenvolvimento", "voces", "nossos", "nossas"},
    "es": {"y", "el", "la", "en", "es", "un", "los", "las", "del", "con", "una", "usted", "nuestro", "nuestra", "nuestros", "trabajo",
           "conocimiento", "conocimientos", "puesto", "desarrollo", "ofrecemos", "equipo", "tus"},
    "en": {"the", "and", "with", "you", "your", "of", "to", "for", "our", "is", "are", "we", "will", "experience",
           "knowledge", "work", "team", "skills", "this", "that", "be", "or", "in", "on"},
}
MIN_PALAVRAS_IDIOMA = 8      # abaixo disso (título curto, trecho vazio) o idioma fica indeterminado
MARGEM_IDIOMA = 1.5          # o 1º idioma precisa de 1,5× as ocorrências do 2º


def idioma_texto(texto: str | None) -> str | None:
    """pt | en | es pela contagem de palavras funcionais; None se o texto não decide."""
    palavras = re.findall(r"[a-z]+", normalizar(texto)[:4000])
    if len(palavras) < MIN_PALAVRAS_IDIOMA:
        return None
    cont = Counter(palavras)
    placar = {}
    for idioma, funcionais in _FUNCIONAIS.items():
        placar[idioma] = sum(cont[p] for p in funcionais)
    ordem = sorted(placar.items(), key=lambda kv: -kv[1])
    (primeiro, n1), (_, n2) = ordem[0], ordem[1]
    if n1 < 3 or n1 < MARGEM_IDIOMA * n2:
        return None
    return primeiro


def idioma_vaga(titulo: str | None, descricao: str | None) -> tuple[str, str]:
    """(pt | en | es | indeterminado, origem). A descrição decide; sem ela, o título (quase sempre curto)."""
    for origem, texto in (("descricao", descricao), ("titulo", titulo)):
        idioma = idioma_texto(texto)
        if idioma:
            return idioma, origem
    return "indeterminado", "nao_informada"


# --------------------------------------------------------------------------- idiomas exigidos
_MENCAO_IDIOMA = {
    "en": re.compile(r"\bingles\b|\benglish\b"),
    "es": re.compile(r"\bespanhol\b|\bspanish\b|\bespanol\b|\bcastellano\b"),
    "pt": re.compile(r"\bportugues\b|\bportuguese\b"),
}
# Nível: o mais alto citado na frase vale. Ordem do mais alto para o mais baixo.
NIVEIS = [
    ("fluente", r"fluen|\bfluid[oa]\b|nativ[oa]|\bnative\b|bilingu|\bc2\b"),
    ("avancado", r"avancad[oa]|avanzad[oa]|advanced|proficien|\bc1\b|\bupper[- ]intermediate\b"),
    ("intermediario", r"intermediari[oa]|intermedi[oa]\b|intermediate|conversa(cao|cion|tional)|\bb[12]\b"),
    ("basico", r"basic[oa]|\bbasic\b|tecnico|instrumental|leitura|lectura|reading|\ba[12]\b"),
]
_NIVEIS_RX = [(n, re.compile(p)) for n, p in NIVEIS]
_NEGACAO = re.compile(r"\bnao (e )?(necessari|obrigatori|exigid|precis)|not required|no (es )?(necesari|requerid)")


def _nivel(frase: str) -> str:
    for nivel, rx in _NIVEIS_RX:
        if rx.search(frase):
            return nivel
    return "nao_informado"


@dataclass
class Exigencia:
    idioma: str                  # en | es | pt
    nivel: str                   # fluente | avancado | intermediario | basico | nao_informado
    importancia: str             # requisito | desejavel
    origem: str                  # descricao | titulo | idioma_da_vaga
    evidencia: str = ""          # frase original (até 160 caracteres)

    def to_dict(self) -> dict:
        return {"idioma": self.idioma, "nivel": self.nivel, "importancia": self.importancia, "origem": self.origem,
                "evidencia": self.evidencia}


_ORDEM_NIVEL = {n: i for i, (n, _) in enumerate(NIVEIS)} | {"nao_informado": len(NIVEIS)}
_ORDEM_IMPORTANCIA = {"requisito": 0, "desejavel": 1}
_PAISES_ES = {"AR", "BO", "CL", "CO", "CR", "CU", "DO", "EC", "ES", "GT", "HN", "MX", "NI", "PA", "PE", "PR", "PY",
              "SV", "UY", "VE"}
_PAISES_EN = {"US", "GB", "CA", "IE", "AU", "NZ"}


def idioma_do_pais(pais_iso: str | None) -> str | None:
    """Idioma esperado de uma vaga do país (sem país = Brasil, a maior parte do histórico)."""
    p = pais_iso or "BR"
    return "pt" if p in ("BR", "PT") else "es" if p in _PAISES_ES else "en" if p in _PAISES_EN else None


def _peso(e: "Exigencia") -> tuple[int, int]:
    return _ORDEM_IMPORTANCIA.get(e.importancia, 0), _ORDEM_NIVEL[e.nivel]


def idiomas_exigidos(unidades: list["Unidade"], idioma: str, pais_iso: str | None = None) -> list[Exigencia]:
    """Idiomas que a vaga pede, com nível e importância, a partir das frases já segmentadas (a mesma
    leitura de seções da taxonomia: frase de empresa/benefícios não conta).

    - Menção explícita ("Inglês avançado", "Fluent English", "Español intermedio") → origem `descricao`
      (ou `titulo`). Requisito vence desejável; entre frases do mesmo peso, vale o nível mais alto.
    - Vaga escrita em outro idioma que não o do país (inglês numa vaga do Brasil) sem menção a ele →
      exigência inferida, origem `idioma_da_vaga`, nível `nao_informado`.
    - Frase que nega ("inglês não é necessário") não gera exigência.
    """
    achados: dict[str, Exigencia] = {}
    for i, u in enumerate(unidades):
        if u.modo == "contexto" or getattr(u, "formacao", False):
            continue
        for lingua, rx in _MENCAO_IDIOMA.items():
            if not rx.search(u.norm) or _NEGACAO.search(u.norm):
                continue
            if lingua == idioma and _nivel(u.norm) == "nao_informado":
                continue   # "Vaga em português", "descrição em inglês" na língua da própria vaga: não é exigência
            novo = Exigencia(lingua, _nivel(u.norm), u.modo, "titulo" if i == 0 else "descricao", u.original[:160])
            atual = achados.get(lingua)
            if atual is None or _peso(novo) < _peso(atual):   # requisito vence desejável; depois, o nível mais alto
                achados[lingua] = novo
    nativo = idioma_do_pais(pais_iso)
    if nativo and idioma in ("en", "es", "pt") and idioma != nativo and idioma not in achados:
        achados[idioma] = Exigencia(idioma, "nao_informado", "requisito", "idioma_da_vaga")
    return sorted(achados.values(), key=lambda e: e.idioma)


# --------------------------------------------------------------------------- linha e migração
@dataclass
class Classificacao:
    subfamilia: str
    idioma_vaga: str
    idiomas_exigidos: list[Exigencia] = field(default_factory=list)
    origem: dict[str, str] = field(default_factory=dict)

    def colunas(self) -> dict:
        return {"subfamilia": self.subfamilia, "idioma_vaga": self.idioma_vaga,
                "idiomas_exigidos": json.dumps([e.to_dict() for e in self.idiomas_exigidos], ensure_ascii=False),
                "classificacao_versao": CLASSIFICACAO_VERSAO}


def classificar(titulo: str, descricao: str | None, familia: str, tax: "Taxonomy",
                pais_iso: str | None = None) -> Classificacao:
    sub, o_sub = subfamilia(titulo, familia)
    idioma, o_idi = idioma_vaga(titulo, descricao)
    exig = idiomas_exigidos(tax.unidades(titulo, descricao), idioma, pais_iso)
    return Classificacao(sub, idioma, exig, {"subfamilia": o_sub, "idioma_vaga": o_idi})


def _origem(valor) -> dict:
    return json.loads(valor) if isinstance(valor, str) and valor else {}


def atualizar(jobs: pd.DataFrame, tax: "Taxonomy", forcar_subfamilia: set[str] | None = None) -> tuple[pd.DataFrame, int]:
    """Migração incremental: vagas gravadas com outra versão (ou antes dela) ganham subfamília e idiomas.

    Vaga cuja descrição já saiu pela retenção e que já tinha idioma calculado mantém o idioma (recalcular
    só pelo título pioraria o dado). `forcar_subfamilia` = job_ids cuja família mudou (reextrair): a
    subfamília é refeita mesmo na versão atual. Devolve as vagas e quantas foram (re)classificadas."""
    if jobs.empty:
        return jobs, 0
    versao = jobs["classificacao_versao"].fillna("") if "classificacao_versao" in jobs else pd.Series("", jobs.index)
    alvo = jobs.index[(versao != CLASSIFICACAO_VERSAO) | jobs["job_id"].isin(forcar_subfamilia or set())]
    if not len(alvo):
        return jobs, 0
    jobs = jobs.copy()
    for col in ("subfamilia", "idioma_vaga", "idiomas_exigidos", "classificacao_versao", "origem_campos"):
        if col not in jobs:
            jobs[col] = None
        jobs[col] = jobs[col].astype("object")
    for i in alvo:
        j = jobs.loc[i]
        desc = j["descricao"] if isinstance(j["descricao"], str) else None
        oc = _origem(j["origem_campos"])
        sub, oc["subfamilia"] = subfamilia(j["titulo"], j["familia"])
        jobs.at[i, "subfamilia"] = sub
        ja_tinha = isinstance(j["idioma_vaga"], str) and j["idioma_vaga"]
        if desc is not None or not ja_tinha:
            c = classificar(j["titulo"], desc, j["familia"], tax, j["pais_iso"] if isinstance(j["pais_iso"], str) else None)
            col = c.colunas()
            jobs.at[i, "idioma_vaga"], jobs.at[i, "idiomas_exigidos"] = col["idioma_vaga"], col["idiomas_exigidos"]
            oc["idioma_vaga"] = c.origem["idioma_vaga"]
        jobs.at[i, "origem_campos"] = json.dumps(oc)
        jobs.at[i, "classificacao_versao"] = CLASSIFICACAO_VERSAO
    return jobs, len(alvo)

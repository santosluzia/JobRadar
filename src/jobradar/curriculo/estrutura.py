"""Estruturação do currículo por REGRAS (sem IA): seções, experiências, períodos e competências.

Princípios (Etapa 3):
- nada é inventado: todo campo vem do texto, e todo achado de competência guarda a frase original;
- "resultado" é só a frase que JÁ traz número, percentual ou valor no seu texto;
- a interpretação é um ponto de partida: empresa, cargo e período podem sair errados em layouts
  incomuns, então cada experiência traz `revisar` e todo campo pode ser corrigido à mão
  (o campo corrigido entra em `editados` e não é sobrescrito por uma nova interpretação).

Níveis de evidência no currículo (pesos em config/scoring.yaml → curriculo):
- comprovada → competência citada pelo nome numa experiência profissional;
- projeto    → citada num projeto;
- declarada  → só na lista de competências ou no resumo, sem contexto de uso;
- parcial    → só por conceito ("consultas e procedures" → SQL), ou só em formação/certificação
               (curso concluído NÃO é experiência profissional).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..transformations.skills import Taxonomy
from ..transformations.text import normalizar, sha1

NivelCV = Literal["comprovada", "projeto", "declarada", "parcial"]
ORDEM_NIVEL = {"comprovada": 4, "projeto": 3, "declarada": 2, "parcial": 1}

SECOES = {
    "resumo": r"(resumo( profissional)?|sobre( mim)?|perfil( profissional)?|objetivo( profissional)?|summary|about( me)?|profile)",
    "experiencias": r"(experiencias?( profissiona(l|is))?|historico profissional|trajetoria profissional|(work |professional )?experience)",
    "formacao": r"(formacao( academica)?|escolaridade|educacao|education|academic background)",
    "certificacoes": r"(certificac(ao|oes)|certificados?|cursos( complementares)?|licencas e certificados|certifications?|licenses?( (&|and) certifications)?|courses)",
    "projetos": r"(projetos?( pessoais| relevantes| de portfolio)?|portfolio|projects?)",
    "competencias": r"(competencias( tecnicas)?|habilidades( tecnicas)?|conhecimentos( tecnicos)?|tecnologias|ferramentas|stack( tecnica)?|skills|technical skills|hard skills)",
    "idiomas": r"(idiomas?|linguas|languages?)",
}
_SECAO = {k: re.compile(rf"^[\W_]*{v}[\W_]*$") for k, v in SECOES.items()}
_MES = (r"(jan|fev|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|set|sep|out|oct|nov|dez|dec)[^\W\d_]*\.?"
        r"(\s+de)?\s*/?\s*")
_DATA = rf"(({_MES})?\d{{4}}|\d{{1,2}}\s*/\s*\d{{4}})"
_FIM_ATUAL = r"(atual(mente)?|o momento|presente|hoje|present|current|now|em andamento)\b"
_PERIODO = re.compile(rf"(?P<ini>{_DATA})\s*(-|–|—|a|ate|até|to|/)\s*(?P<fim>{_DATA}|{_FIM_ATUAL})")
_MESES = {m: i for i, m in enumerate(["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out",
                                      "nov", "dez"], start=1)}
_MESES.update({"feb": 2, "apr": 4, "may": 5, "aug": 8, "sep": 9, "oct": 10, "dec": 12})
_CARGO = re.compile(r"\b(analista|engenheir[oa]|desenvolvedor[a]?|cientista|estagiari[oa]|estagio|coordenador[a]?|"
                    r"gerente|arquitet[oa]|consultor[a]?|especialista|administrador[a]?|assistente|tecnic[oa]|"
                    r"dba|lider|supervisor[a]?|programador[a]?|auxiliar|trainee|professor[a]?|instrutor[a]?|"
                    r"engineer|analyst|developer|scientist|intern|manager|lead|architect|consultant|specialist|"
                    r"administrator)\b")
_RESULTADO = re.compile(r"(\d+([.,]\d+)?\s*%|r\$\s*\d|\d+\s*(x|vezes)\b|\b\d+([.,]\d+)?\s*(mil|milh(ao|oes)|bi|"
                        r"horas?|h\b|dias?|minutos?|segundos?|tb|gb|registros|usuarios|clientes|pipelines|tabelas)\b|"
                        r"(reduc|reduzi|aument|economi|ganho|melhor)\w*.{0,40}\d)")
def _periodo(texto: str) -> re.Match | None:
    """Período ("03/2022 – atual", "jan 2020 - fev 2022", "março de 2021 até hoje") procurado numa
    cópia em minúsculas com travessão trocado por hífen: as posições batem com o texto original."""
    return _PERIODO.search(re.sub(r"[–—]", "-", texto).lower())


def _sem_periodo(texto: str) -> str:
    m = _periodo(texto)
    return (texto[:m.start()] + " " + texto[m.end():]) if m else texto


def _norm(texto: str) -> str:
    """normalizar() apaga travessões ("2016 – 2020" viraria "2016 2020"): troca por hífen antes."""
    return normalizar(re.sub(r"[–—]", "-", texto))


_MARCADOR = re.compile(r"^\s*[-•▪●◦*]\s*")
_SEPARADOR = re.compile(r"\s+[|•·–—-]\s+|\s*\|\s*|\s+em\s+|\s+at\s+|\s*,\s*(?=[A-ZÀ-Ý])")


class Achado(BaseModel):
    """Competência encontrada no currículo, com a frase que a justifica."""
    model_config = ConfigDict(extra="forbid")
    skill_id: str
    nivel: NivelCV
    metodo: str                      # termo | conceito
    evidencia: str
    termo: str = ""                  # trecho normalizado que casou (para comparar com o vocabulário das vagas)


class Experiencia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    empresa: str = ""
    cargo: str = ""
    inicio: str | None = None        # AAAA-MM ou AAAA
    fim: str | None = None
    atual: bool = False
    responsabilidades: list[str] = Field(default_factory=list)
    resultados: list[str] = Field(default_factory=list)    # frases do SEU texto com número/valor
    competencias: list[Achado] = Field(default_factory=list)
    revisar: bool = False            # empresa/cargo inferidos com pouca segurança
    editados: list[str] = Field(default_factory=list)


class Item(BaseModel):
    """Formação, certificação ou projeto: título + texto original + competências citadas."""
    model_config = ConfigDict(extra="forbid")
    titulo: str
    texto: str = ""
    periodo: str | None = None
    link: str | None = None
    competencias: list[Achado] = Field(default_factory=list)
    editados: list[str] = Field(default_factory=list)


class Curriculo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versao_id: str = ""
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nota: str = ""                                   # descrição da versão ("ajustei Databricks")
    origem: dict[str, str] = Field(default_factory=dict)   # nome, tipo, sha256 do arquivo; versão de origem
    taxonomia_versao: str = ""
    texto: str = ""                                  # texto extraído (só local; permite reinterpretar)
    resumo: str = ""
    experiencias: list[Experiencia] = Field(default_factory=list)
    formacao: list[Item] = Field(default_factory=list)
    certificacoes: list[Item] = Field(default_factory=list)
    projetos: list[Item] = Field(default_factory=list)
    competencias_declaradas: list[Achado] = Field(default_factory=list)
    idiomas: list[str] = Field(default_factory=list)
    nao_classificado: list[str] = Field(default_factory=list)   # linhas fora de seção reconhecida

    def evidencias(self) -> dict[str, list[tuple[str, str, Achado]]]:
        """skill_id → [(seção, onde, achado)], de todas as partes do currículo."""
        saida: dict[str, list[tuple[str, str, Achado]]] = {}
        for e in self.experiencias:
            onde = " · ".join(x for x in (e.cargo, e.empresa) if x) or "experiência"
            for a in e.competencias:
                saida.setdefault(a.skill_id, []).append(("experiencia", onde, a))
        for secao, itens in (("projeto", self.projetos), ("formacao", self.formacao),
                             ("certificacao", self.certificacoes)):
            for it in itens:
                for a in it.competencias:
                    saida.setdefault(a.skill_id, []).append((secao, it.titulo, a))
        for a in self.competencias_declaradas:
            saida.setdefault(a.skill_id, []).append(("competencias", "lista de competências", a))
        return saida

    def niveis(self) -> dict[str, str]:
        """skill_id → melhor nível de evidência no currículo."""
        return {sid: max((a.nivel for *_, a in itens), key=ORDEM_NIVEL.get)
                for sid, itens in self.evidencias().items()}


# ------------------------------------------------------------------ interpretação
def _secao(linha: str) -> str | None:
    n = _norm(linha).rstrip(":")
    if len(n) > 45:
        return None
    return next((k for k, rx in _SECAO.items() if rx.match(n)), None)


def _data(txt: str) -> str | None:
    n = _norm(txt)
    if re.fullmatch(_FIM_ATUAL, n):
        return None
    m = re.search(r"(\d{1,2})\s*/\s*(\d{4})", n)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    ano = re.search(r"\d{4}", n)
    mes = re.match(r"([a-z]{3})", n)
    if ano and mes and mes.group(1) in _MESES:
        return f"{ano.group(0)}-{_MESES[mes.group(1)]:02d}"
    return ano.group(0) if ano else None


def _achados(tax: Taxonomy, titulo: str, texto: str, nivel_termo: NivelCV, nivel_conceito: NivelCV) -> list[Achado]:
    saida = []
    for m in tax.extrair(titulo, texto):
        if m.tipo != "tecnica":
            continue    # comportamentais: só nas sugestões, não como "competência demonstrada"
        saida.append(Achado(skill_id=m.skill_id, nivel=nivel_termo if m.metodo == "termo" else nivel_conceito,
                            metodo=m.metodo, evidencia=m.evidencia, termo=m.termo))
    return saida


def _cabecalho_experiencia(linhas: list[str]) -> tuple[str, str, bool]:
    """Empresa e cargo a partir das linhas curtas em volta do período."""
    partes: list[str] = []
    for l in linhas:
        sem_periodo = _sem_periodo(l)
        sem_periodo = re.sub(r"[()\[\]]", " ", sem_periodo)
        partes += [p.strip(" -–—|·,") for p in _SEPARADOR.split(sem_periodo) if p.strip(" -–—|·,")]
    partes = [p for p in partes if len(p) > 1 and not re.fullmatch(r"[\d\s/.-]+", p)]
    cargos = [p for p in partes if _CARGO.search(normalizar(p))]
    outros = [p for p in partes if p not in cargos]
    cargo = cargos[0] if cargos else (partes[1] if len(partes) > 1 else "")
    empresa = outros[0] if outros else (partes[0] if partes and partes[0] != cargo else "")
    revisar = not cargos or not outros or len(partes) > 3
    return empresa, cargo, revisar


def _experiencias(linhas: list[str], tax: Taxonomy) -> list[Experiencia]:
    """Cada linha com período abre uma experiência; até 2 linhas curtas logo antes (sem marcador)
    são o cabeçalho (empresa/cargo). O resto, até a próxima, é a descrição."""
    marcas = [i for i, l in enumerate(linhas) if _periodo(l)]
    if not marcas:
        return [Experiencia(responsabilidades=linhas, revisar=True,
                            competencias=_achados(tax, "", "\n".join(linhas), "comprovada", "parcial"))] if linhas else []
    blocos = []
    for k, i in enumerate(marcas):
        ini = i
        while ini > (marcas[k - 1] + 1 if k else 0) and i - ini < 2 and len(linhas[ini - 1]) <= 80 \
                and not _MARCADOR.match(linhas[ini - 1]) and not linhas[ini - 1].rstrip().endswith("."):
            ini -= 1
        blocos.append((ini, i))
    saida = []
    for k, (ini, i) in enumerate(blocos):
        fim_bloco = blocos[k + 1][0] if k + 1 < len(blocos) else len(linhas)
        cab = linhas[ini:i + 1]
        corpo = [_MARCADOR.sub("", l).strip() for l in linhas[i + 1:fim_bloco]]
        corpo = [l for l in corpo if l]
        # cabeçalho na linha seguinte ao período ("03/2021 – atual" / "Empresa X")
        if ini == i and corpo and len(corpo[0]) <= 60 and not corpo[0].endswith(".") and len(cab) == 1 \
                and not _sem_periodo(cab[0]).strip(" -–|()"):
            cab.append(corpo.pop(0))
        m = _periodo(linhas[i])
        empresa, cargo, revisar = _cabecalho_experiencia(cab)
        fim_txt = m.group("fim")
        saida.append(Experiencia(
            empresa=empresa, cargo=cargo, inicio=_data(m.group("ini")), fim=_data(fim_txt),
            atual=bool(re.fullmatch(_FIM_ATUAL, _norm(fim_txt))),
            responsabilidades=[l for l in corpo if not _RESULTADO.search(normalizar(l))],
            resultados=[l for l in corpo if _RESULTADO.search(normalizar(l))],
            competencias=_achados(tax, cargo, "\n".join(corpo), "comprovada", "parcial"),
            revisar=revisar))
    return saida


def _itens(linhas: list[str], tax: Taxonomy, nivel_termo: NivelCV, nivel_conceito: NivelCV) -> list[Item]:
    """Um item por linha curta de título; linhas longas ou com marcador continuam o item anterior."""
    itens: list[Item] = []
    for l in linhas:
        limpo = _MARCADOR.sub("", l).strip()
        continua = itens and (_MARCADOR.match(l) or len(limpo) > 90 or limpo[:1].islower())
        if continua:
            itens[-1].texto = (itens[-1].texto + "\n" + limpo).strip()
        else:
            p = _periodo(limpo) or re.search(r"\b(19|20)\d{2}\b", limpo)
            link = re.search(r"(https?://[^\s)\]]+|github\.com/[^\s)\]]+)", limpo)
            itens.append(Item(titulo=limpo[:200], periodo=p.group(0) if p else None,
                              link=link.group(0) if link else None))
    for it in itens:
        it.competencias = _achados(tax, it.titulo, it.texto, nivel_termo, nivel_conceito)
    return itens


def interpretar(texto: str, tax: Taxonomy, origem: dict[str, str] | None = None) -> Curriculo:
    secoes: dict[str, list[str]] = {}
    atual = "cabecalho"
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        s = _secao(linha)
        if s:
            atual = s
            continue
        secoes.setdefault(atual, []).append(linha.strip())
    cv = Curriculo(origem=origem or {}, taxonomia_versao=tax.versao, texto=texto)
    cv.resumo = "\n".join(secoes.get("resumo", []))
    cv.experiencias = _experiencias(secoes.get("experiencias", []), tax)
    cv.formacao = _itens(secoes.get("formacao", []), tax, "parcial", "parcial")
    cv.certificacoes = _itens(secoes.get("certificacoes", []), tax, "parcial", "parcial")
    cv.projetos = _itens(secoes.get("projetos", []), tax, "projeto", "parcial")
    declaradas = "\n".join(secoes.get("competencias", []) + secoes.get("resumo", []))
    cv.competencias_declaradas = _achados(tax, "", declaradas, "declarada", "parcial") if declaradas else []
    cv.idiomas = secoes.get("idiomas", [])
    # cabeçalho = nome e contatos: não são guardados como dado estruturado; o resto sem seção vai para revisão
    cv.nao_classificado = secoes.get("cabecalho", [])[3:]
    cv.versao_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + sha1(texto)[:6]
    return cv


def reaplicar_edicoes(novo: Curriculo, anterior: Curriculo) -> Curriculo:
    """Nova interpretação do mesmo texto não apaga o que você corrigiu à mão: experiências com a
    mesma empresa+cargo (ou mesma posição) herdam os campos listados em `editados`."""
    chave = lambda e: (normalizar(e.empresa), normalizar(e.cargo))  # noqa: E731
    antigas = {chave(e): e for e in anterior.experiencias if e.editados}
    for i, e in enumerate(novo.experiencias):
        velha = antigas.get(chave(e)) or (anterior.experiencias[i] if i < len(anterior.experiencias)
                                          and anterior.experiencias[i].editados else None)
        if velha:
            for campo in velha.editados:
                setattr(e, campo, getattr(velha, campo))
            e.editados = list(velha.editados)
    return novo


def recalcular_competencias(e: Experiencia, texto: str, tax: Taxonomy) -> Experiencia:
    """Depois de uma correção manual da descrição: separa de novo atividades × resultados e
    refaz as competências a partir do texto que VOCÊ escreveu."""
    linhas = [_MARCADOR.sub("", l).strip() for l in texto.splitlines() if l.strip()]
    e.responsabilidades = [l for l in linhas if not _RESULTADO.search(normalizar(l))]
    e.resultados = [l for l in linhas if _RESULTADO.search(normalizar(l))]
    e.competencias = _achados(tax, e.cargo, "\n".join(linhas), "comprovada", "parcial")
    return e

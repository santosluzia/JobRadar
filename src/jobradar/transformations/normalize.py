"""Normalização: título, senioridade, modalidade, local e família do cargo.

Cada valor inferido registra sua origem (fonte | titulo | descricao | nao_informada),
para que o dashboard e as análises diferenciem dado observado de dado inferido.
"""
from __future__ import annotations

import re

from ..models import Familia, Modalidade, Senioridade
from .text import normalizar

SENIORIDADE = [
    (Senioridade.estagio, r"\b(estagio|estagiari[oa]|internship|intern|aprendiz)\b"),
    (Senioridade.lideranca, r"\b(lead|lider|lideranca|head|gerente|manager|coordenador[a]?|principal|staff|tech lead)\b"),
    # "master" = nível acima de sênior em consultorias (ex.: CI&T), exceto "master data management".
    (Senioridade.senior, r"\b(senior|sr|especialista|specialist|iii)\b|\bmaster\b(?!\s+data\s+management)"),
    (Senioridade.pleno, r"\b(pleno|pl|mid|mid-level|ii)\b"),
    (Senioridade.junior, r"\b(junior|jr|trainee|entry level|entry-level)\b|\bi$"),
]
SENIORIDADE_DESCRICAO = r"(nivel|senioridade|seniority|level)\s*[:\-]?\s*(junior|pleno|senior|jr|pl|sr)\b"
MAPA_DESC = {"junior": Senioridade.junior, "jr": Senioridade.junior, "pleno": Senioridade.pleno,
             "pl": Senioridade.pleno, "senior": Senioridade.senior, "sr": Senioridade.senior}

MODALIDADE_TEXTO = [
    (Modalidade.hibrido, r"\bhibrid[oa]\b|\bhybrid\b"),
    (Modalidade.remoto, r"\b(100% )?remot[oa]\b|\bhome ?office\b|\bremote\b|\banywhere\b"),
    (Modalidade.presencial, r"\bpresencial\b|\bon-?site\b"),
]

FAMILIA_TITULO = [
    (Familia.analytics_engineering, r"analytics engineer|engenheir[oa] de analytics"),
    (Familia.engenharia_dados, r"engenheir[oa] de (big )?dados|engenharia de dados|data engineer|big data engineer|dataops"),
    (Familia.desenvolvimento_dados, r"desenvolvedor[a]? (de )?(dados|etl|bi)\b|(etl|bi|data) developer"),
    (Familia.governanca_qualidade, r"governanca( e [a-z ]+?)? de dados|data governance|qualidade de dados|data quality|data steward|integracao de dados|\bmdm\b"),
    (Familia.analise_dados, r"analista de (dados|bi)|data analyst|business intelligence|analista de business intelligence"),
]
SKILLS_NUCLEO_ENG = {"spark", "airflow", "etl", "databricks", "dbt", "data_lake", "data_warehouse",
                     "kafka", "data_factory", "snowflake"}
TITULO_GENERICO = r"\b(engenheir[oa]|engineer|desenvolvedor[a]?|developer|analista|programador[a]?)\b"

UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA",
    "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}
UFS = set(UF.values())


def senioridade(titulo: str, descricao: str | None) -> tuple[Senioridade, str]:
    t = normalizar(titulo)
    for valor, padrao in SENIORIDADE:
        if re.search(padrao, t):
            return valor, "titulo"
    m = re.search(SENIORIDADE_DESCRICAO, normalizar(descricao))
    if m:
        return MAPA_DESC[m.group(2)], "descricao"
    return Senioridade.nao_informada, "nao_informada"


def modalidade(bruta: str | None, titulo: str, descricao: str | None) -> tuple[Modalidade, str]:
    if bruta in Modalidade._value2member_map_:
        return Modalidade(bruta), "fonte"
    for origem, texto in (("titulo", titulo), ("descricao", (descricao or "")[:3000])):
        n = normalizar(texto)
        for valor, padrao in MODALIDADE_TEXTO:
            if re.search(padrao, n):
                return valor, origem
    return Modalidade.nao_informada, "nao_informada"


def uf(state: str | None, location_raw: str | None) -> str | None:
    for texto in (state, location_raw):
        n = normalizar(texto)
        if not n:
            continue
        if n.upper() in UFS:
            return n.upper()
        for nome, sigla in sorted(UF.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{nome}\b", n):
                return sigla
        m = re.search(r"\b([a-z]{2})\b$", n)
        if m and m.group(1).upper() in UFS:
            return m.group(1).upper()
    return None


def familia(titulo: str, skills_ids: set[str]) -> tuple[Familia, str]:
    t = normalizar(titulo)
    for valor, padrao in FAMILIA_TITULO:
        if re.search(padrao, t):
            return valor, "titulo"
    # Não descarta só porque o título não diz "dados": olha as responsabilidades.
    if re.search(TITULO_GENERICO, t) and len(skills_ids & SKILLS_NUCLEO_ENG) >= 3:
        return Familia.engenharia_dados, "descricao"
    return Familia.outra, "titulo"

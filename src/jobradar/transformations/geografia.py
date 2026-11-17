"""Geografia da vaga: país (ISO 3166-1 alfa-2), UF, região e cidade normalizadas, e a parte de local das
chaves de deduplicação.

Antes, o local da vaga era só a UF brasileira. Fora do Brasil a UF é nula, então duas vagas da mesma
empresa e do mesmo título em Lisboa e no Porto caíam na mesma chave e viravam "duplicata". E siglas de
país lidas como UF ("Madrid, ES" → Espírito Santo) contaminavam a distribuição por estado.

Regras (docs/adr/0010-geografia-e-deduplicacao-internacional.md):
- país, nesta ordem: campo da fonte (nome ou código ISO) → nome de país no local → cidade conhecida →
  UF brasileira → não informado. Mais de um país no local ("Brazil or Mexico") = não informado;
- UF só existe quando o país é o Brasil ou não foi identificado (comportamento anterior);
- a parte de local da chave NÃO muda para vagas do Brasil ou sem país: continua sendo a UF (ou vazio).
  Assim as chaves já gravadas do Brasil ficam idênticas; só as vagas de outros países ganham chave nova,
  com país e cidade (ou região).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd

from . import normalize
from .text import normalizar

# Suba quando mudar uma regra: as vagas gravadas com versão diferente são recalculadas na próxima execução.
GEOGRAFIA_VERSAO = "1.0.0"

# Nomes normalizados (minúsculas, sem acento) em português, inglês e espanhol.
PAISES = {
    "brasil": "BR", "brazil": "BR",
    "portugal": "PT",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "mexico": "MX",
    "uruguai": "UY", "uruguay": "UY",
    "peru": "PE",
    "equador": "EC", "ecuador": "EC",
    "bolivia": "BO",
    "paraguai": "PY", "paraguay": "PY",
    "venezuela": "VE",
    "costa rica": "CR",
    "panama": "PA",
    "guatemala": "GT",
    "republica dominicana": "DO", "dominican republic": "DO",
    "estados unidos": "US", "united states": "US", "eua": "US", "usa": "US",
    "canada": "CA",
    "espanha": "ES", "spain": "ES", "espana": "ES",
    "reino unido": "GB", "united kingdom": "GB",
    "alemanha": "DE", "germany": "DE",
    "franca": "FR", "france": "FR",
    "irlanda": "IE", "ireland": "IE",
    "holanda": "NL", "paises baixos": "NL", "netherlands": "NL",
    "polonia": "PL", "poland": "PL",
    "india": "IN",
}
CODIGOS = set(PAISES.values())
# Cidades que identificam o país sozinhas (sem ambiguidade com cidades brasileiras ou de outros países).
# Valor: (país, nome canônico da cidade).
CIDADES = {
    "lisboa": ("PT", "lisboa"), "lisbon": ("PT", "lisboa"),
    "braga": ("PT", "braga"), "coimbra": ("PT", "coimbra"),
    "buenos aires": ("AR", "buenos aires"),
    "santiago de chile": ("CL", "santiago"),
    "bogota": ("CO", "bogota"), "medellin": ("CO", "medellin"),
    "ciudad de mexico": ("MX", "cidade do mexico"), "cidade do mexico": ("MX", "cidade do mexico"),
    "mexico city": ("MX", "cidade do mexico"), "cdmx": ("MX", "cidade do mexico"),
    "monterrey": ("MX", "monterrey"),
    "montevideo": ("UY", "montevideu"), "montevideu": ("UY", "montevideu"),
}
# Grafias da mesma cidade (vale para qualquer país).
ALIAS_CIDADE = {nome: canonica for nome, (_, canonica) in CIDADES.items()} | {"sao paulo city": "sao paulo"}
# Segmentos do local que não são cidade.
NAO_CIDADE = re.compile(r"^(remot[eo]|remota|home ?office|hibrid[oa]|hybrid|presencial|on-?site|anywhere|"
                        r"latam|latin america|america latina|latinoamerica|south america|americas|global|worldwide|"
                        r"brazil remote|remote brazil)$")

_RX_PAISES = re.compile(r"\b(" + "|".join(sorted((re.escape(p) for p in PAISES), key=len, reverse=True)) + r")\b")
_RX_CIDADES = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in CIDADES), key=len, reverse=True)) + r")\b")
_UF_NOMES = set(normalize.UF)


@dataclass(frozen=True)
class Local:
    pais_iso: str | None
    uf: str | None
    regiao: str | None        # UF no Brasil; estado/província normalizado nos demais países
    cidade_norm: str | None
    origem_pais: str          # fonte | local_raw | cidade | uf | multiplos | nao_informada


def _pais_do_campo(country: str | None) -> str | None:
    if not country or not country.strip():
        return None
    bruto = country.strip()
    if len(bruto) == 2 and bruto.upper() in CODIGOS:
        return bruto.upper()
    return PAISES.get(normalizar(bruto))


def _cidade(city: str | None, location_raw: str | None) -> str | None:
    if city and city.strip():
        n = normalizar(city)
        return ALIAS_CIDADE.get(n, n) or None
    for seg in re.split(r"[,;|/()]|\s[-–]\s", normalizar(location_raw)):
        seg = seg.strip(" -–.")
        # Segmento com nome de país ("Brazil", "Brazil or Mexico") não é cidade, salvo cidade conhecida
        # que contém o nome do país ("Ciudad de México").
        if not seg or len(seg) <= 2 or NAO_CIDADE.match(seg) or (_RX_PAISES.search(seg) and seg not in CIDADES):
            continue
        if seg in _UF_NOMES and seg not in ("sao paulo", "rio de janeiro"):
            continue   # "Minas Gerais" é estado, não cidade; São Paulo e Rio são as duas coisas
        return ALIAS_CIDADE.get(seg, seg)
    return None


def localizar(country: str | None, state: str | None, city: str | None, location_raw: str | None) -> Local:
    pais, origem = _pais_do_campo(country), "fonte"
    if pais is None:
        texto = " | ".join(normalizar(x) for x in (location_raw, state, city) if x)
        achados = {PAISES[m] for m in _RX_PAISES.findall(texto)}
        if len(achados) == 1:
            pais, origem = achados.pop(), "local_raw"
        elif len(achados) > 1:
            pais, origem = None, "multiplos"
        else:
            cidades = {CIDADES[m][0] for m in _RX_CIDADES.findall(texto)}
            if len(cidades) == 1:
                pais, origem = cidades.pop(), "cidade"
            else:
                origem = "nao_informada"
    uf = normalize.uf(state, location_raw) if pais in (None, "BR") else None
    if pais is None and uf and origem != "multiplos":
        pais, origem = "BR", "uf"
    if pais in (None, "BR"):
        regiao = uf
    else:
        n = normalizar(state) if state else ""
        regiao = n if n and n not in PAISES and len(n) > 2 else None
    return Local(pais, uf, regiao, _cidade(city, location_raw), origem)


def chave_local(pais_iso: str | None, uf: str | None, regiao: str | None, cidade_norm: str | None) -> str:
    """Parte de local das chaves de deduplicação. Brasil ou país não identificado: a UF (como sempre foi).
    Outros países: país + cidade (ou região), para Lisboa e Porto não virarem a mesma vaga."""
    if pais_iso in (None, "BR") or (isinstance(pais_iso, float) and pd.isna(pais_iso)):
        return uf if isinstance(uf, str) else ""
    detalhe = cidade_norm if isinstance(cidade_norm, str) and cidade_norm else (regiao if isinstance(regiao, str) else "")
    return f"{pais_iso}:{detalhe}"


def chave_remota(pais_iso: str | None) -> str:
    """Local da chave de vaga remota: o mesmo anúncio remoto repetido por estado é uma vaga só, mas
    remoto no Brasil e remoto em Portugal são vagas diferentes."""
    return "remoto" if not isinstance(pais_iso, str) or pais_iso == "BR" else f"remoto:{pais_iso}"


def atualizar(jobs: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Migração incremental do histórico: recalcula a geografia (e a chave alternativa) das vagas gravadas
    com outra versão das regras, a partir das colunas que a silver já guarda (pais, uf, cidade, local_raw).
    Não depende da bronze. Devolve as vagas e quantas tiveram a chave alternativa alterada."""
    from .silver import chave_alternativa
    if jobs.empty:
        return jobs, 0
    alvo = jobs.index[jobs["geografia_versao"].fillna("") != GEOGRAFIA_VERSAO]
    if not len(alvo):
        return jobs, 0
    jobs = jobs.copy()
    for col in ("pais_iso", "regiao", "cidade_norm", "geografia_versao", "uf", "chave_alternativa", "origem_campos"):
        jobs[col] = jobs[col].astype("object")
    mudou = 0
    for i in alvo:
        j = jobs.loc[i]
        txt = lambda v: v if isinstance(v, str) else None   # noqa: E731
        loc = localizar(txt(j["pais"]), txt(j["uf"]), txt(j["cidade"]), txt(j["local_raw"]))
        chave = chave_alternativa(txt(j["empresa"]), j["titulo"] or "",
                                  chave_local(loc.pais_iso, loc.uf, loc.regiao, loc.cidade_norm))
        if chave != j["chave_alternativa"]:
            mudou += 1
        oc = json.loads(j["origem_campos"]) if isinstance(j["origem_campos"], str) and j["origem_campos"] else {}
        oc["pais"] = loc.origem_pais
        jobs.at[i, "pais_iso"], jobs.at[i, "uf"], jobs.at[i, "regiao"] = loc.pais_iso, loc.uf, loc.regiao
        jobs.at[i, "cidade_norm"], jobs.at[i, "chave_alternativa"] = loc.cidade_norm, chave
        jobs.at[i, "origem_campos"], jobs.at[i, "geografia_versao"] = json.dumps(oc), GEOGRAFIA_VERSAO
    return jobs, mudou

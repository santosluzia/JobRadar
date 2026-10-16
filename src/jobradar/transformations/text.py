"""Utilitários de texto e URL."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

# Parâmetros de rastreamento: removidos só da URL usada para deduplicar.
# A URL original (com tudo) é preservada para a candidatura.
TRACKING_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid|ref|refid|source|jobboardsource|trk|origin)$", re.I)


def normalizar(texto: str | None) -> str:
    """Minúsculas, sem acentos, espaços simples."""
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def html_para_texto(html: str | None, limite: int = 20000) -> str | None:
    if not html:
        return None
    # Greenhouse entrega HTML com entidades escapadas (&lt;p&gt;); duas passadas resolvem.
    texto = BeautifulSoup(html, "html.parser").get_text("\n")
    if "<" in texto and ">" in texto:
        texto = BeautifulSoup(texto, "html.parser").get_text("\n")
    linhas = [re.sub(r"[ \t]+", " ", l).strip() for l in texto.splitlines()]
    plano = "\n".join(l for l in linhas if l)
    return plano[:limite] or None


def url_canonica(url: str) -> str:
    partes = urlsplit(url.strip())
    query = sorted((k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True)
                   if not TRACKING_PARAMS.match(k))
    caminho = partes.path.rstrip("/") or "/"
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), caminho, urlencode(query), ""))


def sha1(*partes: str | None) -> str:
    return hashlib.sha1("|".join(p or "" for p in partes).encode()).hexdigest()

"""Descoberta assistida: qual ATS e qual quadro estão por trás de uma URL de carreiras.

Duas etapas, nesta ordem:
1. `detectar_na_url(url)`: só olha o endereço (nenhuma requisição). Serve quando a pessoa já colou o link
   do quadro (boards.greenhouse.io/x, jobs.lever.co/x, jobs.ashbyhq.com/x, jobs.smartrecruiters.com/X…).
2. `detectar_no_html(html)`: procura os mesmos padrões nos endereços que aparecem na página de carreiras
   da empresa (links, iframes e scripts de incorporação do quadro).

`buscar_pagina(url)` baixa UMA página pública, informada pela pessoa, e só se o robots.txt do site
permitir. Não segue links, não faz login, não insiste em página que pede CAPTCHA: é uma consulta pontual,
não um rastreador. O resultado nunca entra direto na coleta: vira candidata no catálogo e passa pela
verificação (`verificacao.py`) e pela aprovação de alguém (ADR 0012).

Só os padrões de endereço que as próprias plataformas usam nos links públicos das vagas. Gupy e Workday
são reconhecidos para registro, mas não têm coletor por empresa (ADR 0009 e 0011).
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ..collectors.base import USER_AGENT

# Trechos de caminho que são rota da plataforma, não nome de quadro.
_RESERVADOS = {"embed", "api", "v0", "v1", "jobs", "job", "postings", "posting-api", "job-board", "job_board",
               "job_app", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "careers", "apply"}
_GUPY_RESERVADOS = {"portal", "www", "login", "api", "app", "help", "ajuda", "blog", "status"}   # não são empresas
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_URL_NO_HTML = re.compile(r"""(?:https?:)?//[^\s"'<>\\)]+""", re.I)


@dataclass(frozen=True)
class Deteccao:
    ats: str                 # greenhouse | lever | ashby | smartrecruiters | gupy | workday
    board: str | None        # identificador do quadro (None quando a plataforma não tem coletor por quadro)
    url: str                 # endereço onde o padrão foi achado
    regiao: str | None = None   # "eu" quando o quadro está no ambiente europeu da plataforma (sem coletor)


def _slug(trecho: str | None) -> str | None:
    if not trecho:
        return None
    t = trecho.strip()
    return t if _SLUG.match(t) and t.lower() not in _RESERVADOS else None


def detectar_na_url(url: str) -> Deteccao | None:
    """ATS e quadro a partir do endereço, sem requisição. None se o endereço não for de um ATS conhecido."""
    if url.startswith("//"):
        url = "https:" + url
    try:
        partes = urlsplit(url.strip())
    except ValueError:
        return None
    host = (partes.hostname or "").lower()
    caminho = [p for p in partes.path.split("/") if p]
    query = parse_qs(partes.query)
    primeiro = caminho[0] if caminho else None

    # Greenhouse: boards / job-boards (+ .eu), API pública e o código de incorporação (?for=token)
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io",
                "job-boards.eu.greenhouse.io"):
        regiao = "eu" if ".eu." in host else None
        if primeiro == "embed":
            board = _slug((query.get("for") or [None])[0])
        else:
            board = _slug(primeiro)
        return Deteccao("greenhouse", board, url, regiao) if board else None
    if host == "boards-api.greenhouse.io" and len(caminho) >= 3 and caminho[:2] == ["v1", "boards"]:
        board = _slug(caminho[2])
        return Deteccao("greenhouse", board, url) if board else None

    # Lever: jobs.lever.co/<slug> e api.lever.co/v0/postings/<slug> (+ ambiente europeu)
    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        board = _slug(primeiro)
        return Deteccao("lever", board, url, "eu" if ".eu." in host else None) if board else None
    if host in ("api.lever.co", "api.eu.lever.co") and len(caminho) >= 3 and caminho[:2] == ["v0", "postings"]:
        board = _slug(caminho[2])
        return Deteccao("lever", board, url, "eu" if ".eu." in host else None) if board else None

    # Ashby: jobs.ashbyhq.com/<quadro> e a Public Job Posting API
    if host == "jobs.ashbyhq.com":
        board = _slug(primeiro)
        return Deteccao("ashby", board, url) if board else None
    if host == "api.ashbyhq.com" and len(caminho) >= 3 and caminho[:2] == ["posting-api", "job-board"]:
        board = _slug(caminho[2])
        return Deteccao("ashby", board, url) if board else None

    # SmartRecruiters: páginas públicas das vagas e a Posting API (companyIdentifier)
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
        board = _slug(primeiro)
        return Deteccao("smartrecruiters", board, url) if board else None
    if host == "api.smartrecruiters.com" and len(caminho) >= 3 and caminho[:2] == ["v1", "companies"]:
        board = _slug(caminho[2])
        return Deteccao("smartrecruiters", board, url) if board else None

    # Sem coletor por empresa: só registra a plataforma
    if host.endswith(".gupy.io") and host.count(".") == 2 and host.split(".")[0] not in _GUPY_RESERVADOS:
        return Deteccao("gupy", host.split(".")[0], url)
    if host.endswith(".myworkdayjobs.com"):
        return Deteccao("workday", None, url)
    return None


def detectar_no_html(conteudo: str, base: str | None = None) -> list[Deteccao]:
    """Quadros de ATS citados na página (links, iframes, scripts). Um por (ats, board), na ordem em que
    aparecem."""
    vistos: dict[tuple[str, str | None], Deteccao] = {}
    for bruto in _URL_NO_HTML.findall(html_lib.unescape(conteudo or "")):
        url = urljoin(base, bruto) if base and bruto.startswith("//") else bruto
        d = detectar_na_url(url.rstrip(".,;"))
        if d and (d.ats, d.board) not in vistos:
            vistos[(d.ats, d.board)] = d
    return list(vistos.values())


class PaginaIndisponivel(RuntimeError):
    pass


def conferir_robots(url: str, client: httpx.Client) -> None:
    """Levanta PaginaIndisponivel se o robots.txt do site não permitir a página. Sem robots.txt (404) =
    permitido. Erro ao ler (5xx, rede) ou robots.txt bloqueado (401/403) = não arrisca: o RFC 9309 trata
    5xx como "tudo proibido"."""
    p = urlsplit(url)
    try:
        resp = client.get(f"{p.scheme}://{p.netloc}/robots.txt")
    except httpx.HTTPError as e:
        raise PaginaIndisponivel(f"não foi possível ler o robots.txt do site ({e}); a página não foi consultada") from e
    if resp.status_code in (401, 403) or resp.status_code >= 500:
        raise PaginaIndisponivel(f"o robots.txt do site respondeu HTTP {resp.status_code} para o JobRadar; "
                                 "a página não foi consultada")
    if resp.status_code >= 400:
        return
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    if not rp.can_fetch(USER_AGENT, url):
        raise PaginaIndisponivel("o robots.txt do site não permite a consulta automática desta página")


def buscar_pagina(url: str, client: httpx.Client | None = None) -> tuple[str, str]:
    """(HTML, endereço final após redirecionamentos) de UMA página pública de carreiras. Levanta
    PaginaIndisponivel se o robots.txt não permitir, se a página pedir login/CAPTCHA (401/403/429) ou se
    não for HTML."""
    if not url.startswith("https://"):
        raise PaginaIndisponivel("use o endereço https:// da página de carreiras")
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    conferir_robots(url, client)
    try:
        resp = client.get(url)
    except httpx.HTTPError as e:
        raise PaginaIndisponivel(f"falha ao abrir a página: {e}") from e
    if resp.status_code in (401, 403, 429):
        raise PaginaIndisponivel(f"HTTP {resp.status_code}: a página pede login, bloqueia robôs ou limita acesso")
    if resp.status_code >= 400:
        raise PaginaIndisponivel(f"HTTP {resp.status_code} em {url}")
    if "html" not in resp.headers.get("content-type", "html").lower():
        raise PaginaIndisponivel("o endereço não devolveu uma página HTML")
    return resp.text[:2_000_000], str(resp.url)


def detectar(url: str, client: httpx.Client | None = None) -> list[Deteccao]:
    """Endereço do quadro → resposta direta. Página da empresa → busca a página (com robots.txt) e procura
    o quadro nela. O redirecionamento final também conta (carreiras.empresa.com → jobs.lever.co/empresa)."""
    direta = detectar_na_url(url)
    if direta:
        return [direta]
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    conteudo, final = buscar_pagina(url, client)
    pelo_redirecionamento = detectar_na_url(final)
    achados = detectar_no_html(conteudo, final)
    if pelo_redirecionamento and all((d.ats, d.board) != (pelo_redirecionamento.ats, pelo_redirecionamento.board)
                                     for d in achados):
        achados.insert(0, pelo_redirecionamento)
    return achados

"""Verificação de um quadro de ATS antes de a empresa entrar na coleta (ADR 0012).

A verificação usa o PRÓPRIO coletor da plataforma, com o mesmo filtro de título da coleta diária: se ela
passa, a coleta lê o quadro do mesmo jeito. Mede o que importa para a curadoria:
- o quadro respondeu e veio inteiro (serve de evidência para encerrar vagas);
- quantas vagas há no total e quantas passam no filtro de dados;
- em que países estão as vagas de dados (Brasil, Portugal e América Latina são o alvo);
- o nome que a API informa para a empresa (Greenhouse e SmartRecruiters), para comparar com o catálogo.

Cada verificação vira uma linha em `meta/empresas_verificacoes`: só dados públicos e operacionais
(plataforma, quadro, contagens, nome da empresa), como `meta/board_runs`.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from ..collectors.ats import COLETORES_ATS
from ..storage import Lake
from ..transformations.geografia import localizar
from ..transformations.text import normalizar

TABELA = "meta/empresas_verificacoes"
# Alvo de cobertura do projeto: Brasil, Portugal e América Latina (ISO 3166-1 alfa-2).
LATAM = {"AR", "BO", "BR", "CL", "CO", "CR", "CU", "DO", "EC", "GT", "HN", "MX", "NI", "PA", "PE", "PR", "PY",
         "SV", "UY", "VE"}
PAISES_ALVO = LATAM | {"PT"}
VALIDADE_DIAS = 7   # verificação mais velha que isso não serve para aprovar

# Onde cada API informa o nome da empresa (Lever e Ashby não informam).
_NOME_API = {
    "greenhouse": lambda r: r.get("company_name"),
    "smartrecruiters": lambda r: (r.get("company") or {}).get("name"),
}


@dataclass
class Verificacao:
    ats: str
    board: str
    em: datetime
    ok: bool = False
    completo: bool = False
    vagas_listadas: int = 0
    vagas_dados: int = 0          # passaram no filtro de título da coleta (titulo_contem da fonte)
    vagas_brasil: int = 0         # entre as de dados
    vagas_alvo: int = 0           # entre as de dados: Brasil, Portugal ou América Latina
    paises: dict[str, int] = field(default_factory=dict)   # vagas de dados por país ("?" = não identificado)
    nome_api: str | None = None
    erro: str | None = None
    requisicoes: int = 0
    duracao_s: float = 0.0
    empresa_id: str | None = None

    def pendencias(self, nome_catalogo: str | None = None, nome_fixo: bool = False) -> list[str]:
        """O que impede a aprovação. Lista vazia = pode ser aprovada."""
        p = []
        if not self.ok:
            p.append(f"o quadro não respondeu: {self.erro or 'erro desconhecido'}")
            return p
        if not self.completo:
            p.append("o quadro veio vazio ou incompleto (não serve de evidência para encerrar vagas)")
        if self.vagas_dados == 0:
            p.append("nenhuma vaga passa no filtro de título de dados")
        elif self.vagas_alvo == 0:
            p.append("nenhuma vaga de dados no Brasil, em Portugal ou na América Latina")
        if nome_catalogo and nome_diverge(self.nome_api, nome_catalogo) and not nome_fixo:
            p.append(f"a API informa a empresa como '{self.nome_api}', diferente de '{nome_catalogo}': "
                     "confira o quadro e, se ele for mesmo da empresa, use nome_fixo: true no catálogo")
        return p

    def linha(self) -> dict[str, Any]:
        d = asdict(self)
        d["paises"] = json.dumps(self.paises, ensure_ascii=False, sort_keys=True)
        return d


def nome_diverge(nome_api: str | None, nome_catalogo: str) -> bool:
    """Nomes diferentes de verdade: nenhum contém o outro, sem acento, caixa e pontuação ("XP Inc." e
    "XP" não divergem; "LinkedIn Job Wrapping" e "Artefact" divergem)."""
    if not nome_api:
        return False
    a, b = (normalizar(x).replace(".", "").replace(",", "").strip() for x in (nome_api, nome_catalogo))
    return bool(a and b) and a not in b and b not in a


def verificar(ats: str, board: str, cfg_fonte: dict[str, Any], client: httpx.Client | None = None,
              empresa_id: str | None = None, agora: datetime | None = None) -> Verificacao:
    """Lê o quadro com o coletor da plataforma e resume o resultado. Não grava nada."""
    v = Verificacao(ats=ats, board=board, em=agora or datetime.now(timezone.utc), empresa_id=empresa_id)
    cls = COLETORES_ATS.get(ats)
    if cls is None:
        v.erro = f"a plataforma '{ats}' não tem coletor"
        return v
    cfg = {**cfg_fonte, "empresas": [board], "nomes": {}}
    coletor = cls(cfg, client=client)
    t0 = time.monotonic()
    res = coletor.collect([])
    v.duracao_s = round(time.monotonic() - t0, 2)
    v.requisicoes = res.requests
    m = res.por_quadro.get(board) or {}
    v.ok, v.completo = bool(m.get("ok")), bool(m.get("completo"))
    v.vagas_listadas, v.vagas_dados = int(m.get("vagas_listadas") or 0), len(res.records)
    v.erro = m.get("erro") or ("; ".join(res.errors) if res.errors else None)
    paises: Counter[str] = Counter()
    for r in res.records:
        try:
            raw = coletor.to_raw_job(r)
        except Exception:   # registro que não vira RawJob: conta como país não identificado
            paises["?"] += 1
            continue
        loc = localizar(raw.country, raw.state, raw.city, raw.location_raw)
        # sem país mas com UF ("Recife, PE"): Brasil, como na chave de deduplicação (ADR 0010)
        paises[loc.pais_iso or ("BR" if loc.uf else "?")] += 1
    v.paises = dict(paises.most_common())
    v.vagas_brasil = paises.get("BR", 0)
    v.vagas_alvo = sum(n for p, n in paises.items() if p in PAISES_ALVO)
    nomes = Counter(n for r in res.records if (n := (_NOME_API.get(ats) or (lambda _: None))(r)))
    v.nome_api = nomes.most_common(1)[0][0] if nomes else None
    return v


def registrar(lake: Lake, verificacoes: list[Verificacao]) -> None:
    if verificacoes:
        lake.append(TABELA, pd.DataFrame([v.linha() for v in verificacoes]))


def ultima(lake: Lake, ats: str, board: str) -> Verificacao | None:
    """Verificação mais recente de um quadro (o identificador é comparado sem caixa)."""
    tab = lake.read(TABELA)
    if tab.empty:
        return None
    tab = tab[(tab["ats"] == ats) & (tab["board"].astype(str).str.lower() == board.lower())]
    if tab.empty:
        return None
    d = tab.sort_values("em").iloc[-1].to_dict()
    d["paises"] = json.loads(d["paises"]) if isinstance(d.get("paises"), str) and d["paises"] else {}
    d["em"] = pd.Timestamp(d["em"]).to_pydatetime()
    campos = Verificacao.__dataclass_fields__
    return Verificacao(**{k: (None if (not isinstance(val, (dict, list)) and pd.isna(val)) else val)
                          for k, val in d.items() if k in campos})


def vencida(v: Verificacao, hoje: date) -> bool:
    return (hoje - v.em.date()).days > VALIDADE_DIAS

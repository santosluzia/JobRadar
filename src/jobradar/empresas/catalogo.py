"""Catálogo de empresas monitoradas (`config/empresas.yaml`), validado por Pydantic.

O catálogo é a fonte das empresas consultadas nos ATS (Greenhouse, Lever): só entram na coleta as de
`status: ativa`. Ele guarda o que foi CURADO (nome, país, segmento, plataforma, identificador do quadro,
data da última verificação); o que é medido a cada execução (última coleta bem-sucedida, vagas listadas)
fica em `meta/board_runs` e é cruzado na leitura (`jobradar empresas listar`).

Estar no catálogo não significa ter vaga aberta: significa que o quadro da empresa existe e é lido.
Decisão e campos: docs/adr/0009-catalogo-de-empresas.md.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Plataformas conhecidas. Só as de COLETORES têm coletor; as demais podem aparecer em empresas
# candidatas (descoberta assistida) e ficam fora da coleta até haver integração pública viável.
Ats = Literal["greenhouse", "lever", "ashby", "smartrecruiters", "gupy", "workday", "outro"]
COLETORES = ("greenhouse", "lever", "ashby", "smartrecruiters")
Status = Literal["candidata", "ativa", "pausada", "descartada"]
Segmento = Literal["banco", "fintech", "servicos_financeiros", "seguros", "consultoria", "tecnologia", "telecom",
                   "varejo", "industria", "saude", "educacao", "energia", "logistica", "imobiliario", "jogos",
                   "midia", "governo", "outro"]

# Endereços públicos de cada plataforma com coletor (os mesmos dos coletores em collectors/ats/).
API_URL = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
    "lever": "https://api.lever.co/v0/postings/{board}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{board}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{board}/postings",
}
PAGINA_ATS = {   # só as conferidas (o link das vagas aponta para elas)
    "greenhouse": "https://boards.greenhouse.io/{board}",
    "lever": "https://jobs.lever.co/{board}",
    "ashby": "https://jobs.ashbyhq.com/{board}",
}


class Empresa(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    nome: str = Field(min_length=2)
    pais: str = Field(pattern=r"^[A-Z]{2}$")          # ISO 3166-1 alfa-2 da sede/operação monitorada
    segmento: Segmento
    site: str | None = None                            # site institucional
    pagina_carreiras: str | None = None                # página de carreiras da própria empresa
    ats: Ats
    board: str | None = None                           # token (Greenhouse), slug (Lever), nome do quadro (Ashby)
                                                       # ou companyIdentifier (SmartRecruiters)
    status: Status
    verificada_em: date | None = None                  # última vez que o quadro foi conferido por alguém
    origem: Literal["manual", "descoberta"] = "manual"
    # Usa `nome` na coleta mesmo quando a API informa outro (ex.: quadro do Greenhouse publicado em nome de
    # um parceiro). Padrão False: o nome continua vindo da fonte, como antes, e o histórico não muda.
    nome_fixo: bool = False
    observacoes: str | None = None

    @field_validator("site", "pagina_carreiras")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("URL precisa começar com https://")
        return v

    @model_validator(mode="after")
    def _ativa_coletavel(self) -> "Empresa":
        if self.status == "ativa":
            if self.ats not in COLETORES:
                raise ValueError(f"{self.id}: ATS '{self.ats}' não tem coletor; use status candidata ou pausada")
            if not self.board:
                raise ValueError(f"{self.id}: empresa ativa precisa do identificador do quadro (board)")
            if self.verificada_em is None:
                raise ValueError(f"{self.id}: empresa ativa precisa de verificada_em")
        return self

    @property
    def api_url(self) -> str | None:
        modelo = API_URL.get(self.ats)
        return modelo.format(board=self.board) if modelo and self.board else None

    @property
    def pagina_ats(self) -> str | None:
        modelo = PAGINA_ATS.get(self.ats)
        return modelo.format(board=self.board) if modelo and self.board else None


class Catalogo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: int = 1
    empresas: list[Empresa] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unicos(self) -> "Catalogo":
        ids = [e.id for e in self.empresas]
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        if repetidos:
            raise ValueError(f"ids repetidos no catálogo: {repetidos}")
        quadros = [(e.ats, e.board) for e in self.empresas if e.board]
        repetidos_q = sorted({f"{a}/{b}" for a, b in quadros if quadros.count((a, b)) > 1})
        if repetidos_q:
            raise ValueError(f"quadro repetido no catálogo: {repetidos_q}")
        return self

    def quadros_ativos(self, ats: str) -> list[str]:
        """Identificadores dos quadros a coletar numa plataforma, na ordem do arquivo."""
        return [e.board for e in self.empresas if e.status == "ativa" and e.ats == ats and e.board]

    def por_quadro(self, ats: str, board: str) -> Empresa | None:
        alvo = _chave(board)
        return next((e for e in self.empresas if e.ats == ats and e.board and _chave(e.board) == alvo), None)


def _chave(board: str) -> str:
    return re.sub(r"\s+", "", board).lower()


def carregar_catalogo(dados: dict[str, Any] | None) -> Catalogo:
    """Valida o conteúdo de `config/empresas.yaml`. Arquivo ausente = catálogo vazio."""
    return Catalogo.model_validate(dados or {})

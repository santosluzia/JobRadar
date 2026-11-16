"""Operações de alto nível usadas pela CLI e pelo painel (mesma regra nos dois)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..settings import Settings
from ..transformations.skills import Taxonomy
from ..transformations.text import sha1
from . import versoes
from .estrutura import Curriculo, interpretar, reaplicar_edicoes
from .leitura import ler


def importar(conteudo: bytes, nome: str, tax: Taxonomy, home: Path | None = None, nota: str = "",
             guardar_original: bool = False, retencao: dict[str, Any] | None = None) -> Curriculo:
    """Lê, interpreta e salva uma NOVA versão. Correções manuais da versão anterior são reaplicadas
    nas experiências equivalentes (mesma empresa e cargo)."""
    if nome.lower().endswith(".json"):
        return salvar_edicao(Curriculo.model_validate_json(conteudo.decode("utf-8")), tax, home, nota, retencao)
    t = ler(conteudo, nome)
    cv = interpretar(t.texto, tax, {"nome": Path(nome).name, "tipo": t.tipo, "sha256": t.sha256})
    anterior = versoes.carregar(home=home)
    if anterior:
        cv = reaplicar_edicoes(cv, anterior)
        cv.origem["anterior"] = anterior.versao_id
    cv.nota = nota
    versoes.salvar(cv, home, conteudo if guardar_original else None)
    _reter(home, retencao)
    return cv


def _reter(home: Path | None, retencao: dict[str, Any] | None) -> None:
    """Etapa 8: a regra de retenção roda a cada versão nova (docs/privacidade.md)."""
    from ..retencao import limpar
    limpar(home, retencao)


def salvar_edicao(cv: Curriculo, tax: Taxonomy, home: Path | None = None, nota: str = "",
                  retencao: dict[str, Any] | None = None) -> Curriculo:
    """Versão nova a partir de uma edição manual (painel ou JSON exportado)."""
    novo = cv.model_copy(deep=True)
    novo.origem = {**cv.origem, "anterior": cv.versao_id, "tipo_versao": "edicao"}
    agora = datetime.now(timezone.utc)
    novo.criado_em = agora
    novo.versao_id = agora.strftime("%Y%m%dT%H%M%S") + "-" + sha1(novo.model_dump_json())[:6]
    novo.nota = nota or cv.nota
    novo.taxonomia_versao = tax.versao
    versoes.salvar(novo, home)
    _reter(home, retencao)
    return novo


def diagnostico(s: Settings, objetivo_id: str | None = None, versao_id: str | None = None,
                home: Path | None = None, salvar: bool = False, agora: datetime | None = None) -> list[dict[str, Any]]:
    """Diagnóstico + sugestões por objetivo (um item por objetivo, ou só o pedido)."""
    from ..analytics import market
    from ..scoring import Profile
    from ..storage import Lake
    from .diagnostico import diagnosticar
    from .sugestoes import gerar

    tax = Taxonomy(s.skills)
    lake = Lake(s.lake)
    snap = market.carregar(lake, tax.config.extracao.gold_hibrida)
    scores = lake.read("gold/job_scores")
    from ..evolucao.progresso import perfil_efetivo
    perfil = perfil_efetivo(s.profile, lake)
    cv = versoes.carregar(versao_id, home)
    agora = agora or datetime.now(timezone.utc)
    saida = []
    for p in ([perfil.para(objetivo_id)] if objetivo_id else perfil.por_objetivo()):
        d = diagnosticar(snap, scores, p, cv, tax, s.scoring, s.filtros, agora)
        d["sugestoes"] = [x.to_dict() for x in gerar(d, cv, p, tax)]
        if salvar:
            versoes.salvar_diagnostico(d, home)
        saida.append(d)
    return saida

"""JobRadar — Seu Radar Profissional (Etapa 5): e-mail diário com 4 blocos.

1. O que mudou no mercado    vagas novas, competências em alta (só com amostra), tecnologias novas
                             (só da taxonomia validada: a fila de curadoria é ruidosa demais para e-mail),
                             requisitos que se repetem, volume contra a semana anterior;
2. Relação com o seu perfil  do que as vagas pedem: o que você demonstra, o que precisa de melhor
                             apresentação, lacunas e novas exigências (do plano da Etapa 4);
3. Oportunidade              uma vaga concreta em que falta pouco, e o que falta é prioridade sua;
4. Recomendação do dia       UMA ação, que respeita o progresso e não se repete (nao_repetir_dias).

Regras de qualidade (5.2): seção sem conteúdo relevante é omitida; tendência só com amostra mínima nas
duas janelas; tecnologia só entra com ≥ 2 vagas (nunca por uma vaga só); item já apontado nos últimos
dias não volta sem mudança; o cabeçalho diz o objetivo, o período e quantas vagas foram analisadas.

Privacidade: o conteúdo é montado no CI a partir do lake privado (perfil, progresso e, se você
compartilhou, o RESUMO de níveis do currículo). Só contagens vão para o log. Configuração em
`<lake>/private/radar.yaml` (privada). Histórico em `private/radar_envios`.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..analytics import market
from ..analytics.selection import FUSO
from ..settings import Settings
from ..storage import Lake
from . import email as em

log = logging.getLogger(__name__)
CAMINHO_CONFIG = Path("private") / "radar.yaml"
DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
TURNOS = ["madrugada", "manha", "tarde", "noite"]
ROTULO_ACAO = {"estudar": "Estudar um conceito", "atividade": "Desenvolver uma pequena atividade",
               "projeto": "Atualizar um projeto", "curriculo": "Melhorar uma descrição do currículo",
               "documentar": "Documentar uma experiência"}


class SemanalConfig(BaseModel):
    """Relatório Semanal de Evolução Profissional (Etapa 6): e-mail separado do Radar."""
    model_config = ConfigDict(extra="forbid")
    ativo: bool = True
    dia: Literal["seg", "ter", "qua", "qui", "sex", "sab", "dom"] = "seg"
    horario: str = Field(default="12:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    objetivo: str | None = None                  # vazio = o mesmo do Radar
    limite_itens: int = Field(default=8, ge=3, le=15)

    @property
    def turno(self) -> int:
        h, m = map(int, self.horario.split(":"))
        return ((h * 60 + m + 30) // 360) % 4


class MensalConfig(BaseModel):
    """Diagnóstico mensal (Etapa 7): o retrato é gravado sempre; o e-mail, se `ativo`."""
    model_config = ConfigDict(extra="forbid")
    ativo: bool = True
    dia: int = Field(default=1, ge=1, le=28)
    horario: str = Field(default="12:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @property
    def turno(self) -> int:
        h, m = map(int, self.horario.split(":"))
        return ((h * 60 + m + 30) // 360) % 4


class RadarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ativo: bool = True
    horario: str = Field(default="06:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")   # precisão: turno de 6 h
    dias_semana: list[Literal["seg", "ter", "qua", "qui", "sex", "sab", "dom"]] = Field(default_factory=lambda: list(DIAS))
    frequencia: Literal["diaria", "dias_uteis", "semanal"] = "diaria"
    objetivo: str | None = None                  # id do objetivo do perfil; vazio = o primeiro
    limite_itens: int = Field(default=5, ge=1, le=15)
    nao_repetir_dias: int = Field(default=7, ge=1, le=60)
    janela_tendencia_dias: int = Field(default=14, ge=7, le=60)
    janela_base_dias: int = Field(default=28, ge=7, le=120)
    min_variacao_pp: float = Field(default=5.0, ge=1)
    semanal: SemanalConfig = Field(default_factory=SemanalConfig)
    mensal: MensalConfig = Field(default_factory=MensalConfig)

    @field_validator("dias_semana")
    @classmethod
    def _ao_menos_um(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("informe ao menos um dia da semana")
        return v

    @property
    def turno(self) -> int:
        h, m = map(int, self.horario.split(":"))
        return ((h * 60 + m + 30) // 360) % 4


def carregar_config(lake_root: Path) -> RadarConfig:
    p = Path(lake_root) / CAMINHO_CONFIG
    if not p.exists():
        return RadarConfig()
    return RadarConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")) or {})


def turno_de(agora: datetime) -> int:
    """Mesmos turnos do workflow: limites 30 min antes da hora cheia (00, 06, 12 e 18 em SP)."""
    local = agora.astimezone(FUSO)
    return ((local.hour * 60 + local.minute + 30) // 360) % 4


def devido(cfg: RadarConfig, agora: datetime, turno: int, envios: pd.DataFrame, objetivo_id: str) -> tuple[bool, str]:
    if not cfg.ativo:
        return False, "Radar desativado (private/radar.yaml)"
    if turno != cfg.turno:
        return False, f"fora do horário configurado ({cfg.horario}, turno {TURNOS[cfg.turno]})"
    local = (agora + timedelta(minutes=30)).astimezone(FUSO)
    dia = DIAS[local.weekday()]
    if dia not in cfg.dias_semana:
        return False, f"{dia} não está em dias_semana"
    if cfg.frequencia == "dias_uteis" and local.weekday() >= 5:
        return False, "fim de semana (frequência: dias úteis)"
    ok = envios[(envios["status"] == "enviado") & (envios["objetivo_id"] == objetivo_id)] if not envios.empty else envios
    if not ok.empty and (ok["data"] == local.date().isoformat()).any():
        return False, "Radar de hoje já enviado"
    if cfg.frequencia == "semanal" and not ok.empty:
        semana = local.isocalendar()[:2]
        if any(pd.Timestamp(d).isocalendar()[:2] == semana for d in ok["data"]):
            return False, "Radar desta semana já enviado (frequência: semanal)"
    return True, "ok"


# ------------------------------------------------------------------ conteúdo
def _recentes(envios: pd.DataFrame, objetivo_id: str, agora: datetime, dias: int) -> pd.DataFrame:
    if envios.empty:
        return envios
    e = envios[(envios["status"] == "enviado") & (envios["objetivo_id"] == objetivo_id)]
    return e[pd.to_datetime(e["enviado_em"], utc=True) >= agora - timedelta(days=dias)]


def _chaves_recentes(recentes: pd.DataFrame) -> set[str]:
    chaves: set[str] = set()
    for c in recentes.get("chaves", pd.Series(dtype=str)).dropna():
        chaves.update(json.loads(c))
    return chaves


def escolher_acao(plano: dict[str, Any], conteudo_cfg: dict[str, Any], envios_recentes: pd.DataFrame,
                  com_resumo_cv: bool) -> dict[str, Any] | None:
    """UMA ação. Considera o progresso (quem está em estudo recebe prática, não "estude"), não repete
    (tipo, competência) recomendados no período `nao_repetir_dias` e evita repetir o tipo de ontem."""
    from ..evolucao.plano import ConteudoConfig
    texto = ConteudoConfig.model_validate(conteudo_cfg or {}).competencias
    ja = set(zip(envios_recentes.get("acao_tipo", []), envios_recentes.get("acao_skill", [])))
    ultimo_tipo = envios_recentes.sort_values("enviado_em")["acao_tipo"].iloc[-1] if len(envios_recentes) else None
    vezes = envios_recentes["acao_skill"].value_counts().to_dict() if len(envios_recentes) else {}
    cands = []
    for i in plano["prioritarias"]:
        if i["progresso"] in (None, "nao_iniciada"):
            topicos = (texto.get(i["skill_id"]).estudar if texto.get(i["skill_id"]) else []) or [i["nome"]]
            topico = topicos[vezes.get(i["skill_id"], 0) % len(topicos)]       # tópico diferente a cada vez
            cands.append(("estudar", i, i["prioridade"],
                          f"Estude {topico} ({i['nome']}). {i['nome']} é pedida em {i['pct']:.0f}% das vagas-alvo "
                          f"e é uma das suas prioridades."))
    for i in plano["classes"]["em_desenvolvimento"]:
        projeto = (texto.get(i["skill_id"]).projeto if texto.get(i["skill_id"]) else "") or "um exercício curto"
        if i["progresso"] == "em_estudo":
            cands.append(("atividade", i, i["prioridade"] * 0.9,
                          f"Faça uma pequena prática de {i['nome']}: comece por um pedaço de “{projeto}”."))
        elif i["progresso"] == "em_pratica":
            cands.append(("projeto", i, i["prioridade"] * 0.9,
                          f"Atualize e publique o projeto de {i['nome']}; depois registre o link no progresso "
                          "como “demonstrada em projeto”."))
        elif i["progresso"] is None and i["nivel_curriculo"] == "parcial" and com_resumo_cv:
            cands.append(("curriculo", i, i["prioridade"] * 0.8,
                          f"Se você já usou {i['nome']} no trabalho, cite pelo nome na experiência do currículo: "
                          "hoje ele só aparece de forma indireta."))
    if com_resumo_cv:
        for i in plano["classes"]["declarada_sem_evidencia"]:
            if not i["baixa_relevancia"]:
                cands.append(("documentar", i, i["pct"] / 100 * 0.8,
                              f"Documente no currículo onde você usou {i['nome']} ({i['pct']:.0f}% das vagas-alvo "
                              "pedem): o perfil diz que você tem, o currículo ainda não mostra."))
    pontuados = []
    for tipo, i, pontos, frase in cands:
        if (tipo, i["skill_id"]) in ja:
            continue                                        # não repete a mesma ação no período
        pontuados.append((pontos * (0.75 if tipo == ultimo_tipo else 1.0), tipo, i, frase))
    if not pontuados:
        return None
    pontos, tipo, i, frase = max(pontuados, key=lambda x: x[0])
    return {"tipo": tipo, "rotulo": ROTULO_ACAO[tipo], "skill_id": i["skill_id"], "nome": i["nome"], "texto": frase,
            "base": {"pct_vagas": i["pct"], "prioridade": i["prioridade"], "progresso": i["progresso"]}}


def montar(s: Settings, agora: datetime, cfg: RadarConfig, envios: pd.DataFrame) -> dict[str, Any]:
    from ..curriculo.diagnostico import _alvo
    from ..evolucao.plano import montar as montar_plano
    from ..evolucao.progresso import perfil_efetivo
    from ..evolucao.resumo_cv import carregar as carregar_resumo
    from ..transformations.skills import Taxonomy

    lake = Lake(s.lake)
    tax = Taxonomy(s.skills)
    nomes = {k.id: k.nome for k in tax.skills}
    snap = market.carregar(lake, tax.config.extracao.gold_hibrida)
    scores = lake.read("gold/job_scores")
    perfil = perfil_efetivo(s.profile, lake)
    objetivo = cfg.objetivo or (perfil.objetivos[0].id if perfil.objetivos else "")
    p = perfil.para(objetivo) if perfil.objetivos else perfil
    resumo = carregar_resumo(s.lake)
    plano = montar_plano(snap, scores, p, resumo, tax, s.scoring, s.filtros, s.evolucao,
                         lake.read("private/study_progress"), agora)
    recentes = _recentes(envios, p.objetivo_id, agora, cfg.nao_repetir_dias)
    vistos = _chaves_recentes(_recentes(envios, p.objetivo_id, agora, 3))
    min_n = int(s.scoring["recomendacoes"]["min_vagas_janela"])
    lim = cfg.limite_itens
    c = snap.canonicas
    primeira = pd.to_datetime(c["primeira_observacao"], utc=True)
    alvo_total = _alvo(c, p, s.filtros, agora, 3650)                 # mesmas famílias/senioridades, sem janela
    chaves: list[str] = []

    # ---- vagas novas do objetivo (mesma seleção do e-mail, com o score DESTE objetivo)
    vagas, _ = em.selecionar(s, agora)
    familias = set(p.familias)
    sc_obj = scores[scores["objetivo_id"] == p.objetivo_id].set_index("job_id")["score"] if not scores.empty else pd.Series(dtype=int)
    novas = []
    for v in vagas:
        if familias and v.job["familia"] not in familias:
            continue
        if v.job["job_id"] in sc_obj.index:
            v.score = int(sc_obj.loc[v.job["job_id"]])
        novas.append(v)
    novas.sort(key=lambda v: (v.secao != em.DO_DIA, -v.score))

    # ---- referência para os blocos 2 e 3: vagas novas, ou a última semana se forem poucas
    ids_ref = {v.job["job_id"] for v in novas}
    ref_rotulo = f"{len(novas)} vaga(s) nova(s) de hoje"
    if len(ids_ref) < 3:
        ids_ref = set(c.loc[alvo_total & (primeira >= agora - timedelta(days=7)), "job_id"])
        ref_rotulo = f"{len(ids_ref)} vaga(s)-alvo dos últimos 7 dias"
    sk = snap.skills
    sk_ref = sk[sk["job_id"].isin(ids_ref)]

    # ---- bloco 1: mercado
    jt, jb = cfg.janela_tendencia_dias, cfg.janela_base_dias
    m_rec = alvo_total & (primeira >= agora - timedelta(days=jt))
    m_base = alvo_total & (primeira < agora - timedelta(days=jt)) & (primeira >= agora - timedelta(days=jt + jb))
    n_rec, n_base = int(m_rec.sum()), int(m_base.sum())
    tendencias, aviso_tend = [], None
    if n_rec >= min_n and n_base >= min_n:
        fr = market.frequencia_competencias(snap, m_rec).set_index("skill_id")["percentual"]
        fb = market.frequencia_competencias(snap, m_base).set_index("skill_id")["percentual"]
        delta = (fr.reindex(fr.index.union(fb.index), fill_value=0) - fb.reindex(fr.index.union(fb.index), fill_value=0))
        for sid, d in delta.sort_values(ascending=False).items():
            if d < cfg.min_variacao_pp or sid not in nomes:
                break
            chave = f"tend:{sid}:{round(d)}"
            if any(k.startswith(f"tend:{sid}:") and abs(int(k.split(':')[2]) - round(d)) < 2 for k in vistos):
                continue                                   # já apontada há pouco, sem mudança relevante
            tendencias.append({"skill_id": sid, "nome": nomes[sid], "de": float(fb.get(sid, 0)),
                               "para": float(fr.get(sid, 0)), "delta_pp": round(float(d), 1)})
            chaves.append(chave)
            if len(tendencias) >= lim:
                break
        if not tendencias:
            aviso_tend = (f"Nenhuma competência variou {cfg.min_variacao_pp:.0f} p.p. ou mais entre os últimos {jt} dias "
                          f"({n_rec} vagas) e os {jb} anteriores ({n_base} vagas).")
    else:
        aviso_tend = (f"Amostra insuficiente para tendência: {n_rec} vagas nos últimos {jt} dias e {n_base} nos "
                      f"{jb} anteriores (mínimo {min_n} em cada).")

    m7 = alvo_total & (primeira >= agora - timedelta(days=7))
    m30 = alvo_total & (primeira < agora - timedelta(days=7)) & (primeira >= agora - timedelta(days=37))
    f7 = market.frequencia_competencias(snap, m7).set_index("skill_id")["vagas"]
    f30 = market.frequencia_competencias(snap, m30).set_index("skill_id")["vagas"]
    novas_tec = [{"nome": nomes[sid], "vagas": int(n), "validada": True} for sid, n in f7.items()
                 if sid in nomes and n >= 2 and f30.get(sid, 0) == 0 and f"nova:{sid}" not in vistos][:lim]
    chaves += [f"nova:{sid}" for sid, n in f7.items() if sid in nomes and n >= 2 and f30.get(sid, 0) == 0]
    novas_tec = novas_tec[:lim]

    req = sk_ref[sk_ref["importancia"] == "requisito"].groupby("skill_id")["job_id"].nunique().sort_values(ascending=False)
    repetidos = [{"skill_id": sid, "nome": nomes.get(sid, sid), "vagas": int(n), "de": len(ids_ref)}
                 for sid, n in req.items() if n >= 2 and sid in nomes][:lim]
    volume = {"ultimos_7": int(m7.sum()), "anteriores_7": int((alvo_total & (primeira < agora - timedelta(days=7))
                                                              & (primeira >= agora - timedelta(days=14))).sum())}

    # ---- bloco 2: relação com o perfil
    itens = {i["skill_id"]: i for itens_ in plano["classes"].values() for i in itens_}
    pedidas = sk_ref.groupby("skill_id")["job_id"].nunique()

    def grupo(classes: tuple[str, ...]) -> list[dict[str, Any]]:
        out = [{"skill_id": sid, "nome": nomes.get(sid, sid), "vagas": int(n), "de": len(ids_ref)}
               for sid, n in pedidas.sort_values(ascending=False).items()
               if sid in itens and itens[sid]["classe"] in classes]
        return out[:lim]
    demonstra = grupo(("consolidada", "comprovada_profissional", "demonstrada_projeto"))
    apresentar = grupo(("declarada_sem_evidencia",)) if resumo else []
    lacunas = grupo(("prioritaria",))
    tendencia_ids = {t["skill_id"] for t in tendencias}
    novas_exig = [x for x in grupo(("baixa_relevancia", "em_desenvolvimento"))
                  if x["vagas"] >= 3 or x["skill_id"] in tendencia_ids][:lim]

    # ---- bloco 3: oportunidade — falta pouco, e o que falta é prioridade
    prioritarias = {i["skill_id"] for i in plano["prioritarias"]}
    fortes = {sid for sid, i in itens.items() if i["classe"] in ("consolidada", "comprovada_profissional", "demonstrada_projeto")}
    req_por_vaga = sk_ref[sk_ref["importancia"] == "requisito"].groupby("job_id")["skill_id"].apply(set).to_dict()
    oportunidade = None
    jobs_idx = c.set_index("job_id")
    for jid in sorted(ids_ref, key=lambda j: -int(sc_obj.get(j, 0))):
        reqs = {x for x in req_por_vaga.get(jid, set()) if x in nomes}
        falta = reqs - fortes
        if 1 <= len(falta) <= 2 and falta & prioritarias and reqs & fortes and jid in jobs_idx.index:
            j = jobs_idx.loc[jid]
            oportunidade = {"job_id": jid, "titulo": j["titulo"], "url": j["url"],
                            "empresa": j["empresa"] if isinstance(j["empresa"], str) else None,
                            "score": int(sc_obj.get(jid, 0)) if jid in sc_obj.index else None,
                            "tem": sorted(nomes[x] for x in reqs & fortes), "falta": sorted(nomes[x] for x in falta),
                            "falta_prioritaria": sorted(nomes[x] for x in falta & prioritarias)}
            break

    # ---- bloco 4
    acao = escolher_acao(plano, s.evolucao, recentes, resumo is not None)
    return {
        "objetivo_id": p.objetivo_id, "objetivo": plano["objetivo"], "gerado_em": agora.isoformat(),
        "vagas_alvo": plano["vagas_alvo"], "janela_dias": int(s.scoring["curriculo"]["janela_dias"]),
        "referencia": ref_rotulo, "com_resumo_cv": resumo is not None,
        "vagas_novas": novas, "tendencias": tendencias, "aviso_tendencia": aviso_tend,
        "janelas_tendencia": {"recente": jt, "base": jb, "n_recente": n_rec, "n_base": n_base},
        "novas_tecnologias": novas_tec, "requisitos_repetidos": repetidos, "volume": volume,
        "demonstra": demonstra, "apresentar": apresentar, "lacunas": lacunas, "novas_exigencias": novas_exig,
        "oportunidade": oportunidade, "acao": acao, "chaves": chaves, "nomes": nomes,
    }


# ------------------------------------------------------------------ renderização
def _paragrafo(html_: str) -> str:
    return f'<tr><td style="padding:0 20px 10px;font-size:14px;line-height:21px;color:{em.MARINHO}">{html_}</td></tr>'


def _caixa(html_: str, cor: str = em.LINHA, fundo: str = "#ffffff") -> str:
    return (f'<tr><td style="padding:0 20px 12px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            f'style="background:{fundo};border:1px solid {cor};border-radius:14px"><tr><td style="padding:16px 18px;'
            f'font-size:14px;line-height:21px;color:{em.MARINHO}">{html_}</td></tr></table></td></tr>')


def renderizar(r: dict[str, Any], agora: datetime, fontes: list[dict[str, Any]], cartoes: int = 10,
               alertas: list[str] | None = None) -> tuple[str, str, str]:
    e = html.escape
    local = agora.astimezone(FUSO)
    dia = local.strftime("%d/%m/%Y")
    n_novas = len([v for v in r["vagas_novas"] if v.secao == em.DO_DIA])
    assunto = f"JobRadar — Seu Radar Profissional · {dia} · {r['objetivo']}: {n_novas} vaga(s) nova(s)"
    linhas: list[str] = []
    txt: list[str] = [assunto, "", f"Objetivo: {r['objetivo']} · {r['vagas_alvo']} vagas-alvo analisadas nos últimos "
                      f"{r['janela_dias']} dias · referência dos blocos 2 e 3: {r['referencia']}", ""]

    # Bloco 1
    linhas.append(em._titulo_secao("1 · O que mudou no mercado"))
    txt.append("== 1. O que mudou no mercado ==")
    vol = r["volume"]
    pontos = [f"<b>{vol['ultimos_7']}</b> vagas-alvo nos últimos 7 dias (eram {vol['anteriores_7']} nos 7 anteriores)."]
    if r["tendencias"]:
        pontos.append("Ganharam frequência (" + f"{r['janelas_tendencia']['recente']} dias × "
                      f"{r['janelas_tendencia']['base']} anteriores): " + ", ".join(
                          f"<b>{e(t['nome'])}</b> {t['de']:.0f}% → {t['para']:.0f}%" for t in r["tendencias"]) + ".")
    elif r["aviso_tendencia"]:
        pontos.append(e(r["aviso_tendencia"]))
    if r["novas_tecnologias"]:
        pontos.append("Novas nas vagas desta semana: " + ", ".join(
            f"{e(t['nome'])} ({t['vagas']} vagas{'' if t['validada'] else ', termo ainda não validado'})"
            for t in r["novas_tecnologias"]) + ".")
    if r["requisitos_repetidos"]:
        pontos.append("Requisitos que se repetem: " + ", ".join(
            f"{e(x['nome'])} ({x['vagas']} de {x['de']})" for x in r["requisitos_repetidos"]) + ".")
    linhas.append(_caixa("<br>".join(pontos)))
    txt += [p.replace("<b>", "").replace("</b>", "") for p in pontos] + [""]
    if r["vagas_novas"]:
        h, t = em.bloco_vagas(r["vagas_novas"], agora, r["nomes"], cartoes)
        linhas += h
        txt += t + [""]

    # Bloco 2
    blocos2 = [("Você já demonstra", r["demonstra"]), ("Precisam de melhor apresentação no currículo", r["apresentar"]),
               ("Lacunas prioritárias", r["lacunas"]), ("Novas exigências que merecem atenção", r["novas_exigencias"])]
    if any(itens for _, itens in blocos2):
        linhas.append(em._titulo_secao("2 · Como isso se relaciona com o seu perfil", f"Base: {r['referencia']}."))
        txt.append(f"== 2. Como isso se relaciona com o seu perfil (base: {r['referencia']}) ==")
        partes = []
        for titulo, itens in blocos2:
            if itens:
                lista = ", ".join(f"{x['nome']} ({x['vagas']} de {x['de']})" for x in itens)
                partes.append(f"<b>{e(titulo)}:</b> {e(lista)}")
                txt.append(f"{titulo}: {lista}")
        if not r["com_resumo_cv"]:
            partes.append(f'<span style="color:{em.TEXTO_SUAVE};font-size:12px">Sem o resumo do currículo, esta parte '
                          "usa só o perfil e o progresso (jobradar curriculo compartilhar-resumo).</span>")
        linhas.append(_caixa("<br>".join(partes)))
        txt.append("")

    # Bloco 3
    o = r["oportunidade"]
    if o:
        linhas.append(em._titulo_secao("3 · Oportunidade identificada"))
        corpo = (f'<a href="{e(o["url"], quote=True)}" style="color:{em.MARINHO};font-weight:600">{e(o["titulo"])}</a>'
                 f' — {e(o["empresa"] or "empresa n/i")}' + (f' · aderência {o["score"]}' if o["score"] is not None else "")
                 + f"<br>Você demonstra <b>{e(', '.join(o['tem']))}</b>; falta <b>{e(', '.join(o['falta']))}</b>"
                 + f", que está entre as suas prioridades ({e(', '.join(o['falta_prioritaria']))}).")
        linhas.append(_caixa(corpo, em.VIOLETA_VIVO, "#faf9ff"))
        txt += ["== 3. Oportunidade identificada ==", f"{o['titulo']} — {o['empresa'] or 'empresa n/i'}",
                f"Você demonstra {', '.join(o['tem'])}; falta {', '.join(o['falta'])}.", o["url"], ""]

    # Bloco 4
    a = r["acao"]
    linhas.append(em._titulo_secao("4 · Minha recomendação do dia"))
    if a:
        linhas.append(_caixa(f'<span style="font-family:{em.MONO};font-size:11px;letter-spacing:.12em;'
                             f'text-transform:uppercase;color:{em.VIOLETA}">{e(a["rotulo"])}</span><br>{e(a["texto"])}',
                             em.VIOLETA, em.LILAS))
        txt += ["== 4. Recomendação do dia ==", f"[{a['rotulo']}] {a['texto']}"]
    else:
        linhas.append(_paragrafo("Nenhuma ação nova hoje: as do plano já foram recomendadas nos últimos dias. "
                                 "Siga com a que estiver em andamento."))
        txt += ["== 4. Recomendação do dia ==", "Nenhuma ação nova hoje."]

    destaque = (r["oportunidade"] or {}).get("titulo") or (a or {}).get("texto") or "seu radar de hoje"
    subtitulo = (f"{em.DIAS_SEMANA[local.weekday()].capitalize()}, {dia} · {r['objetivo']} · "
                 f"{r['vagas_alvo']} vagas-alvo em {r['janela_dias']} dias")
    rodape = ("Período: vagas novas de ontem e hoje; mercado nos últimos 7 dias e tendências só com amostra mínima. "
              "Associação entre competências não é causa; aderência não é previsão de contratação. "
              "Configure horário, dias, objetivo e frequência em private/radar.yaml.")
    if alertas:     # Etapa 8: saúde da operação (só agregados), para você saber se o radar está cego
        rodape = "⚠️ Saúde do JobRadar: " + "; ".join(alertas) + ". " + rodape
    corpo = em.moldura(assunto, destaque[:140], "JobRadar · Seu Radar Profissional",
                       f"{n_novas} vaga{'s' if n_novas != 1 else ''} nova{'s' if n_novas != 1 else ''} · {r['objetivo']}",
                       subtitulo, linhas, fontes, rodape=e(rodape))
    txt += ["", rodape]
    return assunto, corpo, "\n".join(txt)


# ------------------------------------------------------------------ envio
def enviar(s: Settings, agora: datetime, run_id: str, turno: int | None = None, dry_run: bool = False,
           forcar: bool = False, html_out: Path | None = None) -> dict[str, Any]:
    """Monta, envia e registra. Devolve só contagens (é o que vai para o log)."""
    lake = Lake(s.lake)
    cfg = carregar_config(s.lake)
    envios = lake.read("private/radar_envios")
    from ..evolucao.progresso import perfil_efetivo
    perfil = perfil_efetivo(s.profile, lake)
    objetivo_id = cfg.objetivo or (perfil.objetivos[0].id if perfil.objetivos else "")
    turno = turno_de(agora) if turno is None else turno
    ok, motivo = devido(cfg, agora, turno, envios, objetivo_id)
    if not ok and not forcar and not dry_run:
        return {"enviado": False, "motivo": motivo}
    r = montar(s, agora, cfg, envios)
    from ..analytics import saude
    try:
        al = saude.alertas(saude.indicadores(lake, agora, s.sources.get("saude")), s.sources.get("saude"))
    except Exception:       # o monitoramento nunca impede o Radar
        al = []
    assunto, corpo, texto = renderizar(r, agora, market.fontes(market.carregar(lake)),
                                       int(s.sources.get("notificacoes", {}).get("cartoes", 10)), al)
    resumo = {"vagas": len(r["vagas_novas"]), "tendencias": len(r["tendencias"]), "oportunidade": bool(r["oportunidade"]),
              "acao": bool(r["acao"])}
    if dry_run:
        if html_out:
            Path(html_out).write_text(corpo, encoding="utf-8")
        return {"enviado": False, "motivo": "prévia (dry-run): nada enviado nem registrado", **resumo}
    local = (agora + timedelta(minutes=30)).astimezone(FUSO)
    a = r["acao"] or {}
    linha = {"data": local.date().isoformat(), "objetivo_id": r["objetivo_id"], "enviado_em": agora, "run_id": run_id,
             "assunto": assunto, "vagas": len(r["vagas_novas"]), "acao_tipo": a.get("tipo"), "acao_skill": a.get("skill_id"),
             "acao_texto": a.get("texto"), "chaves": json.dumps(r["chaves"], ensure_ascii=False)}
    try:
        em.enviar_smtp(s, assunto, corpo, texto)
    except Exception as ex:          # nada de vaga é registrado: volta no próximo turno do mesmo dia
        lake.append("private/radar_envios", pd.DataFrame([{**linha, "status": "falha", "erro": type(ex).__name__}]))
        raise
    em.registrar(lake, r["vagas_novas"], run_id, agora)
    lake.append("private/radar_envios", pd.DataFrame([{**linha, "status": "enviado", "erro": None}]))
    return {"enviado": True, "motivo": "ok", **resumo}

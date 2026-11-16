"""Plano "Minha Evolução Profissional" por objetivo: prioridade explicável, 7 classes e recomendações.

- Prioridade (4.1) = soma ponderada de 7 fatores entre 0 e 1 (pesos em config/scoring.yaml → evolucao),
  sempre com a decomposição. Crescimento só conta quando há amostra nos dois períodos.
- NÃO recomenda todas as lacunas: só as `max_prioritarias` de maior prioridade e acima de
  `prioridade_minima`, com amostra suficiente. As demais aparecem com o motivo de terem ficado de fora.
- Classes (4.2) sem sobreposição, combinando perfil efetivo (declarado + progresso), currículo e progresso.
- Recomendações (4.3): números das vagas-alvo + conteúdo de config/evolucao.yaml, que é SUGESTÃO
  EDITÁVEL (rotulada assim), não dado observado.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ..analytics import coocorrencia, market
from ..analytics.market import Snapshot
from ..recommendations import recomendar
from ..scoring import Profile
from ..transformations.silver import RUIDO_TITULO
from ..transformations.skills import Taxonomy
from ..transformations.text import normalizar

CLASSES = {
    "consolidada": "Consolidadas",
    "comprovada_profissional": "Comprovadas em experiência profissional",
    "demonstrada_projeto": "Demonstradas em projetos",
    "declarada_sem_evidencia": "Declaradas, sem evidência suficiente",
    "em_desenvolvimento": "Em desenvolvimento",
    "prioritaria": "Prioritárias para aprender",
    "baixa_relevancia": "Baixa relevância para o objetivo atual",
}
FATORES = ("frequencia", "exigencia", "crescimento", "compatibilidade", "senioridade", "esforco", "comprovacao")
_SENIORIDADE_TITULO = re.compile(r"\b(junior|jr|pleno|pl|senior|sr|sênior|i{1,3}|iv|estagiari[oa]|trainee|especialista|"
                                 r"lead|lider|principal|staff|\d+)\b")


class ConteudoSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estudar: list[str] = Field(default_factory=list)
    projeto: str = ""
    evidencia: str = ""


class ConteudoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versao: str = "0"
    competencias: dict[str, ConteudoSkill] = Field(default_factory=dict)


def _cargo(titulo: str) -> str:
    t = _SENIORIDADE_TITULO.sub(" ", RUIDO_TITULO.sub(" ", normalizar(re.sub(r"\((a|o|as|os)\)", "", titulo))))
    return " ".join(w for w in t.split() if len(w) > 1 or w == "e")


def _frase(t: str) -> str:
    t = t.strip()
    return t if not t or t.endswith((".", "!", "?")) else t + "."


def _fatores(pct: float, pct_req: float, pct_out: float, pct_sen: float | None, var: float | None,
             tendencia: str, esforco: float, projeto: bool, cmax: float,
             topo: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Frequência, exigência e senioridade são RELATIVAS à competência mais pedida no objetivo (ela vale 1):
    com a escala absoluta, quase tudo ficava perto de 0 e o ranking era decidido por esforço e projeto."""
    notas = []
    cresc = 0.0
    if tendencia in ("alta", "estavel", "queda") and var is not None:
        cresc = min(max(var / cmax, 0.0), 1.0)
    else:
        notas.append("crescimento inconclusivo (sem amostra nos dois períodos): vale 0")
    if pct_sen is None:
        notas.append("sem amostra por senioridade: usa a frequência geral")
    f = {
        "frequencia": pct / topo["pct"] if topo["pct"] else 0.0,
        "exigencia": pct_req / topo["req"] if topo["req"] else 0.0,
        "crescimento": cresc,
        "compatibilidade": pct / (pct + pct_out) if (pct + pct_out) else 0.0,
        "senioridade": (pct_sen / topo["sen"] if topo["sen"] else 0.0) if pct_sen is not None
        else (pct / topo["pct"] if topo["pct"] else 0.0),
        "esforco": esforco,
        "comprovacao": 1.0 if projeto else 0.0,
    }
    return {k: round(min(max(v, 0.0), 1.0), 3) for k, v in f.items()}, notas


def montar(snap: Snapshot, scores: pd.DataFrame, profile: Profile, cv, tax: Taxonomy, scoring: dict[str, Any],
           filtros: dict[str, Any], conteudo: dict[str, Any], progresso: pd.DataFrame, agora: datetime) -> dict[str, Any]:
    from ..curriculo.diagnostico import _alvo, diagnosticar   # import tardio: o pipeline não carrega o currículo

    cfg, rec_cfg = scoring["evolucao"], scoring["recomendacoes"]
    pesos = cfg["pesos"]
    min_n = int(rec_cfg["min_vagas_janela"])
    min_pct = float(scoring["curriculo"]["min_pct_relevante"])
    dias = int(scoring["curriculo"]["janela_dias"])
    texto = ConteudoConfig.model_validate(conteudo or {}).competencias

    diag = diagnosticar(snap, scores, profile, cv, tax, scoring, filtros, agora)
    por_skill = {d["skill_id"]: d for d in diag["competencias"]}
    tendencias = {r.skill_id: r for r in recomendar(snap, profile, tax, rec_cfg, filtros, agora)}

    c = snap.canonicas
    alvo = _alvo(c, profile, filtros, agora, dias)
    janela = pd.to_datetime(c["primeira_observacao"], utc=True) >= agora - timedelta(days=dias)
    freq_alvo = market.frequencia_competencias(snap, alvo).set_index("skill_id")
    freq_out = market.frequencia_competencias(snap, janela & ~alvo).set_index("skill_id")
    sen = alvo & c["senioridade"].isin(profile.senioridades) if profile.senioridades else alvo & False
    n_sen = int(sen.sum())
    freq_sen = market.frequencia_competencias(snap, sen).set_index("skill_id") if n_sen >= min_n else None
    co = coocorrencia.janela(c, snap.skills, alvo, int(scoring.get("coocorrencia", {}).get("min_vagas_par", 10)), min_n)
    prog = {r.skill_id: r for r in progresso.itertuples()} if not progresso.empty else {}
    esf = rec_cfg["esforco_fator"]
    topo = {"pct": max((d["pct"] for d in diag["competencias"]), default=0.0),
            "req": max((d["pct_requisito"] for d in diag["competencias"]), default=0.0),
            "sen": float(freq_sen["percentual"].max()) if freq_sen is not None and not freq_sen.empty else 0.0}

    itens = []
    for skill in tax.skills:
        d = por_skill.get(skill.id, {})
        pct = float(d.get("pct", 0.0))
        p = prog.get(skill.id)
        nivel_p, nivel_cv = profile.nivel(skill.id), d.get("nivel_curriculo") or (cv.niveis().get(skill.id) if cv else None) or "sem_evidencia"
        status = p.status if p is not None else None
        if pct == 0 and nivel_p == "sem_evidencia" and nivel_cv == "sem_evidencia" and status is None:
            continue
        t = tendencias.get(skill.id)
        fat, notas = _fatores(pct, float(d.get("pct_requisito", 0.0)),
                              float(freq_out["percentual"].get(skill.id, 0.0)) if not freq_out.empty else 0.0,
                              float(freq_sen["percentual"].get(skill.id, 0.0)) if freq_sen is not None and not freq_sen.empty else None,
                              t.variacao_pp if t else None, t.tendencia if t else "inconclusiva",
                              float(esf.get(skill.esforco, 0.5)), skill.projeto, float(cfg["crescimento_pp_maximo"]), topo)
        decomp = {k: round(pesos[k] * v, 3) for k, v in fat.items()}
        # classe pela evidência (4.2)
        com_evid = bool(p is not None and p.evidencia and str(p.evidencia).strip())
        if nivel_p == "profissional" and nivel_cv == "comprovada":
            classe = "consolidada"
        elif nivel_cv == "comprovada" or (status == "comprovada_profissional" and com_evid):
            classe = "comprovada_profissional"
        elif nivel_p == "projeto" or nivel_cv == "projeto":
            classe = "demonstrada_projeto"
        elif nivel_p == "profissional" or nivel_cv == "declarada":
            classe = "declarada_sem_evidencia"
        elif nivel_p == "em_desenvolvimento" or nivel_cv == "parcial" or status in ("em_estudo", "em_pratica", "pausada"):
            classe = "em_desenvolvimento"
        else:
            classe = "lacuna"
        itens.append({
            "skill_id": skill.id, "nome": skill.nome, "classe": classe, "pct": pct,
            "pct_requisito": float(d.get("pct_requisito", 0.0)),
            "vagas": int(freq_alvo["vagas"].get(skill.id, 0)) if not freq_alvo.empty else 0,
            "nivel_perfil": nivel_p, "nivel_curriculo": nivel_cv, "progresso": status,
            "progresso_evidencia": (p.evidencia if p is not None else None),
            "tendencia": t.tendencia if t else "inconclusiva", "variacao_pp": t.variacao_pp if t else None,
            "esforco": skill.esforco, "projeto_pratico": skill.projeto,
            "prioridade": round(sum(decomp.values()), 3), "fatores": fat, "decomposicao": decomp, "notas": notas,
            "baixa_relevancia": pct < min_pct,
        })

    # lacunas: só as N mais prioritárias viram "prioritária" (4.1: não recomendar todas)
    lacunas = sorted((i for i in itens if i["classe"] == "lacuna"), key=lambda i: (-i["prioridade"], -i["pct"]))
    escolhidas = 0
    for i in lacunas:
        motivo = None
        if diag["amostra_pequena"]:
            motivo = f"só {diag['vagas_alvo']} vagas-alvo (mínimo {min_n}): sem conclusão de prioridade"
        elif i["pct"] < min_pct:
            motivo = f"pedida em {i['pct']:.0f}% das vagas-alvo (abaixo de {min_pct:.0f}%)"
        elif i["prioridade"] < float(cfg["prioridade_minima"]):
            motivo = f"prioridade {i['prioridade']:.2f} abaixo do corte {cfg['prioridade_minima']}"
        elif escolhidas >= int(cfg["max_prioritarias"]):
            motivo = f"fora das {cfg['max_prioritarias']} de maior prioridade (vem depois)"
        if motivo:
            i["classe"], i["motivo"] = "baixa_relevancia", motivo
        else:
            i["classe"] = "prioritaria"
            escolhidas += 1

    # recomendações práticas (4.3) para as prioritárias e próximo passo das em desenvolvimento
    fortes = {i["skill_id"] for i in itens if i["classe"] in ("consolidada", "comprovada_profissional", "demonstrada_projeto")}
    nome = {s.id: s.nome for s in tax.skills}
    ids_alvo = set(c.loc[alvo, "job_id"])
    sk_alvo = snap.skills[snap.skills["job_id"].isin(ids_alvo)]
    for i in itens:
        if i["classe"] not in ("prioritaria", "em_desenvolvimento"):
            continue
        sid = i["skill_id"]
        vagas_com = c[c["job_id"].isin(set(sk_alvo.loc[sk_alvo["skill_id"] == sid, "job_id"]))]
        rel = coocorrencia.relacionadas(co, sid)
        rel = rel[rel["lift"] >= 1.2].head(5)
        juntas = [{"skill_id": r.skill_id, "nome": nome.get(r.skill_id, r.skill_id), "confianca_pct": float(r.confianca_pct),
                   "lift": float(r.lift), "voce_tem": r.skill_id in fortes} for r in rel.itertuples()]
        t = texto.get(sid, ConteudoSkill())
        termo = (por_skill.get(sid) or {}).get("termo_mais_usado_nas_vagas")
        combinar = [j["nome"] for j in sorted(juntas, key=lambda j: -j["lift"]) if j["voce_tem"]][:2]
        i["recomendacao"] = {
            "por_que": (f"Pedida em {i['vagas']} de {diag['vagas_alvo']} vagas-alvo ({i['pct']:.0f}%), "
                        f"como requisito em {i['pct_requisito']:.0f}%. "
                        + (f"Tendência: {i['tendencia']} ({i['variacao_pp']:+.1f} p.p.). " if i["variacao_pp"] is not None
                           else "Tendência ainda inconclusiva. ")
                        + f"É {i['fatores']['compatibilidade'] / max(1 - i['fatores']['compatibilidade'], 0.01):.1f}× "
                          "mais frequente nas vagas deste objetivo do que nas demais."),
            "vagas": i["vagas"],
            "cargos": [{"cargo": k, "vagas": v} for k, v in Counter(vagas_com["titulo"].map(_cargo)).most_common(3) if k],
            "familias": vagas_com["familia"].value_counts().head(3).to_dict(),
            "senioridades": vagas_com["senioridade"].value_counts().head(3).to_dict(),
            "tecnologias_associadas": juntas,
            "estudar": t.estudar,
            "projeto": " ".join(x for x in (_frase(t.projeto[:1].upper() + t.projeto[1:]) if t.projeto else "",
                                            f"Combine com {' e '.join(combinar)}, que você já tem e que aparecem junto "
                                            "nas vagas." if combinar else "") if x),
            "evidencia_curriculo": " ".join(x for x in (
                _frase(t.evidencia[:1].upper() + t.evidencia[1:]) if t.evidencia else "",
                f"Use o termo que as vagas mais usam: “{termo}”." if termo else "",
                "Depois, registre o progresso como “demonstrada em projeto”, com o link.") if x),
            "conteudo_e_sugestao": True,   # estudar/projeto/evidência vêm de config/evolucao.yaml (editável)
        }
        if i["classe"] == "em_desenvolvimento":
            prox = {None: "comece a estudar", "nao_iniciada": "comece a estudar", "em_estudo": "pratique num projeto",
                    "em_pratica": "publique o projeto e registre o link", "pausada": "retome quando fizer sentido"}
            i["proximo_passo"] = prox.get(i["progresso"], "pratique num projeto")
            if i["progresso"] is None and i["nivel_curriculo"] == "parcial" and i["nivel_perfil"] != "em_desenvolvimento":
                i["proximo_passo"] = ("o currículo indica de forma indireta (conceito, curso ou certificação): se você "
                                      "já usou, cite pelo nome na experiência; se não, pratique num projeto")

    classes = {k: sorted([i for i in itens if i["classe"] == k], key=lambda i: (-i["prioridade"], -i["pct"]))
               for k in CLASSES}
    return {
        "gerado_em": agora.isoformat(), "objetivo_id": diag["objetivo_id"], "objetivo": diag["objetivo"],
        "perfil_hash": profile.hash, "versao_id": diag["versao_id"], "taxonomia_versao": tax.versao,
        "vagas_alvo": diag["vagas_alvo"], "amostra_pequena": diag["amostra_pequena"],
        "vagas_por_senioridade_do_objetivo": n_sen, "aderencia": diag["aderencia"],
        "pesos": pesos, "fatores": list(FATORES),
        "classes": classes, "nomes_classes": CLASSES,
        "prioritarias": classes["prioritaria"],
        "aviso": ("Prioridade é uma ordenação explicável a partir das vagas coletadas e de estimativas configuradas "
                  "(esforço, projeto); não é garantia de contratação. Curso concluído não conta como experiência "
                  "profissional. Ausência de evidência não significa que você não tem a competência."),
    }

"""Diagnóstico mensal (Etapa 7): retrato do mês por objetivo e as 7 perguntas da especificação.

Retrato (gravado em `private/diagnosticos_mensais`, só agregados e níveis — nenhum texto de currículo):
aderência do perfil e do currículo, classes do plano, prioritárias, demanda (peso por competência nas
vagas-alvo do mês) e níveis de evidência (perfil efetivo e resumo do currículo).

"Minha aderência melhorou?" é respondida com DECOMPOSIÇÃO, porque a aderência pode subir só porque o
mercado passou a pedir o que você já tinha:
    A(D, C) = Σ peso_s · cobertura_s / Σ peso_s        (D = demanda do mês, C = cobertura pelos seus níveis)
    variação total   = A(D₁, C₁) − A(D₀, C₀)
    efeito mercado   = A(D₁, C₀) − A(D₀, C₀)          (seu perfil de antes, a demanda de agora)
    efeito perfil    = A(D₁, C₁) − A(D₁, C₀)          (a demanda de agora, o seu perfil de agora)
A soma dos dois efeitos é exatamente a variação total. Pontuação maior NÃO é garantia de emprego.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..analytics import market
from ..analytics.selection import FUSO

AVISO = ("Aderência mede o quanto as suas evidências cobrem o que as vagas-alvo pedem; subir a pontuação não é "
         "garantia de empregabilidade nem previsão de contratação. Associação entre competências não é causa.")
ORDEM_PERFIL = {"sem_evidencia": 0, "nao_dominada": 0, "em_desenvolvimento": 1, "projeto": 2, "profissional": 3}


def mes_referencia(agora: datetime) -> str:
    """No dia 1 o retrato fecha o mês anterior; em outro dia, é o mês corrente (parcial)."""
    local = agora.astimezone(FUSO)
    return (local - timedelta(days=1) if local.day == 1 else local).strftime("%Y-%m")


def aderencia(demanda: dict[str, float], cobertura: dict[str, float]) -> float | None:
    total = sum(demanda.values())
    if not total:
        return None
    return round(100 * sum(p * cobertura.get(k, 0.0) for k, p in demanda.items()) / total, 1)


def cobertura(niveis: dict[str, str], pesos: dict[str, float]) -> dict[str, float]:
    return {k: float(pesos.get(v, 0.0)) for k, v in niveis.items()}


def retrato(s, agora: datetime, objetivo_id: str | None = None) -> list[dict[str, Any]]:
    """Um retrato por objetivo do perfil (ou só o pedido). Usa o lake privado; não lê ~/.jobradar."""
    from ..curriculo.diagnostico import _alvo, _demanda
    from ..storage import Lake
    from ..transformations.skills import Taxonomy
    from .plano import montar
    from .progresso import perfil_efetivo
    from .resumo_cv import carregar as carregar_resumo

    lake = Lake(s.lake)
    tax = Taxonomy(s.skills)
    snap = market.carregar(lake, tax.config.extracao.gold_hibrida)
    scores = lake.read("gold/job_scores")
    perfil = perfil_efetivo(s.profile, lake)
    resumo = carregar_resumo(s.lake)
    progresso = lake.read("private/study_progress")
    peso_desejavel = float(s.scoring["aderencia"]["peso_desejavel"])
    min_n = int(s.scoring["recomendacoes"]["min_vagas_janela"])
    tecnicos = {k.id for k in tax.skills}
    c = snap.canonicas
    primeira = pd.to_datetime(c["primeira_observacao"], utc=True)
    saida = []
    for p in ([perfil.para(objetivo_id)] if objetivo_id else perfil.por_objetivo()):
        plano = montar(snap, scores, p, resumo, tax, s.scoring, s.filtros, s.evolucao, progresso, agora)
        mes_mask = _alvo(c, p, s.filtros, agora, 3650) & (primeira >= agora - timedelta(days=30))
        dem = _demanda(snap, mes_mask, peso_desejavel)
        freq = market.frequencia_competencias(snap, mes_mask)
        saida.append({
            "mes": mes_referencia(agora), "gerado_em": agora.isoformat(), "objetivo_id": p.objetivo_id,
            "objetivo": plano["objetivo"], "vagas_mes": int(mes_mask.sum()), "amostra_pequena": int(mes_mask.sum()) < min_n,
            "aderencia_perfil": plano["aderencia"]["perfil"]["valor"],
            "aderencia_curriculo": (plano["aderencia"]["curriculo"] or {}).get("valor"),
            "demanda": {r.skill_id: round(float(r.peso), 4) for r in dem.itertuples() if r.skill_id in tecnicos},
            "pct": {r.skill_id: float(r.percentual) for r in freq.itertuples()},
            "pct_requisito": {r.skill_id: float(r.percentual_requisito) for r in freq.itertuples()},
            "niveis_perfil": {k: v for k, v in p.niveis.items()},
            "niveis_curriculo": resumo.niveis() if resumo else {},
            "classes": {k: [i["skill_id"] for i in v] for k, v in plano["classes"].items()},
            "prioritarias": [i["skill_id"] for i in plano["prioritarias"]],
            "projetos": [{"skill_id": i["skill_id"], "nome": i["nome"], "projeto": i["recomendacao"]["projeto"]}
                         for i in plano["prioritarias"][:3]],
            "progresso": {r.skill_id: r.status for r in progresso.itertuples()} if not progresso.empty else {},
        })
    return saida


def diagnostico(atual: dict[str, Any], anterior: dict[str, Any] | None, pesos_perfil: dict[str, float],
                pesos_cv: dict[str, float], nomes: dict[str, str], eventos: pd.DataFrame, min_n: int,
                min_pp: float = 5.0) -> dict[str, Any]:
    """As 7 perguntas para UM objetivo (a 7ª, entre objetivos, fica em `objetivos_compativeis`)."""
    nome = lambda k: nomes.get(k, k)  # noqa: E731
    r: dict[str, Any] = {"objetivo_id": atual["objetivo_id"], "objetivo": atual["objetivo"], "mes": atual["mes"],
                         "anterior": anterior["mes"] if anterior else None, "vagas_mes": atual["vagas_mes"],
                         "amostra_pequena": atual["amostra_pequena"]}

    # 1. A aderência melhorou? (com decomposição mercado × perfil)
    c1 = cobertura(atual["niveis_perfil"], pesos_perfil)
    if anterior:
        c0 = cobertura(anterior["niveis_perfil"], pesos_perfil)
        a0, a1 = aderencia(anterior["demanda"], c0), aderencia(atual["demanda"], c1)
        cruzado = aderencia(atual["demanda"], c0)
        r["q1_aderencia"] = {"antes": a0, "agora": a1,
                             "variacao": None if a0 is None or a1 is None else round(a1 - a0, 1),
                             "efeito_mercado": None if a0 is None or cruzado is None else round(cruzado - a0, 1),
                             "efeito_perfil": None if a1 is None or cruzado is None else round(a1 - cruzado, 1),
                             "curriculo_antes": anterior.get("aderencia_curriculo"),
                             "curriculo_agora": atual.get("aderencia_curriculo")}
    else:
        r["q1_aderencia"] = {"antes": None, "agora": aderencia(atual["demanda"], c1), "variacao": None,
                             "efeito_mercado": None, "efeito_perfil": None,
                             "aviso": "primeiro retrato: a comparação começa no próximo mês"}

    # 2. Que competências desenvolvi?
    ini = pd.Timestamp(anterior["gerado_em"]) if anterior else None
    ev = eventos if (ini is None or eventos.empty) else eventos[pd.to_datetime(eventos["em"], utc=True) >= ini]
    subiram = []
    if anterior:
        for k, v in atual["niveis_perfil"].items():
            if ORDEM_PERFIL.get(v, 0) > ORDEM_PERFIL.get(anterior["niveis_perfil"].get(k, "sem_evidencia"), 0):
                subiram.append({"nome": nome(k), "de": anterior["niveis_perfil"].get(k, "sem_evidencia"), "para": v})
    r["q2_desenvolvidas"] = {"niveis_que_subiram": subiram,
                             "progresso_registrado": [{"nome": nome(e.skill_id), "para": e.para} for e in ev.itertuples()]
                             if not ev.empty else []}

    # 3. Que lacunas continuam relevantes?
    persist = [k for k in atual["prioritarias"] if anterior and k in anterior["prioritarias"]]
    r["q3_lacunas"] = {"continuam": [{"nome": nome(k), "pct": atual["pct"].get(k, 0.0)} for k in persist],
                       "novas": [nome(k) for k in atual["prioritarias"] if not anterior or k not in anterior["prioritarias"]],
                       "resolvidas": [nome(k) for k in (anterior["prioritarias"] if anterior else []) if k not in atual["prioritarias"]]}

    # 4. O que mudou nas exigências? (só com amostra nos dois meses)
    if anterior and atual["vagas_mes"] >= min_n and anterior["vagas_mes"] >= min_n:
        chaves = set(atual["pct"]) | set(anterior["pct"])
        delta = sorted(((atual["pct"].get(k, 0) - anterior["pct"].get(k, 0), k) for k in chaves if k in nomes), reverse=True)
        r["q4_exigencias"] = {"subiram": [{"nome": nome(k), "delta_pp": round(d, 1)} for d, k in delta if d >= min_pp][:6],
                              "cairam": [{"nome": nome(k), "delta_pp": round(d, 1)} for d, k in reversed(delta) if d <= -min_pp][:6],
                              "novas": [nome(k) for k in atual["pct"] if k in nomes and atual["pct"][k] >= 3 and anterior["pct"].get(k, 0) == 0]}
    else:
        r["q4_exigencias"] = {"aviso": f"sem amostra nos dois meses (mínimo {min_n} vagas em cada)"
                              if anterior else "primeiro retrato: a comparação começa no próximo mês"}

    # 5. Que projetos agregariam mais valor? (os das prioridades, combinados com o que você tem)
    r["q5_projetos"] = atual["projetos"]

    # 6. O currículo demonstra melhor?
    if atual["niveis_curriculo"]:
        cv1 = aderencia(atual["demanda"], cobertura(atual["niveis_curriculo"], pesos_cv))
        decl1 = len(atual["classes"].get("declarada_sem_evidencia", []))
        q6 = {"aderencia_curriculo": cv1, "declaradas_sem_evidencia": decl1}
        if anterior and anterior.get("niveis_curriculo"):
            cv0 = aderencia(atual["demanda"], cobertura(anterior["niveis_curriculo"], pesos_cv))   # mesma demanda: só o CV muda
            q6.update({"aderencia_curriculo_antes": cv0, "variacao": None if cv0 is None or cv1 is None else round(cv1 - cv0, 1),
                       "declaradas_antes": len(anterior["classes"].get("declarada_sem_evidencia", []))})
        r["q6_curriculo"] = q6
    else:
        r["q6_curriculo"] = {"aviso": "sem resumo do currículo compartilhado (jobradar curriculo compartilhar-resumo)"}
    r["aviso"] = AVISO
    return r


def objetivos_compativeis(retratos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """7. Quais objetivos estão mais compatíveis com o seu perfil (com o n de cada um)."""
    return sorted([{"objetivo": x["objetivo"], "objetivo_id": x["objetivo_id"], "perfil": x["aderencia_perfil"],
                    "curriculo": x["aderencia_curriculo"], "vagas_mes": x["vagas_mes"], "amostra_pequena": x["amostra_pequena"]}
                   for x in retratos], key=lambda x: (x["amostra_pequena"], -(x["perfil"] or 0)))


def serie_mercado_com_perfil_atual(snap, perfil, filtros: dict[str, Any], scoring: dict[str, Any], agora: datetime,
                                   meses: int = 12) -> pd.DataFrame:
    """Aderência do perfil ATUAL contra a demanda de cada mês passado (rotulado assim no painel):
    mostra só como o mercado mudou em relação ao que você sabe hoje — não é histórico pessoal."""
    from ..curriculo.diagnostico import _alvo, _demanda
    c = snap.canonicas
    mes = pd.to_datetime(c["primeira_observacao"], utc=True).dt.tz_convert(FUSO).dt.strftime("%Y-%m")
    alvo = _alvo(c, perfil, filtros, agora, 3650)
    cob = cobertura(perfil.niveis, scoring["aderencia"]["evidencia"])
    linhas = []
    for m in sorted(set(mes[alvo]))[-meses:]:
        mm = alvo & (mes == m)
        dem = _demanda(snap, mm, float(scoring["aderencia"]["peso_desejavel"]))
        linhas.append({"mes": m, "vagas": int(mm.sum()),
                       "aderencia": aderencia({r.skill_id: float(r.peso) for r in dem.itertuples()}, cob)})
    return pd.DataFrame(linhas, columns=["mes", "vagas", "aderencia"])

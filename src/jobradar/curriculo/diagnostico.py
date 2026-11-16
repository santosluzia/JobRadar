"""Diagnóstico de aderência POR OBJETIVO: perfil declarado × currículo × demanda das vagas-alvo.

Duas lentes, sempre lado a lado:
- aderência do PERFIL: o que você declara saber (`profile.yaml`), a mesma base do score do e-mail;
- aderência do CURRÍCULO: o que o texto do currículo demonstra (o que um recrutador enxerga).

Aderência = média das evidências ponderada pela demanda: para cada competência pedida nas vagas-alvo,
peso = % das vagas que a pedem como requisito + `peso_desejavel` × % que a pedem como desejável;
cobertura = peso da evidência (config/scoring.yaml). Resultado 0–100, com as competências que mais
somaram e as que mais faltaram. NÃO é previsão de contratação, e ausência no currículo não quer dizer
que você não tem a competência.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..analytics import coocorrencia, market
from ..analytics.market import Snapshot
from ..scoring import Profile
from ..transformations.skills import Taxonomy
from .estrutura import Curriculo

NIVEL_FORTE = 0.75     # profissional/projeto (perfil) ou comprovada/projeto (currículo)
LIFT_MINIMO_PONTE = 1.2


def _alvo(c: pd.DataFrame, profile: Profile, filtros: dict[str, Any], agora: datetime, dias: int) -> pd.Series:
    familias = profile.familias or [f for f in filtros.get("familias", []) if f != "outra"]
    senior = list(profile.senioridades or filtros.get("senioridades") or []) + ["nao_informada"]
    m = pd.to_datetime(c["primeira_observacao"], utc=True) >= agora - timedelta(days=dias)
    if familias:
        m &= c["familia"].isin(familias)
    if profile.senioridades or filtros.get("senioridades"):
        m &= c["senioridade"].isin(senior)
    return m


def _demanda(snap: Snapshot, mascara: pd.Series, peso_desejavel: float) -> pd.DataFrame:
    f = market.frequencia_competencias(snap, mascara)
    if f.empty:
        return f.assign(peso=[])
    return f.assign(peso=(f["percentual_requisito"] + peso_desejavel * (f["percentual"] - f["percentual_requisito"])) / 100)


def _aderencia(dem: pd.DataFrame, cobertura: dict[str, float]) -> dict[str, Any]:
    if dem.empty or dem["peso"].sum() == 0:
        return {"valor": None, "somaram": [], "faltaram": []}
    contrib = dem.assign(cob=dem["skill_id"].map(cobertura).fillna(0.0))
    contrib["ganho"] = contrib["peso"] * contrib["cob"]
    contrib["perda"] = contrib["peso"] * (1 - contrib["cob"])
    total = contrib["peso"].sum()
    return {
        "valor": int(round(100 * contrib["ganho"].sum() / total)),
        "somaram": [{"skill_id": r.skill_id, "pontos": round(float(100 * r.ganho / total), 1)}
                    for r in contrib.sort_values("ganho", ascending=False).head(5).itertuples() if r.ganho > 0],
        "faltaram": [{"skill_id": r.skill_id, "pontos": round(float(100 * r.perda / total), 1)}
                     for r in contrib.sort_values("perda", ascending=False).head(5).itertuples() if r.perda > 0],
    }


def diagnosticar(snap: Snapshot, scores: pd.DataFrame, profile: Profile, cv: Curriculo | None, tax: Taxonomy,
                 scoring: dict[str, Any], filtros: dict[str, Any], agora: datetime) -> dict[str, Any]:
    cfg_cv, ader = scoring["curriculo"], scoring["aderencia"]
    min_n = int(scoring["recomendacoes"]["min_vagas_janela"])
    min_pct, limiar = float(cfg_cv["min_pct_relevante"]), float(cfg_cv["limiar_lacuna_pct"])
    peso_perfil, peso_cv = ader["evidencia"], cfg_cv["pesos_evidencia"]
    c = snap.canonicas
    mascara = _alvo(c, profile, filtros, agora, int(cfg_cv["janela_dias"]))
    n = int(mascara.sum())
    dem = _demanda(snap, mascara, float(ader["peso_desejavel"]))

    nivel_cv = cv.niveis() if cv else {}
    evid_cv = cv.evidencias() if cv else {}
    cob_perfil = {s: float(peso_perfil.get(profile.nivel(s), 0)) for s in dem["skill_id"]}
    cob_cv = {s: float(peso_cv.get(nivel_cv.get(s, "sem_evidencia"), 0)) for s in dem["skill_id"]}

    # ---- por competência
    nomes = {s.id: s.nome for s in tax.skills}
    termos_vagas = (snap.skills[snap.skills["job_id"].isin(c.loc[mascara, "job_id"]) & (snap.skills.get("metodo", "termo") != "conceito")]
                    .groupby(["skill_id", "termo"])["job_id"].nunique().reset_index(name="vagas")
                    .sort_values("vagas", ascending=False).drop_duplicates("skill_id").set_index("skill_id"))
    linhas = []
    for r in dem.itertuples():
        nv_cv = nivel_cv.get(r.skill_id)
        linhas.append({
            "skill_id": r.skill_id, "nome": nomes.get(r.skill_id, r.skill_id), "pct": float(r.percentual),
            "pct_requisito": float(r.percentual_requisito), "nivel_perfil": profile.nivel(r.skill_id),
            "nivel_curriculo": nv_cv or "sem_evidencia",
            "evidencias_curriculo": [{"secao": sec, "onde": onde, "frase": a.evidencia, "metodo": a.metodo, "termo": a.termo}
                                     for sec, onde, a in evid_cv.get(r.skill_id, [])],
            "evidencias_perfil": profile.evidencias.get(r.skill_id, []),
            "termo_mais_usado_nas_vagas": termos_vagas["termo"].get(r.skill_id) if r.skill_id in termos_vagas.index else None,
        })
    tab = pd.DataFrame(linhas)
    rel = tab[tab["pct"] >= min_pct] if not tab.empty else tab
    forte = lambda pesos, col: rel[col].map(lambda nv: float(pesos.get(nv, 0)) >= NIVEL_FORTE)  # noqa: E731

    def lista(df: pd.DataFrame) -> list[dict[str, Any]]:
        return df.sort_values("pct", ascending=False).to_dict("records") if not df.empty else []

    if rel.empty:
        compat = sem_cv = ausentes = mal_descritas = desenvolver = []
    else:
        perfil_forte, cv_forte = forte(peso_perfil, "nivel_perfil"), forte(peso_cv, "nivel_curriculo")
        compat = lista(rel[perfil_forte | cv_forte])
        sem_cv = lista(rel[rel["nivel_curriculo"] == "sem_evidencia"])
        ausentes = lista(rel[(rel["pct"] >= limiar) & rel["nivel_perfil"].isin(["sem_evidencia", "nao_dominada"])
                             & ~cv_forte])
        mal_descritas = lista(rel[perfil_forte & ~cv_forte])          # você declara; o currículo não mostra
        desenvolver = lista(rel[(rel["pct"] >= limiar) & ~perfil_forte & ~cv_forte])

    # ---- coocorrência nas vagas-alvo: liga o que falta ao que você já tem
    co = coocorrencia.janela(c, snap.skills, mascara, int(scoring.get("coocorrencia", {}).get("min_vagas_par", 10)), min_n)
    fortes = {d["skill_id"] for d in compat}
    for d in desenvolver:
        r = coocorrencia.relacionadas(co, d["skill_id"])
        # "das vagas-alvo que pedem X (você tem), N% também pedem esta"
        pontes = []
        for x in fortes:
            rx = coocorrencia.relacionadas(co, x)
            hit = rx[rx["skill_id"] == d["skill_id"]]
            # só associação acima do acaso: Git ou SQL aparecem com quase tudo e não dizem nada
            if not hit.empty and float(hit.iloc[0]["lift"]) >= LIFT_MINIMO_PONTE:
                pontes.append({"tem": x, "confianca_pct": float(hit.iloc[0]["confianca_pct"]),
                               "vagas_par": int(hit.iloc[0]["vagas_par"]), "lift": float(hit.iloc[0]["lift"])})
        d["aparece_com"] = sorted(pontes, key=lambda p: (-p["lift"], -p["confianca_pct"]))[:3]
        d["costuma_vir_com"] = r["skill_id"].head(3).tolist()

    # ---- aderência geral e por recorte
    def recorte(col: str) -> list[dict[str, Any]]:
        saida = []
        for valor, g in c[mascara].groupby(col):
            m = mascara & (c[col] == valor)
            d = _demanda(snap, m, float(ader["peso_desejavel"]))
            saida.append({"valor": valor, "n": int(m.sum()), "amostra_pequena": int(m.sum()) < min_n,
                          "perfil": _aderencia(d, {s: float(peso_perfil.get(profile.nivel(s), 0)) for s in d["skill_id"]})["valor"],
                          "curriculo": _aderencia(d, {s: float(peso_cv.get(nivel_cv.get(s, "sem_evidencia"), 0))
                                                      for s in d["skill_id"]})["valor"] if cv else None})
        return sorted(saida, key=lambda x: -x["n"])

    sc = scores[(scores["objetivo_id"] == profile.objetivo_id) & scores["job_id"].isin(c.loc[mascara, "job_id"])] \
        if not scores.empty else scores
    corte = int(filtros.get("score_minimo", 0))
    distribuicao = {"vagas_com_score": len(sc), "mediana": float(sc["score"].median()) if len(sc) else None,
                    "p75": float(sc["score"].quantile(0.75)) if len(sc) else None,
                    "pct_acima_do_corte": round(100 * float((sc["score"] >= corte).mean()), 1) if len(sc) else None,
                    "corte": corte}

    # ---- experiências em destaque: as que concentram competências mais pedidas
    pct = dict(zip(tab["skill_id"], tab["pct"])) if not tab.empty else {}
    experiencias = []
    for i, e in enumerate(cv.experiencias if cv else []):
        sk = sorted({a.skill_id for a in e.competencias}, key=lambda s: -pct.get(s, 0))
        experiencias.append({"indice": i, "onde": " · ".join(x for x in (e.cargo, e.empresa) if x) or f"experiência {i + 1}",
                             "relevancia": round(sum(pct.get(s, 0) for s in sk), 1), "competencias": sk,
                             "linhas": len(e.responsabilidades) + len(e.resultados), "tem_resultado": bool(e.resultados)})

    nome_obj = next((o.nome for o in profile.objetivos if o.id == profile.objetivo_id), profile.objetivo_id)
    return {
        "gerado_em": agora.isoformat(), "objetivo_id": profile.objetivo_id, "objetivo": nome_obj,
        "versao_id": cv.versao_id if cv else None, "perfil_hash": profile.hash,
        "taxonomia_versao": tax.versao, "janela_dias": int(cfg_cv["janela_dias"]),
        "vagas_alvo": n, "amostra_pequena": n < min_n,
        "familias": list(profile.familias), "senioridades": list(profile.senioridades),
        "aderencia": {"perfil": _aderencia(dem, cob_perfil), "curriculo": _aderencia(dem, cob_cv) if cv else None},
        "por_familia": recorte("familia"), "por_senioridade": recorte("senioridade"),
        "scores_das_vagas": distribuicao,
        "competencias": tab.to_dict("records") if not tab.empty else [],
        "compativeis": compat, "sem_evidencia_no_curriculo": sem_cv,
        "requisitos_recorrentes_ausentes": ausentes, "declaradas_mas_nao_demonstradas": mal_descritas,
        "a_desenvolver": desenvolver,
        "palavras_chave": [{"skill_id": d["skill_id"], "nome": d["nome"], "pct": d["pct"],
                            "termo_nas_vagas": d["termo_mais_usado_nas_vagas"]} for d in compat[:15]],
        "experiencias": sorted(experiencias, key=lambda x: -x["relevancia"]),
        "aviso": ("Aderência mede o quanto as evidências cobrem as competências mais pedidas nas vagas-alvo. "
                  "Não é previsão de contratação. Ausência no currículo não significa que você não tem a competência."),
    }

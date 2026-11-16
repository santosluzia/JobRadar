"""JobRadar — Relatório Semanal de Evolução Profissional (Etapa 6).

10 seções (mercado, vagas analisadas, mais exigidas, em crescimento, combinações, perfil, lacunas,
currículo, projetos e progresso das recomendações anteriores) e, no fim, as TRÊS principais
oportunidades de evolução — nunca uma lista de cursos.

Comparações só com dados suficientes (amostra mínima nas duas janelas; senão, o relatório diz por quê):
semana × semana anterior, 30 dias × 30 anteriores, objetivo × mercado (todas as famílias de dados) e
versão atual × anteriores do resumo do currículo (só níveis, compartilhado por adesão).

Privacidade: como o Radar, roda no CI com o lake privado; não lê ~/.jobradar; o log só recebe contagens.
Histórico em `private/relatorios_semanais` (base da comparação e do acompanhamento da semana seguinte).
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..analytics import coocorrencia, market
from ..analytics.selection import FUSO
from ..settings import Settings
from ..storage import Lake
from . import email as em
from .radar import RadarConfig, _caixa, carregar_config

ORDEM_NIVEL = {"profissional": 3, "projeto": 2, "em_desenvolvimento": 1}


def semana_iso(agora: datetime) -> str:
    a, s, _ = (agora + timedelta(minutes=30)).astimezone(FUSO).isocalendar()
    return f"{a}-W{s:02d}"


def devido(cfg: RadarConfig, agora: datetime, turno: int, hist: pd.DataFrame, objetivo_id: str) -> tuple[bool, str]:
    sem = cfg.semanal
    if not sem.ativo:
        return False, "Relatório semanal desativado (private/radar.yaml → semanal)"
    if turno != sem.turno:
        return False, f"fora do horário do relatório ({sem.horario})"
    local = (agora + timedelta(minutes=30)).astimezone(FUSO)
    if ["seg", "ter", "qua", "qui", "sex", "sab", "dom"][local.weekday()] != sem.dia:
        return False, f"o relatório sai às {sem.dia}"
    ok = hist[(hist["status"] == "enviado") & (hist["objetivo_id"] == objetivo_id)] if not hist.empty else hist
    if not ok.empty and (ok["semana"] == semana_iso(agora)).any():
        return False, "relatório desta semana já enviado"
    return True, "ok"


def _freq(snap, mascara) -> pd.DataFrame:
    f = market.frequencia_competencias(snap, mascara)
    return f.set_index("skill_id") if not f.empty else f


def _crescimento(snap, m_rec, m_ant, min_n: int, min_pp: float, nomes: dict, lim: int, rotulo: str) -> dict[str, Any]:
    n_r, n_a = int(m_rec.sum()), int(m_ant.sum())
    base = {"rotulo": rotulo, "n_recente": n_r, "n_anterior": n_a, "itens": [], "aviso": None}
    if n_r < min_n or n_a < min_n:
        base["aviso"] = f"amostra insuficiente ({n_r} × {n_a} vagas; mínimo {min_n} em cada)"
        return base
    fr, fa = _freq(snap, m_rec), _freq(snap, m_ant)
    idx = fr.index.union(fa.index) if len(fr) and len(fa) else fr.index
    pr = fr["percentual"].reindex(idx, fill_value=0) if len(fr) else pd.Series(0.0, index=idx)
    pa = fa["percentual"].reindex(idx, fill_value=0) if len(fa) else pd.Series(0.0, index=idx)
    delta = (pr - pa).sort_values(ascending=False)
    base["itens"] = [{"skill_id": k, "nome": nomes[k], "de": float(pa[k]), "para": float(pr[k]), "delta_pp": round(float(d), 1)}
                     for k, d in delta.items() if d >= min_pp and k in nomes][:lim]
    if not base["itens"]:
        base["aviso"] = f"nenhuma competência variou {min_pp:.0f} p.p. ou mais"
    return base


def montar(s: Settings, agora: datetime, cfg: RadarConfig, hist: pd.DataFrame) -> dict[str, Any]:
    from ..curriculo.diagnostico import _alvo
    from ..evolucao.plano import montar as montar_plano
    from ..evolucao.progresso import perfil_efetivo
    from ..evolucao.resumo_cv import carregar as carregar_resumo, comparar_niveis, historico as hist_resumos
    from ..transformations.skills import Taxonomy

    lake = Lake(s.lake)
    tax = Taxonomy(s.skills)
    nomes = {k.id: k.nome for k in tax.skills}
    snap = market.carregar(lake, tax.config.extracao.gold_hibrida)
    perfil = perfil_efetivo(s.profile, lake)
    objetivo = cfg.semanal.objetivo or cfg.objetivo or (perfil.objetivos[0].id if perfil.objetivos else "")
    p = perfil.para(objetivo) if perfil.objetivos else perfil
    resumo = carregar_resumo(s.lake)
    progresso = lake.read("private/study_progress")
    plano = montar_plano(snap, lake.read("gold/job_scores"), p, resumo, tax, s.scoring, s.filtros, s.evolucao,
                         progresso, agora)
    min_n = int(s.scoring["recomendacoes"]["min_vagas_janela"])
    lim, min_pp = cfg.semanal.limite_itens, cfg.min_variacao_pp
    c = snap.canonicas
    primeira = pd.to_datetime(c["primeira_observacao"], utc=True)
    familias_dados = [f for f in s.filtros.get("familias", []) if f != "outra"]
    obj = _alvo(c, p, s.filtros, agora, 3650)
    mercado = c["familia"].isin(familias_dados)
    # janela [agora − a, agora − b); com b = 0 inclui o que foi observado agora
    jan = lambda a, b: (primeira >= agora - timedelta(days=a)) & ((primeira < agora - timedelta(days=b)) | (b == 0))  # noqa: E731
    sem, sem_ant, d30, d30_ant = jan(7, 0), jan(14, 7), jan(30, 0), jan(60, 30)
    anterior = (hist[(hist["status"] == "enviado") & (hist["objetivo_id"] == p.objetivo_id)].sort_values("enviado_em")
                if not hist.empty else hist)
    ultimo = json.loads(anterior.iloc[-1]["resumo"]) if len(anterior) else None
    ult_oport = json.loads(anterior.iloc[-1]["oportunidades"]) if len(anterior) else []

    # 1–2. mercado e vagas analisadas
    encerradas = pd.to_datetime(c["encerrada_em"], utc=True)
    s1 = {"mercado_semana": int((mercado & sem).sum()), "mercado_semana_anterior": int((mercado & sem_ant).sum()),
          "objetivo_semana": int((obj & sem).sum()), "objetivo_semana_anterior": int((obj & sem_ant).sum()),
          "encerradas_semana": int((mercado & (encerradas >= agora - timedelta(days=7))).sum()),
          "fontes": market.fontes(snap)}
    s2 = {"objetivo_30d": int((obj & d30).sum()), "mercado_30d": int((mercado & d30).sum()),
          "objetivo_90d": plano["vagas_alvo"]}

    # 3. mais exigidas (30 dias, mais estável que a semana) — objetivo × mercado
    fo, fm = _freq(snap, obj & d30), _freq(snap, mercado & d30)
    exigidas = [{"skill_id": k, "nome": nomes[k], "pct": float(r.percentual), "pct_requisito": float(r.percentual_requisito),
                 "pct_mercado": float(fm["percentual"].get(k, 0.0)) if len(fm) else 0.0}
                for k, r in (fo.head(lim + 5).iterrows() if len(fo) else []) if k in nomes][:lim]

    # 4. crescimento: semana × semana e 30 × 30, no objetivo e no mercado — só com amostra
    crescimento = [_crescimento(snap, obj & sem, obj & sem_ant, min_n, min_pp, nomes, lim, "objetivo: semana × semana anterior"),
                   _crescimento(snap, mercado & sem, mercado & sem_ant, min_n, min_pp, nomes, lim,
                                "mercado de dados: semana × semana anterior"),
                   _crescimento(snap, obj & d30, obj & d30_ant, min_n, min_pp, nomes, lim, "objetivo: 30 dias × 30 anteriores")]

    # 5. combinações: pares mais fortes do objetivo e "pontes" (você tem × prioridade)
    m90 = obj & (primeira >= agora - timedelta(days=90))
    co = coocorrencia.janela(c, snap.skills, m90, int(s.scoring.get("coocorrencia", {}).get("min_vagas_par", 10)), min_n)
    co_ok = co[~co["amostra_pequena"]] if not co.empty else co
    combinacoes = [{"a": nomes.get(r.skill_a, r.skill_a), "b": nomes.get(r.skill_b, r.skill_b), "vagas": int(r.vagas_par),
                    "jaccard": float(r.jaccard), "lift": float(r.lift)}
                   for r in co_ok.sort_values("jaccard", ascending=False).head(5).itertuples()] if len(co_ok) else []
    itens = {i["skill_id"]: i for v in plano["classes"].values() for i in v}
    fortes = {k for k, i in itens.items() if i["classe"] in ("consolidada", "comprovada_profissional", "demonstrada_projeto")}
    prior = [i["skill_id"] for i in plano["prioritarias"]]
    pontes = []
    if len(co_ok):
        for r in co_ok.sort_values("lift", ascending=False).itertuples():
            tem, falta = (r.skill_a, r.skill_b) if r.skill_a in fortes else (r.skill_b, r.skill_a)
            if tem in fortes and falta in prior and r.lift >= 1.2:
                pontes.append({"tem": nomes.get(tem, tem), "falta": nomes.get(falta, falta), "vagas": int(r.vagas_par),
                               "lift": float(r.lift)})
            if len(pontes) >= 3:
                break

    # 6. perfil × semana anterior
    por_classe = {k: len(v) for k, v in plano["classes"].items()}
    ad = plano["aderencia"]
    perfil_sec = {"aderencia_perfil": ad["perfil"]["valor"], "aderencia_curriculo": (ad["curriculo"] or {}).get("valor"),
                  "por_classe": por_classe,
                  "antes": {"aderencia_perfil": ultimo.get("aderencia_perfil"), "aderencia_curriculo": ultimo.get("aderencia_curriculo"),
                            "por_classe": ultimo.get("por_classe", {})} if ultimo else None}

    # 7. lacunas prioritárias: entraram/saíram
    lacunas = {"atuais": [{"skill_id": i["skill_id"], "nome": i["nome"], "pct": i["pct"]} for i in plano["prioritarias"]],
               "entraram": sorted(set(prior) - set(ultimo.get("prioritarias", []))) if ultimo else [],
               "sairam": sorted(set(ultimo.get("prioritarias", [])) - set(prior)) if ultimo else []}

    # 8. currículo: o que melhorar e versão atual × anteriores (só níveis, por adesão)
    melhorias = []
    if resumo:
        melhorias = [{"tipo": "documentar", "nome": i["nome"], "pct": i["pct"]}
                     for i in plano["classes"]["declarada_sem_evidencia"] if not i["baixa_relevancia"]][:3]
        melhorias += [{"tipo": "nomear", "nome": i["nome"], "pct": i["pct"]}
                      for i in plano["classes"]["em_desenvolvimento"] if i["nivel_curriculo"] == "parcial"][:2]
    versoes = hist_resumos(s.lake)
    comparacao_cv = (comparar_niveis(versoes[-2]["niveis"], versoes[-1]["niveis"]) | {"de": versoes[-2]["versao_id"],
                     "para": versoes[-1]["versao_id"]}) if len(versoes) >= 2 else None

    # 10. progresso das recomendações anteriores (Radar dos últimos 7 dias + as 3 da semana passada)
    envios = lake.read("private/radar_envios")
    eventos = lake.read("private/study_events")
    rec = envios[(envios["status"] == "enviado") & envios["acao_skill"].notna()
                 & (pd.to_datetime(envios["enviado_em"], utc=True) >= agora - timedelta(days=7))] if not envios.empty else envios
    prog_atual = dict(zip(progresso["skill_id"], progresso["status"])) if not progresso.empty else {}
    acompanhamento = []
    for r in rec.drop_duplicates("acao_skill", keep="last").itertuples() if len(rec) else []:
        depois = eventos[(eventos["skill_id"] == r.acao_skill) & (pd.to_datetime(eventos["em"], utc=True) >= pd.Timestamp(r.enviado_em))] \
            if not eventos.empty else eventos
        acompanhamento.append({"origem": "radar", "nome": nomes.get(r.acao_skill, r.acao_skill), "acao": r.acao_tipo,
                               "status": prog_atual.get(r.acao_skill, "nao_iniciada"), "avancou": len(depois) > 0})
    for sid in ult_oport:
        depois = eventos[(eventos["skill_id"] == sid) & (pd.to_datetime(eventos["em"], utc=True)
                                                         >= pd.Timestamp(anterior.iloc[-1]["enviado_em"]))] if not eventos.empty else eventos
        acompanhamento.append({"origem": "relatorio anterior", "nome": nomes.get(sid, sid), "acao": "oportunidade",
                               "status": prog_atual.get(sid, "nao_iniciada"), "avancou": len(depois) > 0})

    # 9 + fechamento: as TRÊS principais oportunidades (cartões), com semanas seguidas sem progresso
    semanas_seguidas = {}
    for sid in prior[:3]:
        n = 1
        for o in reversed([json.loads(x) for x in anterior["oportunidades"]] if len(anterior) else []):
            if sid not in o:
                break
            n += 1
        semanas_seguidas[sid] = n
    oportunidades = []
    for i in plano["prioritarias"][:3]:
        r = i["recomendacao"]
        oportunidades.append({"skill_id": i["skill_id"], "nome": i["nome"], "por_que": r["por_que"], "projeto": r["projeto"],
                              "curriculo": r["evidencia_curriculo"], "estudar": r["estudar"][:3],
                              "semanas_seguidas": semanas_seguidas[i["skill_id"]],
                              "sem_progresso": prog_atual.get(i["skill_id"]) in (None, "nao_iniciada")})
    projetos = [{"nome": o["nome"], "projeto": o["projeto"]} for o in oportunidades]

    resumo_hist = {"aderencia_perfil": perfil_sec["aderencia_perfil"], "aderencia_curriculo": perfil_sec["aderencia_curriculo"],
                   "por_classe": por_classe, "prioritarias": prior, "objetivo_semana": s1["objetivo_semana"]}
    return {
        "semana": semana_iso(agora), "gerado_em": agora.isoformat(), "objetivo_id": p.objetivo_id,
        "objetivo": plano["objetivo"], "min_n": min_n, "com_resumo_cv": resumo is not None,
        "s1_mercado": s1, "s2_vagas": s2, "s3_exigidas": exigidas, "s4_crescimento": crescimento,
        "s5_combinacoes": combinacoes, "s5_pontes": pontes, "s6_perfil": perfil_sec, "s7_lacunas": lacunas,
        "s8_curriculo": {"melhorias": melhorias, "comparacao": comparacao_cv}, "s9_projetos": projetos,
        "s10_progresso": acompanhamento, "oportunidades": oportunidades, "resumo_hist": resumo_hist, "nomes": nomes,
    }


# ------------------------------------------------------------------ renderização
def _barra(rotulo: str, pct: float, pct_ref: float | None, nota: str) -> str:
    e = html.escape
    largura = max(min(pct, 100), 1)
    ref = (f'<div style="height:4px;background:{em.LINHA};width:{max(min(pct_ref, 100), 1):.0f}%;margin-top:2px"></div>'
           if pct_ref is not None else "")
    return (f'<tr><td style="padding:4px 0;font-size:13px;width:38%">{e(rotulo)}</td><td style="padding:4px 0">'
            f'<div style="height:9px;border-radius:5px;background:{em.VIOLETA};width:{largura:.0f}%"></div>{ref}</td>'
            f'<td style="padding:4px 0 4px 8px;font-family:{em.MONO};font-size:12px;white-space:nowrap">{e(nota)}</td></tr>')


def renderizar(r: dict[str, Any], agora: datetime) -> tuple[str, str, str]:
    e = html.escape
    local = agora.astimezone(FUSO)
    assunto = f"JobRadar — Relatório Semanal de Evolução Profissional · {r['semana']} · {r['objetivo']}"
    L: list[str] = []
    T: list[str] = [assunto, ""]

    def secao(n: int, titulo: str, nota: str = "") -> None:
        L.append(em._titulo_secao(f"{n} · {titulo}", nota))
        T.append(f"== {n}. {titulo} ==")

    s1, s2 = r["s1_mercado"], r["s2_vagas"]
    secao(1, "Resumo do mercado")
    p1 = (f"Mercado de dados: <b>{s1['mercado_semana']}</b> vagas novas na semana (eram {s1['mercado_semana_anterior']}); "
          f"no seu objetivo, <b>{s1['objetivo_semana']}</b> (eram {s1['objetivo_semana_anterior']}). "
          f"{s1['encerradas_semana']} vagas encerraram na semana.")
    L.append(_caixa(p1)); T.append(_txt(p1))
    secao(2, "Vagas analisadas")
    p2 = (f"Objetivo: {s2['objetivo_30d']} vagas em 30 dias ({s2['objetivo_90d']} em 90). Mercado de dados: "
          f"{s2['mercado_30d']} vagas em 30 dias. Mínimo para comparar proporções: {r['min_n']} vagas por janela.")
    L.append(_caixa(e(p2))); T.append(p2)

    secao(3, "Competências mais exigidas", "Últimos 30 dias · barra violeta: seu objetivo · barra cinza: mercado de dados")
    if not r["s3_exigidas"]:
        L.append(_caixa("Sem vagas do objetivo nos últimos 30 dias."))
        T.append("Sem vagas do objetivo nos últimos 30 dias.")
    else:
        linhas = "".join(_barra(x["nome"], x["pct"], x["pct_mercado"],
                                f"{x['pct']:.0f}% (req. {x['pct_requisito']:.0f}%) · mercado {x['pct_mercado']:.0f}%")
                         for x in r["s3_exigidas"])
        L.append(_caixa(f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{linhas}</table>'))
        T += [f"- {x['nome']}: {x['pct']:.0f}% (requisito {x['pct_requisito']:.0f}%) · mercado {x['pct_mercado']:.0f}%"
              for x in r["s3_exigidas"]]

    secao(4, "Competências em crescimento")
    partes = []
    for cmp_ in r["s4_crescimento"]:
        if cmp_["itens"]:
            partes.append(f"<b>{e(cmp_['rotulo'])}</b> ({cmp_['n_recente']} × {cmp_['n_anterior']} vagas): " + ", ".join(
                f"{e(x['nome'])} {x['de']:.0f}% → {x['para']:.0f}%" for x in cmp_["itens"]))
        else:
            partes.append(f"<b>{e(cmp_['rotulo'])}</b>: {e(cmp_['aviso'])}.")
    L.append(_caixa("<br>".join(partes))); T += [_txt(x) for x in partes]

    secao(5, "Combinações de competências relevantes", "Associação nas vagas do objetivo (90 dias), não causa.")
    if not (r["s5_combinacoes"] or r["s5_pontes"]):
        L.append(_caixa("Sem pares com amostra suficiente nas vagas do objetivo."))
        T.append("Sem pares com amostra suficiente nas vagas do objetivo.")
    else:
        partes = [", ".join(f"{e(x['a'])} + {e(x['b'])} ({x['vagas']} vagas)" for x in r["s5_combinacoes"])] if r["s5_combinacoes"] else []
        partes += [f"Ponte: você tem <b>{e(x['tem'])}</b>; <b>{e(x['falta'])}</b> aparece junto em {x['vagas']} vagas "
                   f"({x['lift']:.1f}× o acaso)." for x in r["s5_pontes"]]
        L.append(_caixa("<br>".join(partes))); T += [_txt(x) for x in partes]

    s6 = r["s6_perfil"]
    secao(6, "Comparação com o seu perfil")
    antes = s6["antes"]
    p6 = (f"Aderência do perfil: <b>{s6['aderencia_perfil']}</b>"
          + (f" (semana passada: {antes['aderencia_perfil']})" if antes else "")
          + (f" · do currículo: <b>{s6['aderencia_curriculo']}</b>" if s6["aderencia_curriculo"] is not None else
             " · currículo: sem resumo compartilhado")
          + ". Competências: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in s6["por_classe"].items() if v) + ".")
    L.append(_caixa(p6)); T.append(_txt(p6))

    s7 = r["s7_lacunas"]
    secao(7, "Lacunas prioritárias")
    p7 = (", ".join(f"<b>{e(x['nome'])}</b> ({x['pct']:.0f}%)" for x in s7["atuais"]) or "nenhuma com amostra suficiente")
    if s7["entraram"] or s7["sairam"]:
        p7 += "<br>Desde a semana passada: " + "; ".join(x for x in (
            f"entraram {', '.join(r['nomes'].get(k, k) for k in s7['entraram'])}" if s7["entraram"] else "",
            f"saíram {', '.join(r['nomes'].get(k, k) for k in s7['sairam'])}" if s7["sairam"] else "") if x)
    L.append(_caixa(p7)); T.append(_txt(p7))

    s8 = r["s8_curriculo"]
    secao(8, "Melhorias recomendadas no currículo")
    if s8["melhorias"]:
        p8 = "<br>".join(f"{'Documente onde usou' if m['tipo'] == 'documentar' else 'Cite pelo nome'} <b>{e(m['nome'])}</b> "
                         f"({m['pct']:.0f}% das vagas-alvo)." for m in s8["melhorias"])
    else:
        p8 = ("Nada a ajustar com base no resumo do currículo." if r["com_resumo_cv"] else
              "Sem o resumo do currículo (jobradar curriculo compartilhar-resumo), esta seção não tem base.")
    if s8["comparacao"]:
        cmp_ = s8["comparacao"]
        mudancas = [f"{r['nomes'].get(k, k)} {a} → {b}" for k, (a, b) in cmp_["subiram"].items()]
        mudancas += [f"{r['nomes'].get(k, k)} (nova: {v})" for k, v in cmp_["novas"].items()]
        if mudancas:
            p8 += "<br>Desde a versão anterior do currículo: " + e(", ".join(mudancas)) + "."
    L.append(_caixa(p8)); T.append(_txt(p8))

    if r["s9_projetos"]:
        secao(9, "Projetos sugeridos", "Sugestão editável (config/evolucao.yaml), combinada com o que você já tem.")
        p9 = "<br>".join(f"<b>{e(x['nome'])}:</b> {e(x['projeto'])}" for x in r["s9_projetos"])
        L.append(_caixa(p9)); T.append(_txt(p9))

    secao(10, "Progresso das recomendações anteriores")
    if r["s10_progresso"]:
        p10 = "<br>".join(f"{e(x['nome'])} ({'Radar' if x['origem'] == 'radar' else 'relatório anterior'}): status "
                          f"<b>{e(x['status'].replace('_', ' '))}</b>" + (" — avançou depois da recomendação ✓" if x["avancou"] else
                                                                          " — sem progresso registrado depois")
                          for x in r["s10_progresso"])
    else:
        p10 = "Sem recomendações anteriores para acompanhar ainda."
    L.append(_caixa(p10)); T.append(_txt(p10))

    L.append(em._titulo_secao("As 3 principais oportunidades de evolução"))
    T.append("== As 3 principais oportunidades ==")
    for k, o in enumerate(r["oportunidades"], 1):
        aviso = (f'<br><span style="color:{em.ALERTA};font-size:12px">{o["semanas_seguidas"]}ª semana seguida'
                 f'{", sem progresso registrado" if o["sem_progresso"] else ""}.</span>' if o["semanas_seguidas"] > 1 else "")
        L.append(_caixa(f'<span style="font-family:{em.MONO};font-size:11px;color:{em.VIOLETA}">{k:02d}</span> '
                        f'<b style="font-size:16px">{e(o["nome"])}</b><br>{e(o["por_que"])}<br><b>Projeto:</b> {e(o["projeto"])}'
                        f'<br><b>No currículo:</b> {e(o["curriculo"])}{aviso}', em.VIOLETA, em.LILAS))
        T += [f"{k}. {o['nome']} — {o['por_que']}", f"   Projeto: {o['projeto']}", f"   No currículo: {o['curriculo']}"]
    if not r["oportunidades"]:
        L.append(_caixa("Sem oportunidades prioritárias com amostra suficiente nesta semana."))

    subtitulo = f"Semana {r['semana']} · {r['objetivo']} · gerado em {local:%d/%m/%Y}"
    rodape = ("Comparações só com amostra mínima; associação não é causa; aderência não é previsão de contratação. "
              "Configure em private/radar.yaml → semanal.")
    corpo = em.moldura(assunto, f"As 3 oportunidades da semana: {', '.join(o['nome'] for o in r['oportunidades'])}",
                       "JobRadar · Relatório Semanal", "Relatório Semanal de Evolução Profissional", subtitulo, L,
                       r["s1_mercado"]["fontes"], rodape=e(rodape))
    return assunto, corpo, "\n".join(T + ["", rodape])


def _txt(h: str) -> str:
    import re
    return html.unescape(re.sub(r"<br>", "\n", re.sub(r"<(?!br)[^>]+>", "", h)))


# ------------------------------------------------------------------ envio
def enviar(s: Settings, agora: datetime, run_id: str, turno: int | None = None, dry_run: bool = False,
           forcar: bool = False, html_out=None) -> dict[str, Any]:
    from ..evolucao.progresso import perfil_efetivo
    from .radar import turno_de
    lake = Lake(s.lake)
    cfg = carregar_config(s.lake)
    hist = lake.read("private/relatorios_semanais")
    perfil = perfil_efetivo(s.profile, lake)
    objetivo_id = cfg.semanal.objetivo or cfg.objetivo or (perfil.objetivos[0].id if perfil.objetivos else "")
    ok, motivo = devido(cfg, agora, turno_de(agora) if turno is None else turno, hist, objetivo_id)
    if not ok and not forcar and not dry_run:
        return {"enviado": False, "motivo": motivo}
    r = montar(s, agora, cfg, hist)
    assunto, corpo, texto = renderizar(r, agora)
    contagens = {"oportunidades": len(r["oportunidades"]), "secoes": 10}
    if dry_run:
        if html_out:
            from pathlib import Path
            Path(html_out).write_text(corpo, encoding="utf-8")
        return {"enviado": False, "motivo": "prévia (dry-run): nada enviado nem registrado", **contagens}
    linha = {"semana": r["semana"], "objetivo_id": r["objetivo_id"], "enviado_em": agora, "run_id": run_id,
             "assunto": assunto, "oportunidades": json.dumps([o["skill_id"] for o in r["oportunidades"]]),
             "resumo": json.dumps(r["resumo_hist"], ensure_ascii=False)}
    try:
        em.enviar_smtp(s, assunto, corpo, texto)
    except Exception as ex:
        lake.append("private/relatorios_semanais", pd.DataFrame([{**linha, "status": "falha", "erro": type(ex).__name__}]))
        raise
    lake.append("private/relatorios_semanais", pd.DataFrame([{**linha, "status": "enviado", "erro": None}]))
    return {"enviado": True, "motivo": "ok", **contagens}

"""Minha Evolução Profissional — PRIVADO. Plano por objetivo, classificação, progresso e vagas pontuadas."""
import pandas as pd
import streamlit as st
from components import data

from jobradar.evolucao import servico
from jobradar.evolucao.plano import CLASSES
from jobradar.evolucao.progresso import STATUS, atualizar, efeito_no_perfil
from jobradar.scoring import Profile

st.title("Minha Evolução Profissional")
if data.estado_vazio():
    st.stop()

s = data.settings()
perfil = data.perfil()          # perfil declarado + progresso
nomes = data.nomes()
if perfil.vazio:
    st.warning("Perfil não encontrado. Copie `config/profile.example.yaml` para `<lake>/private/profile.yaml` e preencha.")
    st.stop()
nomes_obj = {o.id: o.nome for o in perfil.objetivos}
objetivo = st.sidebar.selectbox("Objetivo profissional", list(nomes_obj), format_func=nomes_obj.get) \
    if len(nomes_obj) > 1 else next(iter(nomes_obj))
st.caption(f"Objetivo: **{nomes_obj[objetivo]}**. Cada objetivo tem plano próprio: requisitos de cargos diferentes "
           "não se misturam. 🔒 Nada desta página é publicado.")


@st.cache_data(ttl=120, show_spinner="Montando o plano…")
def _plano(objetivo: str, _marca: tuple) -> dict:
    return servico.planos(data.settings(), objetivo)[0]


progresso = data.lake().read("private/study_progress")
marca = (str(progresso["atualizado_em"].max()) if not progresso.empty else "", perfil.hash)
p = _plano(objetivo, marca)
aba_plano, aba_ativ, aba_classes, aba_prog, aba_vagas = st.tabs(
    ["Plano", "Atividades e evidências", "Classificação", "Progresso", "Vagas pontuadas"])

with aba_ativ:   # Career Intelligence 7.3: o plano em andamento
    data.badge("observado")
    estado = dict(zip(progresso["skill_id"], progresso["status"])) if not progresso.empty else {}
    evid = dict(zip(progresso["skill_id"], progresso["evidencia"])) if not progresso.empty else {}
    todas = [i for v in p["classes"].values() for i in v]
    planejadas = [i for i in p["prioritarias"] + p["classes"]["em_desenvolvimento"]
                  if estado.get(i["skill_id"]) in (None, "nao_iniciada", "em_estudo", "pausada")]
    andamento = [i for i in todas if estado.get(i["skill_id"]) == "em_pratica"]
    adquiridas = [i for i in todas if estado.get(i["skill_id"]) in ("demonstrada_em_projeto", "comprovada_profissional")]
    futuras = [i for i in p["classes"]["baixa_relevancia"] if "vem depois" in (i.get("motivo") or "")]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Atividades planejadas", len(planejadas))
    c2.metric("Projetos em andamento", len(andamento))
    c3.metric("Evidências adquiridas", len(adquiridas))
    c4.metric("Recomendações futuras", len(futuras))
    st.markdown("**Atividades planejadas** (prioritárias e em desenvolvimento ainda sem prática)")
    st.dataframe(pd.DataFrame([{"competência": i["nome"], "% vagas": i["pct"], "status": estado.get(i["skill_id"]) or "—",
                                "próximo passo": i.get("proximo_passo") or "estudar"} for i in planejadas]),
                 hide_index=True, width="stretch")
    st.markdown("**Projetos em andamento**")
    st.dataframe(pd.DataFrame([{"competência": i["nome"], "projeto sugerido": (i.get("recomendacao") or {}).get("projeto", "—")}
                               for i in andamento]), hide_index=True, width="stretch")
    st.markdown("**Evidências adquiridas**")
    st.dataframe(pd.DataFrame([{"competência": i["nome"], "status": estado[i["skill_id"]].replace("_", " "),
                                "evidência": evid.get(i["skill_id"]) or "—"} for i in adquiridas]),
                 hide_index=True, width="stretch")
    st.markdown("**Recomendações futuras** (relevantes, mas fora das prioritárias por enquanto)")
    st.dataframe(pd.DataFrame([{"competência": i["nome"], "% vagas": i["pct"], "prioridade": i["prioridade"]} for i in futuras]),
                 hide_index=True, width="stretch")

with aba_plano:
    data.badge("recomendacao")
    if p["amostra_pequena"]:
        st.warning(f"Só {p['vagas_alvo']} vagas-alvo: prioridades ficam em suspenso até haver amostra suficiente.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Vagas-alvo (90 dias)", p["vagas_alvo"])
    c2.metric("Aderência do perfil", p["aderencia"]["perfil"]["valor"])
    c3.metric("Aderência do currículo", (p["aderencia"]["curriculo"] or {}).get("valor") or "—")
    st.caption(p["aviso"])
    if not p["prioritarias"]:
        st.info("Nenhuma competência prioritária para aprender agora (veja a aba Classificação).")
    for i in p["prioritarias"]:
        r = i["recomendacao"]
        with st.expander(f"🎯 {i['nome']} — {i['pct']:.0f}% das vagas-alvo · prioridade {i['prioridade']:.2f}", expanded=True):
            st.markdown(f"**Por que importa.** {r['por_que']}")
            st.markdown("**Onde aparece.** " + (", ".join(f"{c['cargo']} ({c['vagas']})" for c in r["cargos"]) or "—"))
            if r["tecnologias_associadas"]:
                st.markdown("**Aparece junto de.** " + ", ".join(
                    f"{j['nome']} ({j['confianca_pct']:.0f}%){' ✓ você tem' if j['voce_tem'] else ''}"
                    for j in r["tecnologias_associadas"]))
            st.markdown("**O que estudar** _(sugestão editável)_: " + ("; ".join(r["estudar"]) or "—"))
            st.markdown(f"**Projeto** _(sugestão)_: {r['projeto'] or '—'}")
            st.markdown(f"**Evidência no currículo.** {r['evidencia_curriculo']}")
            st.caption("Como a prioridade foi calculada (fator × peso): " + " · ".join(
                f"{k} {v:.2f}" for k, v in i["decomposicao"].items()) + (" — " + "; ".join(i["notas"]) if i["notas"] else ""))
    em_dev = p["classes"]["em_desenvolvimento"]
    if em_dev:
        st.subheader("Em desenvolvimento: próximo passo")
        st.dataframe(pd.DataFrame([{"competência": i["nome"], "% vagas": i["pct"], "progresso": i["progresso"] or "—",
                                    "próximo passo": i.get("proximo_passo")} for i in em_dev]),
                     hide_index=True, width="stretch")

with aba_classes:
    data.badge("inferido")
    for chave, titulo in CLASSES.items():
        itens = p["classes"][chave]
        with st.expander(f"{titulo} ({len(itens)})", expanded=chave in ("prioritaria", "declarada_sem_evidencia")):
            if not itens:
                st.caption("Nenhuma.")
                continue
            st.dataframe(pd.DataFrame([{"competência": i["nome"], "% vagas-alvo": i["pct"], "perfil": i["nivel_perfil"],
                                        "currículo": i["nivel_curriculo"], "progresso": i["progresso"] or "—",
                                        "prioridade": i["prioridade"], "observação": i.get("motivo") or
                                        ("pouco pedida neste objetivo" if i["baixa_relevancia"] else "")}
                                       for i in itens]), hide_index=True, width="stretch")
    hist = servico.historico(objetivo)
    if hist:
        st.subheader("Histórico de planos")
        st.dataframe(pd.DataFrame(hist).drop(columns=["objetivo_id", "objetivo"]), hide_index=True, width="stretch")
    if st.button("Salvar este plano no histórico (local)"):
        servico.salvar_plano(p)
        st.success("Plano salvo em ~/.jobradar/evolucao (fora do git).")

with aba_prog:
    st.caption("Curso concluído não vira experiência profissional. “Demonstrada em projeto” e “comprovada em "
               "experiência” só contam no perfil com a evidência (link, projeto, empresa).")
    if not progresso.empty:
        st.dataframe(progresso.assign(competencia=progresso["skill_id"].map(nomes))[
            ["competencia", "status", "inicio", "conclusao", "evidencia"]], hide_index=True, width="stretch")
    with st.form("progresso"):
        sugestao = [i["skill_id"] for i in p["prioritarias"] + p["classes"]["em_desenvolvimento"]]
        c1, c2 = st.columns(2)
        skill = c1.selectbox("Competência", sugestao + [k for k in nomes if k not in sugestao], format_func=nomes.get)
        status = c2.selectbox("Status", STATUS)
        evidencia = st.text_input("Evidência (link do projeto, certificado, empresa onde usou)")
        nota = st.text_input("Nota (opcional)")
        if st.form_submit_button("Salvar progresso"):
            r = atualizar(data.lake(), skill, status, evidencia or None, nota=nota or None)
            efeito = efeito_no_perfil(r["nivel_no_perfil"], Profile.from_dict(data.settings().profile).niveis.get(skill))
            st.success(f"{nomes.get(skill, skill)}: {r['status']}" + (f" — {efeito}" if efeito else ""))
            if r["aviso"]:
                st.warning(r["aviso"])
            st.info("Faça commit/push do jobradar-data para a próxima execução recalcular os scores.")
    ev = data.lake().read("private/study_events")
    if not ev.empty:
        st.subheader("Histórico de progresso")
        st.dataframe(ev.assign(competencia=ev["skill_id"].map(nomes)).sort_values("em", ascending=False)[
            ["em", "competencia", "de", "para", "evidencia", "nota"]], hide_index=True, width="stretch")

with aba_vagas:
    data.badge("inferido")
    todos = data.lake().read("gold/job_scores")
    todos = todos[(todos["objetivo_id"] == objetivo) | (todos["objetivo_id"].isna() & (len(nomes_obj) == 1))]
    snap = data.snapshot()
    sc = todos.merge(snap.canonicas[["job_id", "titulo", "empresa", "status", "url"]], on="job_id")
    sc = sc[sc["status"] != "encerrada"].sort_values("score", ascending=False)
    if sc.empty:
        st.caption("Nenhuma vaga pontuada ainda para este objetivo.")
    else:
        st.caption("O score mede compatibilidade com o seu perfil neste objetivo; não é probabilidade de contratação.")
        st.dataframe(sc[["score", "titulo", "empresa", "url"]].head(30), hide_index=True, width="stretch",
                     column_config={"url": st.column_config.LinkColumn("Vaga", display_text="abrir")})

import json

import pandas as pd
import streamlit as st
from components import data

from jobradar.applications import STUDY_STATUSES, atualizar_estudo
from jobradar.recommendations import recomendar
from jobradar.storage import utcnow

st.title("Minha aderência e estudos")
if data.estado_vazio():
    st.stop()

s = data.settings()
perfil = data.perfil()
nomes = data.nomes()
if perfil.vazio:
    st.warning("Perfil não encontrado. Copie `config/profile.example.yaml` para `<lake>/private/profile.yaml` e preencha.")
    st.stop()
st.caption(f"Perfil lido de `{s.profile_path}`.")

st.subheader("Competências registradas no perfil")
data.badge("observado")
niveis = pd.DataFrame([{"competencia": nomes.get(k, k), "nivel": v,
                        "evidencias": "; ".join(perfil.evidencias.get(k, []))} for k, v in perfil.niveis.items()])
st.dataframe(niveis.sort_values("nivel"), hide_index=True, use_container_width=True)

snap = data.snapshot()
recs = recomendar(snap, perfil, data.taxonomia(), s.scoring["recomendacoes"], s.filtros, utcnow())
st.subheader("Prioridades de estudo")
data.badge("recomendacao")
st.caption("Classificação baseada na demanda observada nas vagas-alvo, com regras de amostra mínima. "
           "O esforço de aprendizagem é uma estimativa configurada em skills.yaml.")
titulos = {"lacuna_prioritaria": "🔴 Lacunas prioritárias", "em_desenvolvimento": "🟡 Em desenvolvimento",
           "monitoramento": "⚪ Para monitorar", "consolidada": "🟢 Consolidadas"}
for classe, titulo in titulos.items():
    grupo = [r for r in recs if r.classe == classe]
    with st.expander(f"{titulo} ({len(grupo)})", expanded=classe in ("lacuna_prioritaria", "em_desenvolvimento")):
        if not grupo:
            st.caption("Nenhuma competência nesta categoria.")
        for r in grupo:
            st.markdown(f"**{r.nome}** — {r.percentual_recente:.0f}% das vagas-alvo · tendência: {r.tendencia}"
                        + (f" ({r.variacao_pp:+.1f} p.p.)" if r.variacao_pp is not None else ""))
            st.caption(r.justificativa)

st.subheader("Aderência às vagas-alvo")
data.badge("inferido")
sc = snap.scores.merge(snap.canonicas[["job_id", "titulo", "empresa", "status", "url"]], on="job_id")
sc = sc[sc["status"] != "encerrada"].sort_values("score", ascending=False)
if sc.empty:
    st.caption("Nenhuma vaga pontuada ainda.")
else:
    st.caption("O score mede compatibilidade com o seu perfil; não é probabilidade de contratação.")
    lac = {}
    for row in sc.itertuples():
        for x in json.loads(row.lacunas or "[]") + json.loads(row.sem_evidencia or "[]"):
            if x["importancia"] == "requisito":
                lac[x["skill_id"]] = lac.get(x["skill_id"], 0) + 1
    if lac:
        st.markdown("**Requisitos que mais faltam nas vagas pontuadas:** " +
                    ", ".join(f"{nomes.get(k, k)} ({v})" for k, v in sorted(lac.items(), key=lambda kv: -kv[1])[:8]))
    st.dataframe(sc[["score", "titulo", "empresa", "url"]].head(30), hide_index=True, use_container_width=True,
                 column_config={"url": st.column_config.LinkColumn("Vaga", display_text="abrir")})

st.subheader("Plano de estudos")
prog = data.lake().read("private/study_progress")
if not prog.empty:
    st.dataframe(prog.assign(competencia=prog["skill_id"].map(nomes))[
        ["competencia", "status", "inicio", "conclusao", "evidencia"]], hide_index=True, use_container_width=True)
with st.form("estudo"):
    sugestoes = [r.skill_id for r in recs if r.classe in ("lacuna_prioritaria", "em_desenvolvimento")] or list(nomes)
    c1, c2 = st.columns(2)
    skill = c1.selectbox("Competência", sugestoes + [k for k in nomes if k not in sugestoes], format_func=nomes.get)
    status = c2.selectbox("Status", STUDY_STATUSES)
    c3, c4 = st.columns(2)
    inicio = c3.date_input("Início", value=None)
    fim = c4.date_input("Conclusão", value=None)
    evidencia = st.text_input("Evidência prática (projeto, certificado, link)")
    if st.form_submit_button("Salvar progresso"):
        atualizar_estudo(data.lake(), skill, status, inicio.isoformat() if inicio else None,
                         fim.isoformat() if fim else None, evidencia or None)
        st.success("Progresso salvo no lake privado. Faça commit/push do jobradar-data para não perder.")
        st.rerun()

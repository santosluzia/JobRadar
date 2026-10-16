import json

import pandas as pd
import streamlit as st
from components import data

from jobradar.applications import atualizar_candidatura
from jobradar.models import APPLICATION_STATUSES
from jobradar.transformations.text import normalizar

st.title("Vagas e candidaturas")
if data.estado_vazio():
    st.stop()

snap = data.snapshot()
nomes = data.nomes()
lake = data.lake()
apps = lake.read("private/applications")
sk = snap.skills.groupby("job_id")["skill_id"].apply(lambda x: ", ".join(sorted(nomes.get(i, i) for i in set(x))))

df = snap.canonicas.merge(snap.scores[["job_id", "score", "explicacao", "lacunas", "sem_evidencia"]], on="job_id", how="left") \
    .merge(apps[["job_id", "status", "observacoes"]].rename(columns={"status": "candidatura"}), on="job_id", how="left")
df["candidatura"] = df["candidatura"].fillna("nova")
df["competencias"] = df["job_id"].map(sk).fillna("")

with st.sidebar:
    st.header("Filtros")
    busca = st.text_input("Buscar (título, empresa, competência)")
    status_vaga = st.multiselect("Situação da vaga", ["ativa", "desconhecida", "encerrada"], default=["ativa", "desconhecida"])
    cand = st.multiselect("Candidatura", APPLICATION_STATUSES, default=[])
    sen = st.multiselect("Senioridade", sorted(df["senioridade"].unique()))
    mod = st.multiselect("Modalidade", sorted(df["modalidade"].unique()))
    fonte = st.multiselect("Fonte", sorted(df["source"].unique()))
    ordem = st.radio("Ordenar por", ["Relevância (score)", "Data de publicação", "Senioridade"])

m = df["status"].isin(status_vaga)
for col, sel in (("candidatura", cand), ("senioridade", sen), ("modalidade", mod), ("source", fonte)):
    if sel:
        m &= df[col].isin(sel)
if busca:
    alvo = (df["titulo"].fillna("") + " " + df["empresa"].fillna("") + " " + df["competencias"]).map(normalizar)
    m &= alvo.str.contains(normalizar(busca), regex=False)
v = df[m].copy()
colunas, asc = {"Relevância (score)": (["score"], [False]), "Data de publicação": (["publicada_em"], [False]),
                 "Senioridade": (["senioridade", "score"], [True, False])}[ordem]
v = v.sort_values(colunas, ascending=asc, na_position="last")

st.caption(f"{len(v)} vagas. Score = inferido pelo sistema; situação e datas = observadas nas coletas.")
tabela = v[["score", "titulo", "empresa", "modalidade", "senioridade", "status", "candidatura", "publicada_em",
            "ultima_observacao", "source", "url"]]
st.dataframe(tabela, hide_index=True, use_container_width=True, column_config={
    "url": st.column_config.LinkColumn("Candidatura", display_text="abrir vaga"),
    "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
    "publicada_em": st.column_config.DatetimeColumn("Publicada", format="DD/MM/YYYY"),
    "ultima_observacao": st.column_config.DatetimeColumn("Última observação", format="DD/MM/YYYY"),
})

st.subheader("Detalhe e acompanhamento")
if v.empty:
    st.stop()
rotulos = {r.job_id: f"{r.titulo} — {r.empresa or 'empresa n/i'}" for r in v.itertuples()}
jid = st.selectbox("Vaga", list(rotulos), format_func=rotulos.get)
j = v[v["job_id"] == jid].iloc[0]
c1, c2 = st.columns([2, 1])
with c1:
    st.markdown(f"### [{j['titulo']}]({j['url']})")
    st.markdown(f"{j['empresa'] or 'Empresa não informada'} · {j['modalidade']} · {j['cidade'] or j['uf'] or 'local n/i'} · "
                f"{j['senioridade']} · fonte {j['source']}")
    st.markdown(f"**Competências:** {j['competencias'] or 'nenhuma identificada'}")
    if pd.notna(j["score"]):
        data.badge("inferido")
        st.markdown(f"**Score de aderência: {int(j['score'])}/100**")
        for e in json.loads(j["explicacao"] or "[]"):
            st.caption(f"{e['criterio']}: {e['pontos']:g}/{e['maximo']} — {e['detalhe']}")
        lac = [nomes.get(x["skill_id"], x["skill_id"]) for x in json.loads(j["lacunas"] or "[]")]
        sem = [nomes.get(x["skill_id"], x["skill_id"]) for x in json.loads(j["sem_evidencia"] or "[]")]
        if lac:
            st.markdown(f"**Lacunas (marcadas como não dominadas):** {', '.join(lac)}")
        if sem:
            st.markdown(f"**Sem evidência no perfil:** {', '.join(sem)}")
    origem = json.loads(j["origem_campos"] or "{}")
    st.caption("Origem dos campos: " + ", ".join(f"{k}={v_}" for k, v_ in origem.items()))
with c2:
    with st.form("candidatura"):
        novo = st.selectbox("Status da candidatura", APPLICATION_STATUSES,
                            index=APPLICATION_STATUSES.index(j["candidatura"]))
        nota = st.text_area("Observações pessoais (privadas)", value=j["observacoes"] if pd.notna(j["observacoes"]) else "")
        if st.form_submit_button("Salvar"):
            atualizar_candidatura(lake, jid, novo, nota or None)
            st.success("Salvo no lake privado. Faça commit/push do jobradar-data para não perder.")
            st.rerun()
    hist = lake.read("private/application_events")
    hist = hist[hist["job_id"] == jid].sort_values("em")
    for h in hist.itertuples():
        st.caption(f"{pd.Timestamp(h.em).tz_convert('America/Sao_Paulo'):%d/%m %H:%M}: {h.de} → {h.para}")

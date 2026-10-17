import json

import pandas as pd
import streamlit as st
from components import data

from jobradar.analytics.selection import FUSO, publicadas_no_periodo, relevantes
from jobradar.storage import utcnow
from jobradar.transformations.text import normalizar

st.title("Vagas")
if data.estado_vazio():
    st.stop()

snap = data.snapshot()
nomes = data.nomes()
s = data.settings()
agora = utcnow()
FONTES = {"gupy": "Gupy", "adzuna": "Adzuna", "greenhouse": "Greenhouse", "lever": "Lever"}
PERIODOS = {"qualquer_data": "Qualquer data", "hoje": "Hoje", "ontem_e_hoje": "Ontem e hoje",
            "7_dias": "Últimos 7 dias", "30_dias": "Últimos 30 dias"}

sk = snap.skills.groupby("job_id")["skill_id"].apply(lambda x: ", ".join(sorted(nomes.get(i, i) for i in set(x))))
df = snap.canonicas.merge(snap.scores[["job_id", "score", "explicacao", "lacunas", "sem_evidencia"]],
                          on="job_id", how="left")
df["competencias"] = df["job_id"].map(sk).fillna("")
df["fonte"] = df["source"].map(lambda f: FONTES.get(f, f))
df["local"] = (df["cidade"].fillna("") + ", " + df["uf"].fillna("")).str.strip(", ").replace("", "não informado")
df["publicada"] = pd.to_datetime(df["publicada_em"], utc=True, errors="coerce").dt.tz_convert(FUSO)
df["relevante"] = relevantes(df, snap.skills, s.filtros, agora,
                             int(s.sources["busca"].get("max_dias_publicacao", 30))).values

with st.sidebar:
    st.header("Filtros")
    busca = st.text_input("Buscar (título, empresa, competência)")
    periodo = st.selectbox("Publicadas", list(PERIODOS), format_func=PERIODOS.get)
    so_relevantes = st.toggle("Só as relevantes (mesmos filtros do e-mail)", value=False)
    fontes = st.multiselect("Fonte", sorted(df["fonte"].unique()))
    empresas = st.multiselect("Empresa", sorted(df["empresa"].dropna().unique()))
    ufs = st.multiselect("Estado", sorted(df["uf"].dropna().unique()))
    cidades_base = df[df["uf"].isin(ufs)] if ufs else df
    cidades = st.multiselect("Cidade", sorted(c for c in cidades_base["cidade"].dropna().unique() if c))
    mod = st.multiselect("Modalidade", sorted(df["modalidade"].unique()))
    sen = st.multiselect("Senioridade", sorted(df["senioridade"].unique()))
    status_vaga = st.multiselect("Situação da vaga", ["ativa", "desconhecida", "encerrada"],
                                 default=["ativa", "desconhecida"])
    agrupar = st.toggle("Agrupar por fonte", value=True)

m = df["status"].isin(status_vaga) & publicadas_no_periodo(df, periodo, agora)
if so_relevantes:
    m &= df["relevante"]
for col, sel in (("fonte", fontes), ("empresa", empresas), ("uf", ufs), ("cidade", cidades),
                 ("modalidade", mod), ("senioridade", sen)):
    if sel:
        m &= df[col].isin(sel)
if busca:
    alvo = (df["titulo"].fillna("") + " " + df["empresa"].fillna("") + " " + df["competencias"]).map(normalizar)
    m &= alvo.str.contains(normalizar(busca), regex=False)
# Mais recentes primeiro; no mesmo instante, maior score antes.
v = df[m].sort_values(["publicada", "score"], ascending=[False, False], na_position="last")

hoje = pd.Timestamp(agora).tz_convert(FUSO).normalize()
c = st.columns(3)
c[0].metric("Vagas no filtro", len(v))
c[1].metric("Publicadas hoje", int((v["publicada"] >= hoje).sum()))
c[2].metric("Publicadas ontem", int(((v["publicada"] >= hoje - pd.Timedelta(days=1)) & (v["publicada"] < hoje)).sum()))
st.caption("Ordenadas pelas mais recentes. Datas no horário de São Paulo. "
           "Score = inferido pelo sistema; situação e datas = observadas nas coletas.")

COLUNAS = ["publicada", "titulo", "empresa", "local", "modalidade", "senioridade", "score", "fonte", "url"]
CONFIG = {
    "publicada": st.column_config.DatetimeColumn("Publicada", format="DD/MM/YYYY HH:mm"),
    "titulo": st.column_config.TextColumn("Vaga"),
    "empresa": st.column_config.TextColumn("Empresa"),
    "local": st.column_config.TextColumn("Local"),
    "modalidade": st.column_config.TextColumn("Modalidade"),
    "senioridade": st.column_config.TextColumn("Senioridade"),
    "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
    "fonte": st.column_config.TextColumn("Fonte"),
    "url": st.column_config.LinkColumn("Candidatura", display_text="abrir vaga"),
}


def tabela(vagas: pd.DataFrame) -> None:
    if vagas.empty:
        st.info("Nenhuma vaga com esses filtros.")
    else:
        st.dataframe(vagas[COLUNAS], hide_index=True, use_container_width=True, column_config=CONFIG)


if agrupar and not v.empty:
    contagem = v["fonte"].value_counts()
    abas = st.tabs([f"Todas ({len(v)})"] + [f"{f} ({n})" for f, n in contagem.items()])
    with abas[0]:
        tabela(v)
    for aba, f in zip(abas[1:], contagem.index):
        with aba:
            tabela(v[v["fonte"] == f])
else:
    tabela(v)

if v.empty:
    st.stop()
st.subheader("Detalhe da vaga")
rotulos = {r.job_id: f"{r.titulo} — {r.empresa or 'empresa n/i'} ({r.fonte})" for r in v.itertuples()}
jid = st.selectbox("Vaga", list(rotulos), format_func=rotulos.get)
j = v[v["job_id"] == jid].iloc[0]
st.markdown(f"### [{j['titulo']}]({j['url']})")
publicada = f"{j['publicada']:%d/%m/%Y %H:%M}" if pd.notna(j["publicada"]) else "data não informada"
st.markdown(f"{j['empresa'] or 'Empresa não informada'} · {j['modalidade']} · {j['local']} · "
            f"{j['senioridade']} · fonte {j['fonte']} · publicada {publicada}")
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
st.link_button("Abrir vaga para se candidatar", j["url"])

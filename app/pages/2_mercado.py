from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st
from components import data

from jobradar.analytics import market
from jobradar.storage import utcnow

st.title("Mercado")
if data.estado_vazio():
    st.stop()

snap = data.snapshot()
s = data.settings()
nomes = data.nomes()
min_n = int(s.scoring["recomendacoes"]["min_vagas_janela"])
c = snap.canonicas

with st.sidebar:
    st.header("Filtros")
    fontes = st.multiselect("Fonte", sorted(c["source"].unique()), default=sorted(c["source"].unique()))
    familias = st.multiselect("Tipo de vaga", sorted(c["familia"].unique()),
                              default=[f for f in s.filtros.get("familias", []) if f in set(c["familia"])])
    dias = st.select_slider("Período (dias)", options=[30, 60, 90, 180, 365, 730], value=180)

agora = utcnow()
primeira = pd.to_datetime(c["primeira_observacao"], utc=True)
mascara = c["source"].isin(fontes) & c["familia"].isin(familias) & (primeira >= agora - timedelta(days=dias))
n = int(mascara.sum())
data.badge("observado")
st.caption(f"{n} vagas no recorte. Mês = mês da primeira observação da vaga.")
if n == 0:
    st.warning("Nenhuma vaga no recorte selecionado.")
    st.stop()

st.subheader("Evolução mensal das competências")
mensal = market.tendencias_mensais(snap, familias)
top = market.frequencia_competencias(snap, mascara, top=8)["skill_id"].tolist()
escolha = st.multiselect("Competências", sorted(nomes, key=nomes.get), default=top[:6], format_func=nomes.get)
serie = mensal[mensal["skill_id"].isin(escolha)].copy()
if serie.empty:
    st.caption("Sem série mensal para as competências escolhidas.")
else:
    serie["competencia"] = serie["skill_id"].map(nomes)
    serie["amostra"] = serie["total_vagas"].map(lambda v: "pequena" if v < min_n else "ok")
    base = alt.Chart(serie).encode(x=alt.X("mes:N", title="Mês"), y=alt.Y("percentual:Q", title="% das vagas do mês"),
                                   color=alt.Color("competencia:N", title=None))
    st.altair_chart(base.mark_line() + base.mark_point(filled=True).encode(
        shape=alt.Shape("amostra:N", title=f"Amostra (<{min_n})"),
        tooltip=["mes", "competencia", "vagas_com_skill", "total_vagas", "percentual"]), use_container_width=True)
    st.caption(f"Pontos marcados como 'pequena' têm menos de {min_n} vagas no mês: leia com cautela. "
               "Variação de volume e de fontes entre meses afeta as proporções; não indica causalidade.")

col1, col2 = st.columns(2)
with col1:
    st.subheader("Júnior × pleno × sênior")
    sen = snap.canonicas[mascara]
    linhas = []
    for nivel in ["junior", "pleno", "senior"]:
        m = mascara & (c["senioridade"] == nivel)
        f = market.frequencia_competencias(snap, m)
        f = f[f["skill_id"].isin(top)]
        f["senioridade"] = nivel
        linhas.append(f)
    comp = pd.concat(linhas) if linhas else pd.DataFrame()
    if comp.empty:
        st.caption("Sem vagas classificadas por senioridade no recorte.")
    else:
        comp["competencia"] = comp["skill_id"].map(nomes)
        st.altair_chart(alt.Chart(comp).mark_bar().encode(
            x=alt.X("percentual:Q", title="% das vagas do nível"), y=alt.Y("competencia:N", title=None),
            color="senioridade:N", yOffset="senioridade:N",
            tooltip=["senioridade", "competencia", "vagas", "n", "percentual"]), use_container_width=True)
        st.caption("Senioridade inferida do título ou da descrição. " +
                   " · ".join(f"{k}: n={int((mascara & (c['senioridade'] == k)).sum())}" for k in ["junior", "pleno", "senior"]))
with col2:
    st.subheader("Modalidade e localização")
    d = c[mascara]
    st.altair_chart(alt.Chart(d.assign(modalidade=d["modalidade"])).mark_bar().encode(
        x=alt.X("count():Q", title="Vagas"), y=alt.Y("modalidade:N", sort="-x", title=None)), use_container_width=True)
    st.dataframe(d["uf"].fillna("não informada").value_counts().head(8).rename("vagas"), use_container_width=True)

st.subheader("Comparação entre períodos equivalentes")
janela = st.radio("Janela", [30, 60, 90], horizontal=True, index=2)
rec = c["source"].isin(fontes) & c["familia"].isin(familias) & (primeira >= agora - timedelta(days=janela))
ant = c["source"].isin(fontes) & c["familia"].isin(familias) & (primeira < agora - timedelta(days=janela)) \
    & (primeira >= agora - timedelta(days=2 * janela))
fr, fa = market.frequencia_competencias(snap, rec), market.frequencia_competencias(snap, ant)
n_r, n_a = int(rec.sum()), int(ant.sum())
comp = fr[["skill_id", "percentual"]].merge(fa[["skill_id", "percentual"]], on="skill_id", how="outer",
                                            suffixes=("_recente", "_anterior")).fillna(0)
comp["variacao_pp"] = (comp["percentual_recente"] - comp["percentual_anterior"]).round(1)
comp["competencia"] = comp["skill_id"].map(nomes)
st.caption(f"Recente: {n_r} vagas · anterior: {n_a} vagas.")
if min(n_r, n_a) < min_n:
    st.warning(f"Pelo menos um dos períodos tem menos de {min_n} vagas: a comparação não é conclusiva.")
st.dataframe(comp.sort_values("percentual_recente", ascending=False)[
    ["competencia", "percentual_anterior", "percentual_recente", "variacao_pp"]], hide_index=True, use_container_width=True)

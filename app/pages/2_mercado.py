from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st
from components import data

from jobradar.analytics import market
from jobradar.storage import utcnow

st.title("Radar de mercado")
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
        tooltip=["mes", "competencia", "vagas_com_skill", "total_vagas", "percentual"]), width="stretch")
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
            tooltip=["senioridade", "competencia", "vagas", "n", "percentual"]), width="stretch")
        st.caption("Senioridade inferida do título ou da descrição. " +
                   " · ".join(f"{k}: n={int((mascara & (c['senioridade'] == k)).sum())}" for k in ["junior", "pleno", "senior"]))
with col2:
    st.subheader("Modalidade e localização")
    d = c[mascara]
    st.altair_chart(alt.Chart(d.assign(modalidade=d["modalidade"])).mark_bar().encode(
        x=alt.X("count():Q", title="Vagas"), y=alt.Y("modalidade:N", sort="-x", title=None)), width="stretch")
    st.dataframe(d["uf"].fillna("não informada").value_counts().head(8).rename("vagas"), width="stretch")

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
    ["competencia", "percentual_anterior", "percentual_recente", "variacao_pp"]], hide_index=True, width="stretch")

st.subheader("Competências que aparecem juntas")
from jobradar.analytics import coocorrencia  # noqa: E402

cfg_co = s.scoring.get("coocorrencia", {})
min_par = int(cfg_co.get("min_vagas_par", 10))
tab = coocorrencia.janela(c, snap.skills, mascara, min_par, min_n)
base_co = int(tab["base"].iloc[0]) if not tab.empty else 0
st.caption(f"Base: {base_co} vagas do recorte com ao menos uma competência identificada. Associação na amostra, "
           f"não causa. Pares com menos de {min_par} vagas juntas ficam de fora. Menção do mesmo produto "
           "(\"Azure Data Factory\", \"PySpark\") não conta como par.")
if base_co < min_n or tab.empty:
    st.info(f"Amostra pequena para coocorrência (menos de {min_n} vagas com competência no recorte).")
else:
    freq = {**dict(zip(tab["skill_b"], tab["vagas_b"])), **dict(zip(tab["skill_a"], tab["vagas_a"]))}
    opcoes = sorted(freq, key=lambda k: nomes.get(k, k))
    foco = st.selectbox("Das vagas que pedem…", opcoes, index=opcoes.index(max(freq, key=freq.get)),
                        format_func=lambda k: nomes.get(k, k))   # começa pela mais frequente do recorte
    rel = coocorrencia.relacionadas(tab, foco)
    if rel.empty:
        st.caption("Nenhum par com amostra suficiente para esta competência.")
    else:
        rel = rel.assign(competencia=rel["skill_id"].map(nomes),
                         intervalo=rel["confianca_ic"].map(lambda ic: f"{ic[0]}–{ic[1]}%"))
        st.altair_chart(alt.Chart(rel.head(12)).mark_bar().encode(
            x=alt.X("confianca_pct:Q", title=f"% das vagas com {nomes.get(foco, foco)} que também pedem"),
            y=alt.Y("competencia:N", sort="-x", title=None),
            tooltip=["competencia", "vagas_par", "confianca_pct", "intervalo", "lift"]), width="stretch")
        st.dataframe(rel[["competencia", "vagas_par", "confianca_pct", "intervalo", "lift"]].head(12),
                     hide_index=True, width="stretch")
        st.caption("Intervalo = 95% (Wilson). Lift > 1: aparecem juntas mais do que se fossem independentes.")


# ---------------------------------------------------------------- Etapa 7.1: emergentes, cargo e requisitos
st.subheader("Competências emergentes")
jr = 30
rec_m = c["source"].isin(fontes) & c["familia"].isin(familias) & (primeira >= agora - timedelta(days=jr))
ant_m = (c["source"].isin(fontes) & c["familia"].isin(familias) & (primeira < agora - timedelta(days=jr))
         & (primeira >= agora - timedelta(days=2 * jr)))
n_rm, n_am = int(rec_m.sum()), int(ant_m.sum())
fr_m, fa_m = market.frequencia_competencias(snap, rec_m), market.frequencia_competencias(snap, ant_m)
nunca_antes = set(fr_m["skill_id"]) - set(market.frequencia_competencias(
    snap, c["familia"].isin(familias) & (primeira < agora - timedelta(days=jr)))["skill_id"])
if min(n_rm, n_am) < min_n:
    st.caption(f"Crescimento 30 × 30 dias: amostra insuficiente ({n_rm} × {n_am} vagas; mínimo {min_n}).")
else:
    em = fr_m[["skill_id", "percentual"]].merge(fa_m[["skill_id", "percentual"]], on="skill_id", how="left",
                                                 suffixes=("_30d", "_anterior")).fillna(0)
    em["variacao_pp"] = (em["percentual_30d"] - em["percentual_anterior"]).round(1)
    em = em[em["variacao_pp"] >= 3].sort_values("variacao_pp", ascending=False).head(8)
    if em.empty:
        st.caption("Nenhuma competência subiu 3 p.p. ou mais entre os últimos 30 dias e os 30 anteriores.")
    else:
        st.dataframe(em.assign(competencia=em["skill_id"].map(nomes))[
            ["competencia", "percentual_anterior", "percentual_30d", "variacao_pp"]], hide_index=True, width="stretch")
if nunca_antes:
    st.caption("Apareceram pela primeira vez nos últimos 30 dias: " + ", ".join(nomes.get(k, k) for k in sorted(nunca_antes)))

st.subheader("Comparação por cargo")
top_cargo = market.frequencia_competencias(snap, mascara, top=12)["skill_id"].tolist()
linhas_cargo = []
for fam in familias:
    mf = mascara & (c["familia"] == fam)
    if int(mf.sum()) < 10:
        continue
    f = market.frequencia_competencias(snap, mf)
    f = f[f["skill_id"].isin(top_cargo)].assign(familia=fam, n=int(mf.sum()))
    linhas_cargo.append(f)
if linhas_cargo:
    cargo = pd.concat(linhas_cargo).assign(competencia=lambda d: d["skill_id"].map(nomes))
    st.altair_chart(alt.Chart(cargo).mark_rect().encode(
        x=alt.X("familia:N", title=None), y=alt.Y("competencia:N", title=None, sort=[nomes.get(k, k) for k in top_cargo]),
        color=alt.Color("percentual:Q", title="% das vagas", scale=alt.Scale(scheme="purples")),
        tooltip=["familia", "competencia", "percentual", "n"]), width="stretch")
    st.caption("Famílias com menos de 10 vagas no recorte ficam de fora. n por família no tooltip.")
else:
    st.caption("Sem famílias com amostra suficiente no recorte.")

st.subheader("Distribuição dos requisitos")
col_a, col_b = st.columns(2)
with col_a:
    dist = market.frequencia_competencias(snap, mascara, top=12)
    if not dist.empty:
        d = dist.assign(competencia=dist["skill_id"].map(nomes), desejavel=dist["vagas"] - dist["vagas_requisito"])
        longo = d[["competencia", "vagas_requisito", "desejavel"]].melt(id_vars="competencia", var_name="tipo", value_name="vagas")
        longo["tipo"] = longo["tipo"].map({"vagas_requisito": "requisito", "desejavel": "desejável"})
        st.altair_chart(alt.Chart(longo).mark_bar().encode(
            x=alt.X("vagas:Q", stack="normalize", title="proporção"), y=alt.Y("competencia:N", sort="-x", title=None),
            color=alt.Color("tipo:N", title=None), tooltip=["competencia", "tipo", "vagas"]), width="stretch")
        st.caption("Requisito × desejável por competência (heurística de seções da vaga).")
with col_b:
    por_vaga = snap.skills[snap.skills["job_id"].isin(c.loc[mascara, "job_id"])].groupby("job_id")["skill_id"].nunique()
    por_vaga = por_vaga.reindex(c.loc[mascara, "job_id"], fill_value=0)
    st.altair_chart(alt.Chart(pd.DataFrame({"competencias": por_vaga.clip(upper=15)})).mark_bar().encode(
        x=alt.X("competencias:O", title="competências identificadas por vaga (15 = 15 ou mais)"),
        y=alt.Y("count():Q", title="vagas")), width="stretch")
    st.caption(f"{int((por_vaga == 0).sum())} vaga(s) sem competência identificada (trechos curtos de agregador).")

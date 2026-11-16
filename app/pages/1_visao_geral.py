import altair as alt
import pandas as pd
import streamlit as st
from components import data

from jobradar.analytics import market
from jobradar.storage import utcnow

st.title("Visão geral")
if data.estado_vazio():
    st.stop()

snap = data.snapshot()
agora = utcnow()
r = market.resumo(snap, agora)
t, q = r["totais"], r["qualidade"]
data.badge("observado")

c = st.columns(5)
c[0].metric("Vagas observadas", t["vagas_observadas"], help="Vagas únicas (duplicatas entre fontes removidas)")
c[1].metric("Ativas", t["ativas"], help="Observadas nos últimos 14 dias")
c[2].metric("Status desconhecido", t["status_desconhecido"], help="Sem observação recente e sem evidência de encerramento")
c[3].metric("Novas (7 dias)", t["novas_7_dias"])
c[4].metric("Novas (30 dias)", t["novas_30_dias"])

ult = market.ultima_execucao_ok(snap)
st.caption(f"Última execução bem-sucedida: **{pd.Timestamp(ult['finalizada_em']).tz_convert('America/Sao_Paulo'):%d/%m/%Y %H:%M}** "
           f"({ult['status']})" if ult else "Nenhuma execução bem-sucedida ainda.")

st.subheader("Fontes")
fontes = pd.DataFrame(market.fontes(snap))
if not fontes.empty:
    st.dataframe(fontes, hide_index=True, width="stretch")

col1, col2 = st.columns(2)
with col1:
    st.subheader("Competências mais frequentes")
    freq = market.frequencia_competencias(snap, top=12)
    if freq.empty:
        st.caption("Sem competências extraídas ainda.")
    else:
        freq["competencia"] = freq["skill_id"].map(data.nomes())
        st.altair_chart(alt.Chart(freq).mark_bar().encode(
            x=alt.X("percentual:Q", title="% das vagas"), y=alt.Y("competencia:N", sort="-x", title=None),
            tooltip=["competencia", "vagas", "percentual", "percentual_requisito"]), width="stretch")
        st.caption(f"Base: {int(freq['n'].iloc[0])} vagas únicas. Extração por taxonomia configurável (inferida).")
with col2:
    st.subheader("Qualidade e cobertura")
    st.dataframe(pd.DataFrame([
        ("Execuções", q["execucoes"]), ("Execuções com falha", q["execucoes_com_falha"]),
        ("Registros coletados", q["registros_coletados"]), ("Registros inválidos", q["registros_invalidos"]),
        ("Taxa de inválidos (%)", q["taxa_invalidos_pct"]),
        ("Vagas sem data de publicação (%)", q["vagas_sem_data_publicacao_pct"]),
        ("Vagas sem empresa (%)", q["vagas_sem_empresa_pct"]),
        ("Duplicatas entre fontes", t["duplicatas_entre_fontes"]),
    ], columns=["Indicador", "Valor"]).astype({"Valor": str}), hide_index=True, width="stretch")
    st.caption("A amostra reflete as fontes e termos configurados, não o mercado inteiro.")

st.subheader("Saúde da operação")
from jobradar.analytics import saude  # noqa: E402

_cfg = data.settings().sources.get("saude")
_ind = saude.indicadores(data.lake(), agora, _cfg)
_al = saude.alertas(_ind, _cfg)
if _al:
    st.warning("**Alertas:** " + "; ".join(_al))
else:
    st.success("Nenhum alerta: execuções, fontes, extração e validações dentro dos limites (config/sources.yaml → saude).")
_e = _ind["execucao"]
c = st.columns(5)
c[0].metric("Falha 7d / 30d", f"{_e['taxa_falha_7d_pct'] or 0}% / {_e['taxa_falha_30d_pct'] or 0}%")
c[1].metric("Duração mediana 7d", f"{_e['duracao_mediana_7d_s'] or 0:.0f} s")
c[2].metric("Horas desde o último sucesso", _e["horas_desde_ultimo_sucesso"])
c[3].metric("Validações com falha (7d)", _ind["validacoes"]["falhas_7d"])
c[4].metric("Custo de IA", f"US$ {_ind['custo_ia_usd']:.2f}", help="Extração por regras e embeddings locais: sem API paga")
if _ind["extracao_por_fonte"]:
    st.dataframe(pd.DataFrame(_ind["extracao_por_fonte"]).rename(columns={
        "fonte": "Fonte", "vagas": "Vagas (30 dias)", "com_competencia_pct": "Com competência (%)",
        "competencias_por_vaga": "Competências por vaga"}), hide_index=True, width="stretch")

st.subheader("Execuções recentes")
runs = snap.runs.sort_values("iniciada_em", ascending=False).head(15)
st.dataframe(runs[["run_id", "status", "iniciada_em", "duracao_s"]], hide_index=True, width="stretch")

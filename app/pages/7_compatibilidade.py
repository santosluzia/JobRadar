"""Minha compatibilidade (Career Intelligence, 7.2) — PRIVADO.

Aderência por objetivo (perfil × currículo), por senioridade, classes do plano e evolução entre versões
do currículo (versões locais, ~/.jobradar). Aderência não é previsão de contratação.
"""
import pandas as pd
import streamlit as st
from components import data

from jobradar.curriculo import versoes
from jobradar.curriculo.diagnostico import diagnosticar
from jobradar.evolucao.mensal import serie_mercado_com_perfil_atual
from jobradar.storage import utcnow

st.title("Minha compatibilidade")
if data.estado_vazio():
    st.stop()
s = data.settings()
perfil = data.perfil()
if perfil.vazio:
    st.warning("Perfil não encontrado: a compatibilidade compara o seu perfil com as vagas.")
    st.stop()
tax = data.taxonomia()
nomes = data.nomes()
snap = data.snapshot()
scores = data.lake().read("gold/job_scores")
cv = versoes.carregar()
agora = utcnow()
st.caption("🔒 Privado. Aderência mede o quanto as suas evidências cobrem o que as vagas-alvo pedem; "
           "não é previsão de contratação. " + ("" if cv else "Sem currículo importado: só a aderência do perfil."))


@st.cache_data(ttl=300, show_spinner="Calculando por objetivo…")
def _diags(_marca: tuple) -> list[dict]:
    return [diagnosticar(snap, scores, p, cv, tax, s.scoring, s.filtros, agora) for p in perfil.por_objetivo()]


diags = _diags((perfil.hash, cv.versao_id if cv else "", agora.strftime("%Y%m%d%H")))
data.badge("inferido")
st.subheader("Aderência por objetivo profissional")
tab = pd.DataFrame([{"objetivo": d["objetivo"], "vagas-alvo (90 dias)": d["vagas_alvo"],
                     "perfil": d["aderencia"]["perfil"]["valor"],
                     "currículo": (d["aderencia"]["curriculo"] or {}).get("valor"),
                     "amostra": "pequena" if d["amostra_pequena"] else "ok"} for d in diags])
st.dataframe(tab.sort_values("perfil", ascending=False), hide_index=True, width="stretch")

obj = st.selectbox("Objetivo", [d["objetivo_id"] for d in diags],
                   format_func=lambda k: next(d["objetivo"] for d in diags if d["objetivo_id"] == k))
d = next(x for x in diags if x["objetivo_id"] == obj)
c1, c2, c3 = st.columns(3)
c1.metric("Comprovadas / compatíveis", len(d["compativeis"]))
c2.metric("Declaradas, não demonstradas", len(d["declaradas_mas_nao_demonstradas"]))
c3.metric("Lacunas recorrentes", len(d["requisitos_recorrentes_ausentes"]))
col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**Compatibilidade por senioridade**")
    st.dataframe(pd.DataFrame([{"senioridade": x["valor"], "vagas": x["n"], "perfil": x["perfil"], "currículo": x["curriculo"],
                                "amostra": "pequena" if x["amostra_pequena"] else "ok"} for x in d["por_senioridade"]]),
                 hide_index=True, width="stretch")
with col_b:
    st.markdown("**Por família de cargo**")
    st.dataframe(pd.DataFrame([{"família": x["valor"], "vagas": x["n"], "perfil": x["perfil"], "currículo": x["curriculo"]}
                               for x in d["por_familia"]]), hide_index=True, width="stretch")
st.markdown("**O que mais somou e o que mais faltou (perfil)**")
st.caption("Somaram: " + ", ".join(f"{nomes.get(x['skill_id'], x['skill_id'])} (+{x['pontos']})"
                                   for x in d["aderencia"]["perfil"]["somaram"]) + " · Faltaram: " +
           ", ".join(f"{nomes.get(x['skill_id'], x['skill_id'])} ({x['pontos']})" for x in d["aderencia"]["perfil"]["faltaram"]))

st.subheader("Evolução entre versões do currículo")
lista = versoes.listar()
if len(lista) < 1:
    st.info("Importe o currículo (página Meu currículo) para acompanhar a evolução entre versões.")
else:
    p = perfil.para(obj)
    linhas = []
    for v in lista[-10:]:
        dv = diagnosticar(snap, scores, p, versoes.carregar(v["versao_id"]), tax, s.scoring, s.filtros, agora)
        linhas.append({"versão": f"{v['criado_em']:%d/%m %H:%M}", "aderência do currículo": dv["aderencia"]["curriculo"]["valor"],
                       "competências com evidência": v["competencias"]})
    st.line_chart(pd.DataFrame(linhas).set_index("versão")["aderência do currículo"])
    st.caption("Cada versão medida contra a MESMA demanda atual do objetivo: a variação é do currículo, não do mercado.")

st.subheader("Como o mercado mudou em relação ao que você sabe hoje")
serie = serie_mercado_com_perfil_atual(snap, perfil.para(obj), s.filtros, s.scoring, agora)
if len(serie) >= 2:
    st.line_chart(serie.set_index("mes")["aderencia"])
st.caption("Perfil ATUAL contra a demanda de cada mês passado (não é o seu histórico pessoal; esse fica no "
           "Diagnóstico mensal). " + " · ".join(f"{r.mes}: n={r.vagas}" for r in serie.itertuples()))

"""Relatório Semanal de Evolução Profissional — PRIVADO. Gera o da semana sob demanda e mostra o histórico."""
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from components import data

from jobradar.notifications import semanal
from jobradar.notifications.radar import carregar_config
from jobradar.storage import utcnow

st.title("Relatório semanal")
if data.estado_vazio():
    st.stop()
s = data.settings()
if data.perfil().vazio:
    st.warning("Perfil não encontrado: o relatório compara o mercado com o seu perfil.")
    st.stop()
cfg = carregar_config(s.lake)
st.caption(f"Sai por e-mail às {cfg.semanal.dia} {cfg.semanal.horario} "
           f"({'ativo' if cfg.semanal.ativo else 'desativado'}; configure em private/radar.yaml → semanal). "
           "🔒 Nada desta página é publicado.")


@st.cache_data(ttl=300, show_spinner="Montando o relatório da semana…")
def _relatorio(_marca: str) -> tuple[str, str, dict]:
    agora = utcnow()
    hist = data.lake().read("private/relatorios_semanais")
    r = semanal.montar(data.settings(), agora, carregar_config(data.settings().lake), hist)
    assunto, corpo, _ = semanal.renderizar(r, agora)
    return assunto, corpo, {k: r[k] for k in ("semana", "objetivo", "oportunidades")}


marca = utcnow().strftime("%Y-%m-%d %H")
assunto, corpo, meta = _relatorio(marca)
data.badge("recomendacao")
st.markdown(f"**{assunto}**")
components.html(corpo, height=1400, scrolling=True)
st.download_button("Baixar este relatório (HTML)", corpo, file_name=f"relatorio_{meta['semana']}.html", mime="text/html")

hist = data.lake().read("private/relatorios_semanais")
if not hist.empty:
    st.subheader("Histórico")
    nomes = data.nomes()
    h = hist.sort_values("enviado_em", ascending=False).assign(
        oportunidades=lambda d: d["oportunidades"].map(lambda x: ", ".join(nomes.get(k, k) for k in json.loads(x or "[]"))),
        aderencia_perfil=lambda d: d["resumo"].map(lambda x: json.loads(x or "{}").get("aderencia_perfil")))
    st.dataframe(h[["semana", "objetivo_id", "status", "aderencia_perfil", "oportunidades", "enviado_em"]],
                 hide_index=True, width="stretch")
    st.line_chart(pd.DataFrame({"semana": h["semana"], "aderência do perfil": h["aderencia_perfil"]})
                  .dropna().drop_duplicates("semana").set_index("semana").sort_index())

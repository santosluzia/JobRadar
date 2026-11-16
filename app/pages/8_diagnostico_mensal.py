"""Diagnóstico mensal (Career Intelligence, 7.4) — PRIVADO. As 7 perguntas, com o histórico de retratos."""
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from components import data

from jobradar.analytics import market
from jobradar.notifications import mensal
from jobradar.notifications.radar import carregar_config
from jobradar.storage import utcnow

st.title("Diagnóstico mensal")
if data.estado_vazio():
    st.stop()
s = data.settings()
if data.perfil().vazio:
    st.warning("Perfil não encontrado: o diagnóstico compara o seu perfil com as vagas.")
    st.stop()
cfg = carregar_config(s.lake)
st.caption(f"O retrato do mês é gravado automaticamente no dia {cfg.mensal.dia} ({cfg.mensal.horario}), e o e-mail "
           f"{'sai' if cfg.mensal.ativo else 'está desativado'} (private/radar.yaml → mensal). 🔒 Nada é publicado.")

hist = data.lake().read("private/diagnosticos_mensais")


@st.cache_data(ttl=300, show_spinner="Montando o diagnóstico do mês…")
def _diag(_marca: str) -> tuple[str, str]:
    agora = utcnow()
    r = mensal.montar(data.settings(), agora, data.lake().read("private/diagnosticos_mensais"))
    assunto, corpo, _ = mensal.renderizar(r, agora, market.fontes(data.snapshot()))
    return assunto, corpo


assunto, corpo = _diag(utcnow().strftime("%Y-%m-%d %H"))
data.badge("recomendacao")
st.markdown(f"**{assunto}** _(mês corrente, parcial até o fechamento)_")
components.html(corpo, height=1300, scrolling=True)
st.download_button("Baixar (HTML)", corpo, file_name="diagnostico_mensal.html", mime="text/html")

ok = hist[hist["status"].isin(["enviado", "gerado"])] if not hist.empty else hist
if not ok.empty:
    st.subheader("Histórico de retratos")
    linhas = []
    for r in ok.itertuples():
        x = json.loads(r.retrato)
        linhas.append({"mês": x["mes"], "objetivo": x["objetivo"], "aderência do perfil": x["aderencia_perfil"],
                       "aderência do currículo": x["aderencia_curriculo"], "vagas no mês": x["vagas_mes"],
                       "prioritárias": ", ".join(data.nomes().get(k, k) for k in x["prioritarias"][:3])})
    h = pd.DataFrame(linhas).drop_duplicates(["mês", "objetivo"], keep="last")
    st.dataframe(h, hide_index=True, width="stretch")
    st.line_chart(h.pivot(index="mês", columns="objetivo", values="aderência do perfil"))
    st.caption("Subir a aderência não é garantia de empregabilidade; veja no diagnóstico quanto veio do mercado e quanto do seu perfil.")

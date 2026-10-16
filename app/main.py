"""Painel PRIVADO do JobRadar (roda só na sua máquina).

    streamlit run app/main.py

Lê o lake local (clone do repositório privado jobradar-data). A parte pública dos dados
é exibida no portfólio (santosluzia.com/jobradar), a partir do contrato v1.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))  # permite `from components...`

st.set_page_config(page_title="JobRadar", page_icon="📡", layout="wide")

paginas = [
    st.Page("pages/1_visao_geral.py", title="Visão geral", icon="📊", default=True),
    st.Page("pages/2_mercado.py", title="Mercado", icon="📈"),
    # Fora do menu por enquanto (dependem do perfil e das candidaturas). Para reativar, descomente:
    # st.Page("pages/3_aderencia_estudos.py", title="Minha aderência e estudos", icon="🎯"),
    # st.Page("pages/4_vagas.py", title="Vagas e candidaturas", icon="🗂️"),
]
st.navigation(paginas).run()
st.sidebar.caption("Painel privado · dados pessoais nunca saem desta máquina.")

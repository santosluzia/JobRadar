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

paginas = {
    "Mercado": [
        st.Page("pages/1_visao_geral.py", title="Visão geral", icon="📊", default=True),
        st.Page("pages/2_mercado.py", title="Radar de mercado", icon="📈"),
        st.Page("pages/4_vagas.py", title="Vagas", icon="🗂️"),
    ],
    # Career Intelligence (Etapa 7): tudo daqui é pessoal e só existe nesta máquina / no repositório privado.
    "Career Intelligence": [
        st.Page("pages/7_compatibilidade.py", title="Minha compatibilidade", icon="🧭"),
        st.Page("pages/3_aderencia_estudos.py", title="Minha Evolução Profissional", icon="🎯"),
        st.Page("pages/5_curriculo.py", title="Meu currículo", icon="📄"),
        st.Page("pages/6_relatorio_semanal.py", title="Relatório semanal", icon="🗓️"),
        st.Page("pages/8_diagnostico_mensal.py", title="Diagnóstico mensal", icon="📆"),
    ],
}
st.navigation(paginas).run()
st.sidebar.caption("Painel privado · dados pessoais nunca saem desta máquina.")

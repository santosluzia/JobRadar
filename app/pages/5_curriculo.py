"""Meu currículo — PRIVADO. Importação local, revisão manual, versões e diagnóstico por objetivo.

Tudo fica em $JOBRADAR_HOME (padrão ~/.jobradar), fora de qualquer repositório git.
"""
import json

import pandas as pd
import streamlit as st
from components import data

from jobradar.curriculo import ArquivoInvalido, Experiencia, servico, versoes
from jobradar.curriculo.estrutura import recalcular_competencias

st.title("Meu currículo")
st.caption(f"🔒 Privado: os dados ficam só nesta máquina, em `{versoes.pasta()}`, fora do git. "
           "Nada daqui vai para o CI, para o e-mail nem para os dados públicos.")
s = data.settings()
tax = data.taxonomia()
nomes = data.nomes()
aba_imp, aba_rev, aba_ver, aba_diag = st.tabs(["Importar", "Revisar e corrigir", "Versões", "Diagnóstico"])

with aba_imp:
    st.markdown("Envie o currículo em **PDF**, **DOCX** ou **TXT**. A leitura é local, sem IA e sem internet; "
                "a interpretação é um ponto de partida e pode ser corrigida na aba ao lado.")
    arq = st.file_uploader("Currículo", type=["pdf", "docx", "txt"])
    nota = st.text_input("Descrição desta versão (opcional)", placeholder="ex.: incluí o projeto de pipeline")
    guardar = st.checkbox("Guardar também o arquivo original (por padrão só fica o texto e a estrutura)")
    if arq is not None and st.button("Interpretar e salvar versão", type="primary"):
        try:
            cv = servico.importar(arq.getvalue(), arq.name, tax, nota=nota, guardar_original=guardar,
                                  retencao=s.scoring.get("privacidade"))
            st.success(f"Versão {cv.versao_id} salva: {len(cv.experiencias)} experiência(s), "
                       f"{len(cv.niveis())} competência(s) com evidência.")
        except ArquivoInvalido as e:
            st.error(str(e))

cv = versoes.carregar()
with aba_rev:
    if not cv:
        st.info("Nenhuma versão ainda. Importe o currículo na primeira aba.")
    else:
        st.caption(f"Versão {cv.versao_id} · {cv.origem.get('nome', '')}. Corrija o que a leitura errou; "
                   "o que você corrigir não é sobrescrito numa nova importação do mesmo currículo.")
        cab = pd.DataFrame([{"empresa": e.empresa, "cargo": e.cargo, "inicio": e.inicio or "", "fim": e.fim or "",
                             "atual": e.atual, "revisar": "⚠️" if e.revisar else ""} for e in cv.experiencias])
        editado = st.data_editor(cab, num_rows="dynamic", hide_index=True, width="stretch",
                                 disabled=["revisar"], key="exp")
        textos = []
        for i, e in enumerate(cv.experiencias):
            with st.expander(f"{e.cargo or '?'} · {e.empresa or '?'}"):
                desc = st.text_area("Atividades e resultados (uma por linha)", "\n".join(e.responsabilidades + e.resultados),
                                    key=f"desc{i}", height=150)
                textos.append(desc)
                st.caption("Competências encontradas: " + (", ".join(
                    f"{nomes.get(c.skill_id, c.skill_id)} [{c.nivel}]" for c in e.competencias) or "nenhuma"))
        if st.button("Salvar correções como nova versão"):
            novo = cv.model_copy(deep=True)
            exps = []
            for i, r in enumerate(editado.to_dict("records")):
                base = cv.experiencias[i] if i < len(cv.experiencias) else Experiencia()
                e = base.model_copy(deep=True)
                for campo in ("empresa", "cargo", "inicio", "fim", "atual"):
                    valor = r.get(campo) if campo == "atual" else (r.get(campo) or None if campo in ("inicio", "fim") else r.get(campo) or "")
                    if valor != getattr(base, campo):
                        setattr(e, campo, valor)
                        e.editados = sorted(set(e.editados) | {campo})
                if i < len(textos) and textos[i] != "\n".join(base.responsabilidades + base.resultados):
                    recalcular_competencias(e, textos[i], tax)
                    e.editados = sorted(set(e.editados) | {"responsabilidades", "resultados", "competencias"})
                e.revisar = False
                exps.append(e)
            novo.experiencias = exps
            v = servico.salvar_edicao(novo, tax, nota="correção manual", retencao=s.scoring.get("privacidade"))
            st.success(f"Versão {v.versao_id} salva.")
            st.rerun()

with aba_ver:
    lista = versoes.listar()
    if not lista:
        st.info("Nenhuma versão.")
    else:
        st.dataframe(pd.DataFrame(lista), hide_index=True, width="stretch")
        ids = [v["versao_id"] for v in lista]
        if len(ids) >= 2:
            c1, c2 = st.columns(2)
            de = c1.selectbox("De", ids, index=len(ids) - 2)
            para = c2.selectbox("Para", ids, index=len(ids) - 1)
            st.json(versoes.comparar(versoes.carregar(de), versoes.carregar(para)))
        with st.expander("Apagar"):
            alvo = st.selectbox("Versão", ids, key="apagar")
            if st.button("Apagar esta versão (definitivo)"):
                st.success(f"{versoes.apagar(alvo)} arquivo(s) apagado(s).")
                st.rerun()

with aba_diag:
    perfil = data.perfil()
    if data.estado_vazio():          # o diagnóstico precisa das vagas; importar e revisar, não
        pass
    elif perfil.vazio:
        st.warning("Perfil não encontrado: o diagnóstico compara currículo, perfil e vagas.")
    else:
        objetivos = {o.id: o.nome for o in perfil.objetivos}
        obj = st.selectbox("Objetivo", list(objetivos), format_func=objetivos.get)
        salvar = st.checkbox("Guardar no histórico")
        d = servico.diagnostico(s, obj, salvar=salvar)[0]
        data.badge("inferido")
        if d["amostra_pequena"]:
            st.warning(f"Só {d['vagas_alvo']} vagas-alvo: leia como indício.")
        ad = d["aderencia"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Aderência do perfil", ad["perfil"]["valor"])
        c2.metric("Aderência do currículo", ad["curriculo"]["valor"] if ad["curriculo"] else "—")
        c3.metric("Vagas-alvo", d["vagas_alvo"])
        st.caption(d["aviso"])
        rec = pd.DataFrame([{"recorte": f"{k}: {x['valor']}", "vagas": x["n"], "perfil": x["perfil"],
                             "currículo": x["curriculo"], "amostra": "pequena" if x["amostra_pequena"] else "ok"}
                            for k in ("por_familia", "por_senioridade") for x in d[k]])
        st.dataframe(rec, hide_index=True, width="stretch")
        def tabela(chave, titulo):
            itens = d[chave]
            st.markdown(f"**{titulo}** ({len(itens)})")
            if itens:
                st.dataframe(pd.DataFrame([{"competência": x["nome"], "% vagas": x["pct"], "perfil": x["nivel_perfil"],
                                            "currículo": x["nivel_curriculo"]} for x in itens]),
                             hide_index=True, width="stretch")
        tabela("compativeis", "Compatíveis")
        tabela("declaradas_mas_nao_demonstradas", "Você declara, o currículo não mostra")
        tabela("requisitos_recorrentes_ausentes", "Requisitos recorrentes ausentes")
        st.subheader("Sugestões")
        data.badge("recomendacao")
        for sg in d["sugestoes"]:
            st.markdown(f"- {sg['texto']}")
        hist = versoes.historico(objetivo_id=obj)
        if hist:
            st.subheader("Histórico deste objetivo")
            st.line_chart(pd.DataFrame([{"quando": h["gerado_em"][:16], "perfil": h["aderencia"]["perfil"]["valor"],
                                         "currículo": (h["aderencia"]["curriculo"] or {}).get("valor")} for h in hist])
                          .set_index("quando"))
        st.download_button("Baixar diagnóstico (JSON)", json.dumps(d, ensure_ascii=False, indent=2, default=str),
                           file_name=f"diagnostico_{obj}.json")

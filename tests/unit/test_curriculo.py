"""Etapa 3: leitura, interpretação, versões e perfil com vários objetivos. Só dados FICTÍCIOS."""
import io
import zipfile
from pathlib import Path

import pytest

from jobradar.curriculo import ArquivoInvalido, interpretar, ler, reaplicar_edicoes
from jobradar.curriculo import versoes
from jobradar.curriculo.estrutura import recalcular_competencias
from jobradar.scoring import Profile, melhor_por_vaga
from jobradar.settings import CONFIG_DIR, _yaml
from jobradar.transformations.skills import Taxonomy

TAX = Taxonomy(_yaml(CONFIG_DIR / "skills.yaml"))
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "curriculo_ficticio.txt"
TEXTO = FIXTURE.read_text(encoding="utf-8")


def pdf_minimo(linhas: list[str]) -> bytes:
    """PDF de texto válido, gerado na mão (os testes não dependem de gerador de PDF)."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    stream = "BT /F1 10 Tf 40 800 Td 13 TL " + " ".join(f"({esc(l)}) '" for l in linhas) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


# ---------------------------------------------------------------- leitura
def test_le_txt_pdf_e_docx():
    assert "Empresa Fictícia" in ler(TEXTO.encode(), "cv.txt").texto
    pytest.importorskip("pypdf")
    linhas = ["Experiencia Profissional", "Analista de Dados | Empresa Teste | 01/2023 - atual",
              "- Consultas SQL e dashboards em Power BI para a diretoria financeira da empresa.",
              "- Pipelines em Python com pandas para integrar fontes de dados internas e externas."] * 2
    t = ler(pdf_minimo(linhas), "cv.pdf")
    assert t.tipo == "pdf" and "Power BI" in t.texto and len(t.sha256) == 64
    docx = pytest.importorskip("docx")
    d = docx.Document()
    for l in TEXTO.splitlines():
        d.add_paragraph(l)
    buf = io.BytesIO()
    d.save(buf)
    assert "Empresa Exemplo Ltda" in ler(buf.getvalue(), "cv.docx").texto


@pytest.mark.parametrize("conteudo,nome,erro", [
    (b"", "cv.pdf", "vazio"),
    (b"MZ\x90\x00executavel", "cv.pdf", "formato"),                 # extensão mentindo
    (b"x" * (5 * 1024 * 1024 + 1), "cv.txt", "maior"),
    (b"curto demais", "cv.txt", "texto"),                          # PDF escaneado cai aqui também
], ids=["vazio", "extensao_falsa", "grande_demais", "sem_texto"])
def test_arquivo_invalido_e_recusado(conteudo, nome, erro):
    with pytest.raises(ArquivoInvalido, match=erro):
        ler(conteudo, nome)


def test_zip_que_nao_e_docx_e_recusado():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("algo.txt", "x" * 500)
    with pytest.raises(ArquivoInvalido, match="DOCX"):
        ler(buf.getvalue(), "cv.docx")


# ---------------------------------------------------------------- interpretação
def test_interpreta_experiencias_em_layouts_diferentes():
    cv = interpretar(TEXTO, TAX)
    e1, e2 = cv.experiencias
    assert (e1.empresa, e1.cargo, e1.inicio, e1.atual) == ("Empresa Fictícia S.A.", "Analista de Dados Pleno", "2022-03", True)
    assert (e2.empresa, e2.cargo, e2.inicio, e2.fim) == ("Empresa Exemplo Ltda", "Estagiária de BI", "2020-01", "2022-02")
    assert {a.skill_id for a in e1.competencias} >= {"oracle", "power_bi", "python", "sql"}
    assert all(a.evidencia in TEXTO.replace("- ", "") or a.evidencia.strip("…") in TEXTO for a in e1.competencias)


def test_nada_e_inventado():
    cv = interpretar(TEXTO, TAX)
    linhas = {l.lstrip("- ").strip() for l in TEXTO.splitlines()}
    for e in cv.experiencias:
        assert set(e.responsabilidades + e.resultados) <= linhas        # só frases do seu texto
    # "resultado" = frase que já tem número; a estagiária não tem nenhum
    assert cv.experiencias[0].resultados == [l for l in linhas if "40%" in l]
    assert cv.experiencias[1].resultados == []


def test_curso_e_certificacao_nao_sao_experiencia_profissional():
    n = interpretar(TEXTO, TAX).niveis()
    assert n["databricks"] == n["airflow"] == "parcial"          # só certificação/curso
    assert n["python"] == "comprovada" and n["docker"] == "declarada"  # docker só na lista


def test_correcao_manual_sobrevive_a_nova_interpretacao():
    cv = interpretar(TEXTO, TAX)
    cv.experiencias[1].cargo = "Estagiária de Business Intelligence"
    cv.experiencias[1].editados = ["cargo"]
    novo = reaplicar_edicoes(interpretar(TEXTO, TAX), cv)
    assert novo.experiencias[1].cargo == "Estagiária de Business Intelligence"
    e = recalcular_competencias(novo.experiencias[1], "Modelagem dimensional no Snowflake.\nReduzi 30% do custo.", TAX)
    assert {"snowflake", "modelagem"} <= {a.skill_id for a in e.competencias} and e.resultados == ["Reduzi 30% do custo."]


# ---------------------------------------------------------------- versões (pasta local)
def test_versoes_salvar_comparar_e_apagar_de_verdade(tmp_path):
    home = tmp_path / "home"
    v1 = interpretar(TEXTO, TAX)
    versoes.salvar(v1, home, original=b"%PDF-1.4 original")
    v2 = interpretar(TEXTO.replace("- Apoio na manutenção", "- Modelagem dimensional no Snowflake.\n- Apoio na manutenção"), TAX)
    v2.versao_id = v2.versao_id[:-6] + "aaaaaa"
    versoes.salvar(v2, home)
    assert [v["versao_id"] for v in versoes.listar(home)] == [v1.versao_id, v2.versao_id]   # cronológica
    diff = versoes.comparar(v1, v2)
    assert "snowflake" in diff["competencias_novas"] and diff["experiencias_alteradas"]
    versoes.salvar_diagnostico({"gerado_em": "2026-11-12T10:00:00", "versao_id": v1.versao_id, "objetivo_id": "x"}, home)
    assert versoes.apagar(v1.versao_id, home) == 3                    # versão + original + diagnóstico
    assert versoes.carregar(v1.versao_id, home) is None
    versoes.apagar(home=home, tudo=True)
    assert not any((home / "curriculo").rglob("*.json"))


def test_id_de_versao_nao_vira_caminho(tmp_path):
    with pytest.raises(ValueError):
        versoes.carregar("../../segredo", tmp_path)


def test_pasta_privada_dentro_de_repositorio_git_e_recusada(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(versoes.PastaInsegura):
        versoes.pasta(tmp_path / "repo" / "privado")


# ---------------------------------------------------------------- perfil com vários objetivos
PERFIL_V2 = {
    "objetivos": [{"id": "engenharia", "nome": "Engenharia de Dados", "familias": ["engenharia_dados"],
                   "senioridades": ["junior", "pleno"]},
                  {"id": "governanca", "nome": "Governança", "familias": ["governanca_qualidade"]}],
    "competencias": [{"skill": "sql", "nivel": "profissional"}],
}


def test_perfil_com_varios_objetivos_e_formato_antigo():
    p = Profile.from_dict(PERFIL_V2)
    assert [o.id for o in p.objetivos] == ["engenharia", "governanca"] and p.objetivo_id == "engenharia"
    g = p.para("governanca")
    assert g.familias == ["governanca_qualidade"] and g.nivel("sql") == "profissional"   # competências são suas
    antigo = Profile.from_dict({"objetivo": {"familias": ["analise_dados"]}, "competencias": []})
    assert [o.id for o in antigo.objetivos] == ["principal"] and antigo.familias == ["analise_dados"]
    with pytest.raises(KeyError):
        p.para("inexistente")


@pytest.mark.parametrize("estrago", [
    lambda d: d.update(objetivo={"familias": ["engenharia_dados"]}),          # dois formatos juntos
    lambda d: d["objetivos"].append(dict(d["objetivos"][0])),                  # id repetido
    lambda d: d["objetivos"][0].update(familias=["dados"]),                    # família fora do enum
    lambda d: d["competencias"][0].update(nivel="expert"),
    lambda d: d.update(campo_errado=1),
])
def test_perfil_invalido_falha_cedo(estrago):
    import copy
    d = copy.deepcopy(PERFIL_V2)
    estrago(d)
    with pytest.raises(ValueError):
        Profile.from_dict(d)


def test_melhor_por_vaga():
    import pandas as pd
    sc = pd.DataFrame([{"job_id": "a", "score": 40, "objetivo_id": "x"}, {"job_id": "a", "score": 70, "objetivo_id": "y"},
                       {"job_id": "b", "score": 10, "objetivo_id": "x"}])
    m = melhor_por_vaga(sc).set_index("job_id")
    assert m.loc["a", "objetivo_id"] == "y" and len(m) == 2

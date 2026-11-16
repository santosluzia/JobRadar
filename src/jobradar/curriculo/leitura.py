"""Leitura LOCAL de currículo (PDF, DOCX ou texto). Nenhuma chamada de rede.

- PDF com `pypdf` (BSD) e DOCX com `python-docx` (MIT): dependência opcional `.[curriculo]`.
- Limite de tamanho e conferência do tipo REAL do arquivo (assinatura), não só da extensão.
- PDF escaneado (imagem) não tem texto: o erro diz isso, em vez de devolver um currículo vazio.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass

LIMITE_BYTES = 5 * 1024 * 1024
MIN_CARACTERES = 200


class ArquivoInvalido(ValueError):
    pass


@dataclass(frozen=True)
class TextoCurriculo:
    texto: str
    tipo: str          # pdf | docx | txt
    nome: str
    sha256: str        # do arquivo original (o arquivo em si não é guardado, por padrão)


def _tipo(conteudo: bytes, nome: str) -> str:
    if conteudo.startswith(b"%PDF-"):
        return "pdf"
    if conteudo.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        raise ArquivoInvalido("arquivo compactado que não é DOCX")
    if nome.lower().endswith((".txt", ".md")):
        try:
            conteudo.decode("utf-8")
            return "txt"
        except UnicodeDecodeError as e:
            raise ArquivoInvalido("texto que não está em UTF-8") from e
    raise ArquivoInvalido("formato não suportado: envie PDF, DOCX ou TXT")


def _pdf(conteudo: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise ArquivoInvalido('leitura de PDF requer: pip install -e ".[curriculo]"') from e
    leitor = PdfReader(io.BytesIO(conteudo))
    if leitor.is_encrypted:
        raise ArquivoInvalido("PDF protegido por senha: exporte uma cópia sem senha")
    return "\n".join((p.extract_text() or "") for p in leitor.pages)


def _docx(conteudo: bytes) -> str:
    try:
        import docx
    except ImportError as e:  # pragma: no cover
        raise ArquivoInvalido('leitura de DOCX requer: pip install -e ".[curriculo]"') from e
    doc = docx.Document(io.BytesIO(conteudo))
    linhas = [p.text for p in doc.paragraphs]
    for tabela in doc.tables:                    # currículo em duas colunas costuma ser tabela
        for linha in tabela.rows:
            for celula in linha.cells:
                linhas.extend(p.text for p in celula.paragraphs)
    return "\n".join(linhas)


def ler(conteudo: bytes, nome: str) -> TextoCurriculo:
    if len(conteudo) > LIMITE_BYTES:
        raise ArquivoInvalido(f"arquivo maior que {LIMITE_BYTES // (1024 * 1024)} MB")
    if not conteudo:
        raise ArquivoInvalido("arquivo vazio")
    tipo = _tipo(conteudo, nome)
    bruto = {"pdf": _pdf, "docx": _docx, "txt": lambda b: b.decode("utf-8")}[tipo](conteudo)
    linhas = [" ".join(l.split()) for l in bruto.replace("\r", "\n").split("\n")]
    texto = "\n".join(l for l in linhas if l)
    if len(texto) < MIN_CARACTERES:
        raise ArquivoInvalido("quase nenhum texto encontrado: se for PDF escaneado (imagem), exporte o "
                              "currículo como PDF de texto ou DOCX")
    return TextoCurriculo(texto, tipo, nome, hashlib.sha256(conteudo).hexdigest())

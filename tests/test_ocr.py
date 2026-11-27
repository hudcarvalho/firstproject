"""OCR gratuito (Tesseract) no conversor de PDF em Excel: PDF escaneado e fotos."""
import random
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app import ocr
from app.pdf_excel import AVISO_OCR, ErroPDF, converter
from tests.test_pdf_excel import _pdf_relatorio

precisa_tesseract = pytest.mark.skipif(not ocr.disponivel() or ocr.idioma() is None,
                                       reason="Tesseract com português não instalado")


def _imagem_escaneada():
    """O balancete de teste 'fotografado': um pouco torto, com ruído e desfocado."""
    import pypdfium2
    from PIL import ImageFilter
    doc = pypdfium2.PdfDocument(_pdf_relatorio())
    img = doc[0].render(scale=200 / 72).to_pil().convert("L")
    doc.close()
    img = img.rotate(0.6, expand=True, fillcolor=255)
    rnd, px = random.Random(1), img.load()
    for _ in range(4000):
        px[rnd.randrange(img.width), rnd.randrange(img.height)] = rnd.randrange(0, 255)
    return img.filter(ImageFilter.GaussianBlur(0.6))


def _corpo(xlsx):
    linhas = list(load_workbook(BytesIO(xlsx)).active.iter_rows(values_only=True))
    assert linhas[0][0] == AVISO_OCR
    return linhas[1:]


def test_ler_tsv_agrupa_linha_torta():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "4\t1\t1\t1\t1\t0\t0\t0\t900\t40\t-1\t\n"
           "5\t1\t1\t1\t1\t1\t100\t100\t80\t30\t95\tCaixa\n"
           "5\t1\t1\t1\t1\t2\t800\t112\t120\t30\t91\t1.234,56\n"
           "5\t1\t1\t1\t1\t3\t300\t104\t40\t30\t5\t~\n")
    palavras = ocr.ler_tsv(tsv, escala=2)
    assert [p["text"] for p in palavras] == ["Caixa", "1.234,56"]  # sujeira de baixa confiança sai
    assert palavras[0]["x0"] == 50 and palavras[0]["top"] == palavras[1]["top"]  # mesma linha


def test_reconhece_imagem_pelos_bytes():
    assert ocr.e_imagem(b"\xff\xd8\xff\xe0....") and ocr.e_imagem(b"\x89PNG\r\n\x1a\n...")
    assert not ocr.e_imagem(b"%PDF-1.7") and not ocr.e_imagem(b"PK\x03\x04")


def test_sem_tesseract_avisa(monkeypatch):
    monkeypatch.setattr(ocr, "disponivel", lambda: False)
    b = BytesIO()
    _imagem_escaneada().save(b, "PDF", resolution=200)
    with pytest.raises(ErroPDF, match="OCR"):
        converter(b.getvalue())


@precisa_tesseract
def test_pdf_escaneado_vira_planilha(client):
    b = BytesIO()
    _imagem_escaneada().save(b, "PDF", resolution=200)
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(b.getvalue()), "escaneado.pdf"),
                                                    "modo": "auto", "numeros": "on"},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.headers["X-OCR"] == "1"
    linhas = _corpo(r.data)
    assert ("Conta", "Descrição", "Débito", "Crédito") in linhas
    assert ("1.1.01", "Caixa e equivalentes", 12345.67, None) in linhas
    assert ("1.1.02", "Bancos conta movimento", 1000, -250.5) in linhas
    assert ("3.1.01", "Receita de vendas — ação", 0, 1234567.89) in linhas


@precisa_tesseract
def test_foto_jpg_e_varios_arquivos(client):
    img = _imagem_escaneada()
    j = BytesIO()
    img.crop((0, 0, img.width, img.height // 3)).save(j, "JPEG", quality=70)
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(j.getvalue()), "foto.jpg"), "numeros": "on"},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.headers["X-OCR"] == "1" and "foto.xlsx" in r.headers["Content-Disposition"]
    assert ("2.1.01", "Fornecedores", None, 98765.43) in _corpo(r.data)
    # foto junto com um PDF comum: uma planilha só, com a foto marcada como lida por OCR
    r = client.post("/ferramentas/pdf-excel", data={
        "arquivo": [(BytesIO(j.getvalue()), "foto.jpg"), (BytesIO(_pdf_relatorio()), "balancete.pdf")],
        "modo": "layout", "numeros": "on"}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.headers["X-OCR"] == "1"
    linhas = list(load_workbook(BytesIO(r.data)).active.iter_rows(values_only=True))
    arquivos = {l[0] for l in linhas[2:]}
    assert arquivos == {"foto.jpg (lido por OCR)", "balancete.pdf"}


def test_arquivo_invalido(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(b"texto qualquer"), "x.txt")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "imagem (JPG/PNG)" in r.get_data(as_text=True)

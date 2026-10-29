from decimal import Decimal as D
from io import BytesIO

from openpyxl import load_workbook

from app.pdf_excel import numero_br
from app.pdf_simples import Documento


def _pdf_relatorio():
    """Relatório sem bordas: título, cabeçalho e linhas com código, descrição e dois valores."""
    doc = Documento("Balancete")
    doc.texto(40, 40, "Balancete de verificação — Empresa Teste", 13, negrito=True)
    y = 80
    for x, t, al in ((40, "Conta", "esquerda"), (100, "Descrição", "esquerda"),
                     (420, "Débito", "direita"), (540, "Crédito", "direita")):
        doc.texto(x, y, t, 9, negrito=True, alinhar=al)
    linhas = [("1.1.01", "Caixa e equivalentes", "12.345,67", ""),
              ("1.1.02", "Bancos conta movimento", "1.000,00", "(250,50)"),
              ("2.1.01", "Fornecedores", "", "98.765,43"),
              ("3.1.01", "Receita de vendas — ação", "0,00", "1.234.567,89")]
    for conta, desc, deb, cred in linhas:
        y += 14
        doc.texto(40, y, conta, 9)
        doc.texto(100, y, desc, 9)
        doc.texto(420, y, deb, 9, alinhar="direita")
        doc.texto(540, y, cred, 9, alinhar="direita")
    return doc.gerar()


def test_numero_br():
    assert numero_br("1.234,56") == D("1234.56")
    assert numero_br("(1.234,56)") == D("-1234.56")
    assert numero_br("-1.234,56") == D("-1234.56") and numero_br("1.234,56-") == D("-1234.56")
    assert numero_br("R$ 10,00") == D("10.00") and numero_br("1.234,56 D") == D("1234.56")
    for texto in ("12.345.678/0001-90", "01/2026", "1001", "abc", ""):
        assert numero_br(texto) is None


def test_tela_e_menu(client):
    assert "Converter PDF em Excel" in client.get("/empresas").get_data(as_text=True)
    assert 'enctype="multipart/form-data"' in client.get("/ferramentas/pdf-excel").get_data(as_text=True)


def test_converte_relatorio_em_colunas(client):
    r = client.post("/ferramentas/pdf-excel", data={
        "arquivo": (BytesIO(_pdf_relatorio()), "Balancete março.pdf"), "modo": "layout", "numeros": "on",
    }, content_type="multipart/form-data")
    assert r.status_code == 200 and "Balancete%20mar%C3%A7o.xlsx" in r.headers["Content-Disposition"]
    assert r.headers["X-Paginas"] == "1"
    linhas = list(load_workbook(BytesIO(r.data)).active.iter_rows(values_only=True))
    assert linhas[0][0] == "Balancete de verificação — Empresa Teste"
    assert linhas[1] == ("Conta", "Descrição", "Débito", "Crédito")
    assert linhas[2] == ("1.1.01", "Caixa e equivalentes", 12345.67, None)
    assert linhas[3] == ("1.1.02", "Bancos conta movimento", 1000, -250.5)
    assert linhas[5] == ("3.1.01", "Receita de vendas — ação", 0, 1234567.89)


def test_sem_converter_numeros_e_aba_por_pagina(client):
    r = client.post("/ferramentas/pdf-excel", data={
        "arquivo": (BytesIO(_pdf_relatorio()), "x.pdf"), "modo": "layout", "aba_por_pagina": "on",
    }, content_type="multipart/form-data")
    wb = load_workbook(BytesIO(r.data))
    assert wb.sheetnames == ["Página 1"]
    assert list(wb.active.iter_rows(values_only=True))[2][2] == "12.345,67"


def test_erros(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(b"nao sou pdf"), "a.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "não é um PDF" in r.get_data(as_text=True)
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(b"%PDF-1.4 quebrado"), "a.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Não foi possível ler" in r.get_data(as_text=True)
    # relatório sem bordas no modo "somente tabelas": nada a extrair
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_pdf_relatorio()), "a.pdf"), "modo": "tabelas"},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Nenhum texto encontrado" in r.get_data(as_text=True)

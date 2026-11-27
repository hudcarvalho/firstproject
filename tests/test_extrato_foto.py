"""Extrato Consolidado Inteligente do Santander fotografado: leitura por OCR, conferência com os
saldos do dia e com o resumo, e correção das trocas de dígito típicas do OCR."""
import random
from datetime import date
from decimal import Decimal as D
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app import extrato_foto_santander as fs
from app import ocr
from app.extrato_planilha import Movimento
from app.pdf_simples import Documento

precisa_tesseract = pytest.mark.skipif(not ocr.disponivel() or ocr.idioma() is None,
                                       reason="Tesseract com português não instalado")

LANCAMENTOS = [  # data, histórico (linhas), crédito, débito, saldo do fim do dia
    ("02/01", ["TARIFA MENSALIDADE PACOTE SERVICOS", "DEZEMBRO / 2025"], None, "224,00-", None),
    (None, ["RESGATE CONTAMAX AUTOMATICO"], "224,00", None, "0,00"),
    ("12/01", ["DEBITO AUT. FAT.CARTAO MASTER CARD", "FINAL 4666"], None, "1.732,20-", None),
    (None, ["RESGATE CDB/RDB"], "1.300,00", None, None),
    (None, ["PAGAMENTO DE BOLETO OUTROS BANCOS", "EXATA NEGOCIOS JURIDICOS"], None, "1.151,37-", None),
    (None, ["RESGATE CONTAMAX AUTOMATICO"], "1.583,57", None, "0,00"),
    ("15/01", ["TED RECEBIDA 956.843.608-15"], "207,69", None, None),
    (None, ["PAGAMENTO DE BOLETO", "EVINO PROCESSAD"], None, "207,69-", "0,00"),
]


def _pdf_extrato():
    doc = Documento("Extrato")
    doc.texto(40, 40, "Santander Empresas", 14, negrito=True)
    doc.texto(555, 40, "EXTRATO CONSOLIDADO INTELIGENTE", 9, alinhar="direita")
    doc.texto(555, 52, "janeiro/2026", 9, alinhar="direita")
    doc.texto(40, 80, "Resumo - janeiro/2026", 12, negrito=True)
    doc.texto(40, 100, "Nome", 8, negrito=True)
    doc.texto(40, 111, "EMPRESA DE TESTE LTDA", 9, negrito=True)
    doc.texto(40, 128, "Agência", 8, negrito=True)
    doc.texto(170, 128, "Conta Corrente", 8, negrito=True)
    doc.texto(40, 139, "4777", 9)
    doc.texto(170, 139, "13.000059-5", 9)
    resumo = [("(=) Saldo de Conta Corrente em 31/12", "0,00"), ("(+) Total de Créditos", "3.315,26"),
              ("(-) Total de Débitos", "3.315,26"), ("(=) Saldo de Conta Corrente em 31/01", "0,00"),
              ("(+) Saldo de Investimentos com Resgate Automático", "297,41"), ("(=) Saldo Disponível", "297,41"),
              ("(+) Limite de Cheque Empresa", "13.000,00"), ("(=) Saldo Disponível Total em 31/01", "13.297,41")]
    y = 162
    for rotulo, valor in resumo:
        doc.texto(40, y, rotulo, 9, negrito=True)
        doc.texto(380, y, valor, 9, negrito=True, alinhar="direita")
        y += 15
    y += 20
    doc.texto(40, y, "Conta Corrente", 12, negrito=True)
    doc.texto(40, y + 18, "Movimentação", 11)
    y += 40
    doc.texto(40, y + 8, "Data", 8, negrito=True)
    doc.texto(80, y + 8, "Descrição", 8, negrito=True)
    doc.texto(300, y + 8, "Nº Documento", 8, negrito=True)
    doc.texto(400, y, "Movimentos (R$)", 8, negrito=True)
    doc.texto(395, y + 12, "Créditos", 8, negrito=True)
    doc.texto(455, y + 12, "Débitos", 8, negrito=True)
    doc.texto(550, y + 8, "Saldo (R$)", 8, negrito=True, alinhar="direita")
    y += 28
    doc.texto(80, y, "SALDO EM 31/12", 8, negrito=True)
    doc.texto(550, y, "0,00", 8, negrito=True, alinhar="direita")
    for data, hist, cred, deb, saldo in LANCAMENTOS:
        y += 13
        if data:
            doc.texto(40, y, data, 8)
        doc.texto(80, y, hist[0], 8)
        doc.texto(330, y, "-", 8)
        if cred:
            doc.texto(430, y, cred, 8, alinhar="direita")
        if deb:
            doc.texto(490, y, deb, 8, alinhar="direita")
        if saldo:
            doc.texto(550, y, saldo, 8, alinhar="direita")
        for extra in hist[1:]:
            y += 11
            doc.texto(80, y, extra, 8)
    y += 13
    doc.texto(80, y, "SALDO EM 31/01", 8, negrito=True)
    doc.texto(550, y, "0,00", 8, negrito=True, alinhar="direita")
    doc.texto(40, y + 40, "Saldos por Período", 11)
    return doc.gerar()


def _foto():
    """O extrato 'fotografado': levemente torto, com ruído e desfocado."""
    import pypdfium2
    from PIL import ImageFilter
    pdf = pypdfium2.PdfDocument(_pdf_extrato())
    img = pdf[0].render(scale=220 / 72).to_pil().convert("L")
    pdf.close()
    img = img.rotate(0.7, expand=True, fillcolor=255)
    rnd, px = random.Random(3), img.load()
    for _ in range(5000):
        px[rnd.randrange(img.width), rnd.randrange(img.height)] = rnd.randrange(0, 255)
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    b = BytesIO()
    img.save(b, "JPEG", quality=80)
    return b.getvalue()


@precisa_tesseract
def test_foto_do_extrato_sai_organizada_e_conferida(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_foto()), "extrato.jpg"), "numeros": "on"},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.headers["X-OCR"] == "1"
    wb = load_workbook(BytesIO(r.data))
    assert wb.sheetnames == ["Resumo", "Extrato"]
    ws = wb["Extrato"]
    assert "Santander ag. 4777 c/c 13.000059-5" in ws["A1"].value and "OCR" in ws["A2"].value
    cab = [c.value for c in ws[4]]
    ent, sai, conf = cab.index("Entrada (R$)"), cab.index("Saída (R$)"), cab.index("Confere")
    linhas = [[c.value for c in row] for row in ws.iter_rows(min_row=6) if row[0].value]
    entradas = [l[ent] for l in linhas if l[ent] is not None]
    saidas = [l[sai] for l in linhas if l[sai] is not None]
    assert sum(1 for l in linhas if l[conf]) == 3  # saldo do banco nos 3 fins de dia
    assert entradas == [224, 1300, 1583.57, 207.69]
    assert saidas == [224, 1732.2, 1151.37, 207.69]
    assert [l[0].day for l in linhas] == [2, 2, 12, 12, 12, 12, 15, 15]
    assert linhas[0][1] == "TARIFA MENSALIDADE PACOTE SERVICOS"
    resumo = {row[0].value: row[2].value for row in wb["Resumo"].iter_rows(min_row=4, max_row=7)}
    assert resumo["Entradas (créditos)"] == 3315.26 and resumo["Saídas (débitos)"] == 3315.26


def _mov(entrada=None, saida=None, alternativas=(), votos=1, saldo=None):
    m = Movimento(date(2026, 1, 2), "X", D(entrada) if entrada else None, D(saida) if saida else None,
                  saldo_banco=D(saldo) if saldo is not None else None)
    m._alternativas, m._votos = [D(a) for a in alternativas], votos
    return m


def test_corrige_troca_de_digito_pelo_saldo_do_dia():
    from app.extrato_planilha import Extrato
    # 224,00 de tarifa e resgate de 724,00 (OCR leu 7 no lugar de 2): o dia não fecha com o saldo 0,00
    ex = Extrato(saldo_anterior=D("0"), movimentos=[_mov(saida="224.00", votos=3),
                                                     _mov(entrada="724.00", saldo="0.00")])
    fs._corrigir(ex, None, None, usar_saldo_final=False)
    assert ex.movimentos[1].entrada == D("224.00") and "724,00" in ex.movimentos[1].aviso
    assert ex.movimentos[0].saida == D("224.00") and not ex.movimentos[0].aviso


def test_prefere_ler_4_como_1_e_usa_as_outras_leituras():
    from app.extrato_planilha import Extrato
    ex = Extrato(saldo_anterior=D("29.42"), movimentos=[_mov(saida="480.92"),
                                                         _mov(entrada="151.50", alternativas=["161.50"], saldo="0")])
    fs._corrigir(ex, None, None, usar_saldo_final=False)
    assert ex.movimentos[0].saida == D("180.92")


def test_empate_nao_chuta_e_marca_o_dia():
    from app.extrato_planilha import Extrato
    # débito 182,55 e crédito 152,55 com saldo 0: tanto faz qual está errado -> não corrige, marca
    ex = Extrato(saldo_anterior=D("0"), movimentos=[_mov(saida="182.55"), _mov(entrada="152.55", saldo="0")])
    fs._corrigir(ex, None, None, usar_saldo_final=False)
    assert ex.movimentos[0].saida == D("182.55") and ex.movimentos[1].entrada == D("152.55")
    assert all("não fechou" in m.aviso for m in ex.movimentos)


def test_numeros_lidos_pelo_ocr():
    assert fs._num("1.442,69-") == (D("1442.69"), True)
    assert fs._num("14,153,28") == (D("14153.28"), False)
    assert fs._num("0,00.") == (D("0.00"), False)
    assert fs._num("266384") is None and fs._num("266384", sem_virgula=True) == (D("2663.84"), False)
    assert fs._num("1.22115", sem_virgula=True) == (D("1221.15"), False)
    assert fs._num("222", sem_virgula=True) is None


def test_limpa_historico():
    assert fs._limpar_hist("A PMES SIRESGATE CDBRDB") == "RESGATE CDBRDB"
    assert fs._limpar_hist("E APLICACAO CONTAMAX x") == "APLICACAO CONTAMAX"

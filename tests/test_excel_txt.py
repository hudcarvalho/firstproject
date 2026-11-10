from datetime import datetime
from io import BytesIO

from openpyxl import Workbook

ESPERADO = (b"1,02/01/2026,571,858,22.84,1006,IOF,,0\r\n"
            b"2,03/01/2026,16,858,700,1006,SUPRIMENTO DE CAIXA,,219\r\n"
            b"3,04/01/2026,628,858,400,1006,SUPRIMENTO DE CAIXA,,0\r\n"
            b"4,05/01/2026,1653,858,11.28,1006,TAR C/C SISPAG,,0\r\n"
            b"5,06/01/2026,37,858,2658,1006,VALORES A IDENTIFICA - INT PAG TIT 175324004590,,0\r\n"
            b"6,03/01/2018,172,858,940.95,1006,PAGAMENTO DE FGTS REF. 12/2017,,0\r\n")


def _planilha():
    wb = Workbook()
    ws = wb.active
    ws.append(["Data", None, None, "Lançamento", "Valor (R$)", "Participante"])
    for d, deb, cred, hist, v, p in (
            ("02/01/2026", 571, 858, "IOF", 22.84, None), ("03/01/2026", 16, 858, "SUPRIMENTO DE CAIXA", 700, 219),
            ("04/01/2026", 628, 858, "SUPRIMENTO DE CAIXA", 400, None),
            ("05/01/2026", 1653, 858, "TAR C/C SISPAG", 11.28, None),
            ("06/01/2026", 37, 858, "VALORES A IDENTIFICA - INT PAG TIT 175324004590", 2658, None),
            ("03/01/2018", 172, 858, "PAGAMENTO DE FGTS REF. 12/2017", 940.95, None)):
        ws.append([datetime.strptime(d, "%d/%m/%Y"), deb, cred, hist, v, p])
    ws.append([None, None, None, None, None, None])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_menu_e_tela(client):
    assert "Converter Excel em TXT" in client.get("/ferramentas/pdf-excel").get_data(as_text=True)
    r = client.get("/ferramentas/excel-txt")
    assert r.status_code == 200 and 'value="1006"' in r.get_data(as_text=True)


def test_converte_igual_ao_modelo(client):
    r = client.post("/ferramentas/excel-txt", data={"arquivo": (BytesIO(_planilha()), "lanc.xlsx"), "codigo": "1006"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.headers["X-Linhas"] == "6"
    assert "lanc.txt" in r.headers["Content-Disposition"]
    assert r.data == ESPERADO


def test_valores_texto_virgula_no_historico_e_codigo():
    from app.excel_txt import converter
    wb = Workbook()
    wb.active.append(["01/02/2026", "10", "20", "PAGTO X,Y", "1.234,50", ""])
    buf = BytesIO()
    wb.save(buf)
    txt, n = converter(buf.getvalue(), codigo="2000")
    assert n == 1 and txt == b"1,01/02/2026,10,20,1234.5,2000,PAGTO X.Y,,0\r\n"


def test_erros(client):
    r = client.post("/ferramentas/excel-txt", data={"arquivo": (BytesIO(b"nada"), "x.txt"), "codigo": "1006"},
                    content_type="multipart/form-data")
    assert "não é uma planilha" in r.get_data(as_text=True)
    wb = Workbook()
    wb.active.append(["Data", None, None, "Lançamento", "Valor", "Participante"])
    wb.active.append(["02/01/2026", 1, 2, "IOF", "abc", None])
    buf = BytesIO()
    wb.save(buf)
    r = client.post("/ferramentas/excel-txt", data={"arquivo": (BytesIO(buf.getvalue()), "x.xlsx"), "codigo": "1006"},
                    content_type="multipart/form-data")
    assert "linha 2: valor inválido" in r.get_data(as_text=True)

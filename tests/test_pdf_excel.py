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


def _pdf_extrato_itau():
    """Extrato mensal no layout do Itaú (posições das colunas iguais às do banco), dados fictícios."""
    doc = Documento("Extrato")
    t = doc.texto
    t(40, 30, "extrato mensal ag 1234 cc 12345-6 jul 2026 001|002", 8)
    t(40, 50, "CTC CENTRO", 8)
    t(40, 62, "EMPRESA FICTICIA LTDA", 8)
    t(40, 74, "AV PAULISTA 1000", 8)
    t(411, 110, "saldo em 30/06/26 saldo em 31/07/26", 8)
    t(58, 122, "01. Conta Corrente e Aplicações Automáticas", 9)
    t(421, 134, "R$ 1.000,00 R$ 1.500,00", 9)
    t(343, 150, "entradas (créditos)", 8)
    t(343, 162, "total 2.000,00", 8)
    t(343, 174, "saídas (débitos)", 8)
    t(343, 186, "total 1.500,00", 8)
    t(56, 210, "Conta Corrente | Movimentação", 9)
    for x, texto in ((150, "data"), (208, "descrição"), (357, "entradas"), (388, "R$"), (426, "saídas"),
                     (448, "R$"), (521, "saldo"), (541, "R$")):
        t(x, 230, texto, 8)
    linhas = [
        ("30/06", "Saldo anterior", None, None, "1.000,00"),
        ("01/07", "Sispag CLIENTE XPTO", "2.000,00", None, None),
        ("", "BOLETO PAGO FORNECEDOR", None, "500,00-", None),
        ("", "Apl Aplic Aut Mais", None, "1.499,00-", "1,00"),
        ("", "SALDO APLIC AUT MAIS", None, None, "2.499,00"),
        ("02/07", "PIX ENVIADO JOAO SILVA", None, "1.000,00-", None),
        ("", "Res Aplic Aut Mais", "1.000,00", None, "1,00"),
        ("", "SALDO APLIC AUT MAIS", None, None, "1.499,00"),
        ("31/07", "Saldo em C/C", None, None, "1,00"),
        ("", "Saldo final", None, None, "1.500,00"),
    ]
    y = 250
    for data, desc, ent, sai, saldo in linhas:
        y += 12
        t(150, y, data, 8)
        t(208, y, desc, 8)
        t(396, y, ent, 8, alinhar="direita")
        t(458, y, sai, 8, alinhar="direita")
        t(549, y, saldo, 8, alinhar="direita")
    doc.nova_pagina()
    t(40, 40, "CDB e Renda Fixa", 9)
    t(40, 60, "CDB-DI 15/02/22 15/02/27 10.000,00 100,00% DI 12.000,00 11.500,00", 8)
    t(40, 72, "total aplicações financeiras 10.000,00 12.000,00 11.500,00", 8)
    return doc.gerar()


def test_extrato_itau_organizado(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_pdf_extrato_itau()), "extrato.pdf")},
                    content_type="multipart/form-data")
    wb = load_workbook(BytesIO(r.data))
    assert wb.sheetnames == ["Resumo", "Extrato", "Investimentos CDB"]
    ext = wb["Extrato"]
    assert ext["A1"].value == "EMPRESA FICTICIA LTDA — Itaú ag. 1234 c/c 12345-6"
    linhas = [tuple(c.value for c in ext[r][:9]) for r in range(6, 9)]
    # as linhas internas da aplicação automática ficam de fora
    assert [l[1:6] for l in linhas] == [
        ("Sispag CLIENTE XPTO", "CLIENTE XPTO", "Recebimento Sispag", 2000, None),
        ("BOLETO PAGO FORNECEDOR", "FORNECEDOR", "Boletos/contas pagas", None, 500),
        ("PIX ENVIADO JOAO SILVA", "JOAO SILVA", "PIX enviado", None, 1000),
    ]
    # saldo do banco no fim do dia = aplicação automática + conta corrente, com conferência
    assert linhas[1][7] == 2500 and linhas[2][7] == 1500 and linhas[0][7] is None
    assert linhas[2][6] == "=G7+E8-F8" and linhas[2][8].startswith("=IF(ROUND(G8-H8,2)=0")
    assert ext["B9"].value == "TOTAIS DO MÊS" and ext["E9"].value == "=SUM(E6:E8)"
    res = wb["Resumo"]
    assert [res.cell(i, 3).value for i in range(4, 8)] == [1000, 2000, 1500, 1500]
    assert res["A13"].value == "Recebimento Sispag" and res["B13"].value.startswith("=SUMIFS(")
    inv = wb["Investimentos CDB"]
    assert [c.value for c in inv[4]][:7][3:] == [10000, 1, 12000, 11500]


def test_extrato_itau_no_modo_layout_fica_simples(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_pdf_extrato_itau()), "e.pdf"), "modo": "layout"},
                    content_type="multipart/form-data")
    assert load_workbook(BytesIO(r.data)).sheetnames == ["PDF"]


def _pdf_extrato_bradesco():
    """Extrato "Mensal / Por Período" no layout do Bradesco (registros de até 3 linhas), dados fictícios."""
    doc = Documento("Extrato")
    t = doc.texto
    t(155, 43, "Extrato Mensal / Por Período", 9)
    t(155, 58, "EMPRESA TESTE LTDA | CNPJ: 011.222.333/0001-81", 8)
    t(155, 70, "Nome do usuário: FULANO DE TAL", 8)
    t(547, 100, "Folha 1/1", 8)
    t(40, 178, "Extrato de: Ag: 1111 | CC: 0001234-5 | Entre 01/08/2026 e 31/08/2026", 8)
    for x, texto in ((44, "Data"), (104, "Lançamento"), (269, "Dcto."), (338, "Crédito (R$)"),
                     (428, "Débito (R$)"), (519, "Saldo (R$)")):
        t(x, 211, texto, 8)

    def linha(y, data="", nome="", doc_="", valor="", saldo="", tam=7):
        t(41, y, data, tam)
        t(101, y, nome, tam)
        t(266, y, doc_, tam)
        if valor:
            t(388 if not valor.startswith("-") else 475, y, valor, tam, alinhar="direita")
        t(563, y, saldo, tam, alinhar="direita")

    y = 230
    linha(y, "31/07/2026", "SALDO ANTERIOR", saldo="1.000,00")
    y += 10.3
    linha(y, "03/08/2026", "RENTAB.INVEST FACILCRED*", "677471", "1,12", "1.001,12")  # registro de uma linha
    y += 10.3
    t(101, y, "PIX RECEBIDO", 7)                                                     # nome acima
    linha(y + 4.4, "", "", "936154", "5.000,00", "6.001,12")
    t(101, y + 8.8, "REM: CLIENTE BOM LTDA 03/08", 7)                                 # complemento abaixo
    y += 19.3
    t(101, y, "PAGTO ELETRON COBRANCA", 7)
    linha(y + 4.4, "05/08/2026", "", "1252", "-4.389,70", "1.611,42")
    t(101, y + 8.8, "020039981400303804BRADESCO ADMIN", 7)
    y += 19.3
    linha(y, "", "GASTOS CARTAO DE CREDITO", "3990215", "-11,42", "1.600,00")
    y += 10.3
    t(41, y, "Total", 7)
    t(388, y, "5.001,12", 7, alinhar="direita")
    t(475, y, "-4.401,12", 7, alinhar="direita")
    t(563, y, "1.600,00", 7, alinhar="direita")
    t(40, y + 40, "Saldos Invest Fácil / Plus", 9)
    t(48, y + 60, "Data", 8)
    t(108, y + 60, "Histórico", 8)
    t(525, y + 60, "Valor (R$)", 8)
    t(45, y + 75, "03/08/2026", 7)
    t(105, y + 75, "SALDO INVEST FÁCIL", 7)
    t(567, y + 75, "1.001,12", 7, alinhar="direita")
    return doc.gerar()


def test_extrato_bradesco_organizado(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_pdf_extrato_bradesco()), "extrato.pdf")},
                    content_type="multipart/form-data")
    wb = load_workbook(BytesIO(r.data))
    assert wb.sheetnames == ["Resumo", "Extrato", "Invest Fácil"]
    ext = wb["Extrato"]
    assert ext["A1"].value == "EMPRESA TESTE LTDA — Bradesco ag. 1111 c/c 0001234-5"
    assert [c.value for c in ext[4]] == ["Data", "Histórico (banco)", "Dcto.", "Favorecido / Complemento", "Tipo",
                                        "Entrada (R$)", "Saída (R$)", "Saldo (R$)", "Saldo banco (R$)", "Confere"]
    linhas = [tuple(c.value for c in ext[r][1:9]) for r in range(6, 10)]
    assert linhas == [
        ("RENTAB.INVEST FACILCRED*", "677471", None, "Rendimento Invest Fácil", 1.12, None, "=H5+F6-G6", 1001.12),
        ("PIX RECEBIDO", "936154", "CLIENTE BOM LTDA", "Recebimento PIX/TED", 5000, None, "=H6+F7-G7", 6001.12),
        ("PAGTO ELETRON COBRANCA", "1252", "BRADESCO ADMIN", "Boletos/contas pagas", None, 4389.7, "=H7+F8-G8", 1611.42),
        ("GASTOS CARTAO DE CREDITO", "3990215", None, "Cartão de crédito", None, 11.42, "=H8+F9-G9", 1600),
    ]
    assert ext["J9"].value == '=IF(ROUND(H9-I9,2)=0,"OK","DIVERGE")'
    res = wb["Resumo"]
    assert [res.cell(i, 3).value for i in range(4, 8)] == [1000, 5001.12, 4401.12, 1600]
    assert res["B5"].value == "=Extrato!F10" and "Extrato!$E$6:$E$9" in res["B13"].value
    assert [c.value for c in wb["Invest Fácil"][5]][1:] == ["SALDO INVEST FÁCIL", 1001.12]


def _pdf_extrato_santander():
    """Extrato do app Santander Empresas (do mais novo para o mais antigo), dados fictícios."""
    doc = Documento("Extrato")
    t = doc.texto
    t(358, 45, "Aplicativo Santander Empresas", 9)
    t(34, 94, "EMPRESA SANTA LTDA", 9)
    t(367, 94, "Agência: 0086", 9)
    t(484, 94, "Conta: 13000001", 9)
    t(31, 138, "Períodos: 01/08/2026 a 31/08/2026", 9)
    for x, texto in ((49, "Data"), (95, "Histórico"), (306, "Documento"), (423, "Valor (R$)"), (518, "Saldo (R$)")):
        t(x, 168, texto, 9)

    def lanc(y, data, hist, doc_, valor, saldo, acima=None, abaixo=None):
        if acima:
            t(92, y - 6.9, acima, 8)
        t(33, y, data, 8)
        t(92, y, hist, 8)
        t(306, y, doc_, 8)
        t(466, y, valor, 8, alinhar="direita")
        t(564, y, saldo, 8, alinhar="direita")
        if abaixo:
            t(92, y + 6.9, abaixo, 8)

    # mais novo primeiro; saldo anterior = 1.000,00
    lanc(190, "02/08/2026", "Pix Recebido 12345678000190", "", "500,00", "-1.270,00")
    lanc(215, "02/08/2026", "", "0000531587", "3.000,00", "-1.770,00", acima="Pagamento Cartao De Credito",
         abaixo="STONE-MASTER")
    lanc(240, "01/08/2026", "Tarifa Avulsa Envio Pix", "", "-20,00", "-4.770,00")
    lanc(265, "01/08/2026", "", "14354062", "-5.750,00", "-4.750,00", acima="Pix Enviado JOAO DA SILVA",
         abaixo="SAURO")
    t(31, 300, "Saldo Disponível -1.270,00", 9)
    return doc.gerar()


def test_extrato_santander_organizado(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_pdf_extrato_santander()), "extrato.pdf")},
                    content_type="multipart/form-data")
    wb = load_workbook(BytesIO(r.data))
    ext = wb["Extrato"]
    assert ext["A1"].value == "EMPRESA SANTA LTDA — Santander ag. 0086 c/c 13000001"
    assert ext["H5"].value == 1000  # saldo anterior calculado a partir do lançamento mais antigo
    linhas = [tuple(c.value for c in ext[r][1:9]) for r in range(6, 10)]
    assert linhas == [  # em ordem cronológica
        ("Pix Enviado", "14354062", "JOAO DA SILVA SAURO", "PIX enviado", None, 5750, "=H5+F6-G6", -4750),
        ("Tarifa Avulsa Envio Pix", None, None, "Tarifas bancárias", None, 20, "=H6+F7-G7", -4770),
        ("Pagamento Cartao De Credito", "0000531587", "STONE-MASTER", "Recebíveis de cartão", 3000, None,
         "=H7+F8-G8", -1770),
        ("Pix Recebido", None, "12345678000190", "Recebimento PIX/TED", 500, None, "=H8+F9-G9", -1270),
    ]
    res = wb["Resumo"]
    assert [res.cell(i, 3).value for i in range(4, 8)] == [1000, None, None, -1270]


def _xlsx_extrato_stone():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Movimentação", "Tipo", "Valor", "Saldo antes", "Saldo depois", "Tarifa", "Data", "Nosso Número",
               "Situação", "Destino", "Destino Documento", "Destino Instituição", "Destino Agência", "Destino Conta",
               "Origem", "Origem Documento", "Origem Instituição", "Origem Agência", "Origem Conta"])
    dono = ["Loja Teste", "11.222.333/0001-81", "Stone Instituição de Pagamento S.A.", "0001", "123-4"]
    desc = ["Desconhecido"] * 5
    # do mais novo para o mais antigo; dois lançamentos no mesmo minuto
    ws.append(["Débito", "Pix", "-100,00", "R$ 1.151,61", "R$ 1.051,61", "Grátis", "02/09/2026 10:00", None,
               "Enviado", "FORNECEDOR X", "99.888.777/0001-66", "Banco Y", "Desconhecido", "Desconhecido"] + dono)
    ws.append(["Crédito", "Pagamento", "150,00", "R$ 1.003,61", "R$ 1.151,61", "R$ 2,00", "01/09/2026 09:30",
               "34190000000000000001", "Recebido"] + dono + desc)
    ws.append(["Crédito", "Transação", "4,00", "R$ 1.000,00", "R$ 1.003,61", "R$ 0,39", "01/09/2026 09:30", None,
               "FINISHED"] + dono + ["MARIA CLIENTE", "***.111.222-**", "Banco Z", "Desconhecido", "Desconhecido"])
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue()


def test_extrato_stone_em_planilha(client):
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(_xlsx_extrato_stone()), "STONE.xls")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and "STONE.xlsx" in r.headers["Content-Disposition"]
    wb = load_workbook(BytesIO(r.data))
    ext = wb["Extrato"]
    assert ext["A1"].value == "Loja Teste — Stone ag. 0001 c/c 123-4"
    linhas = [tuple(c.value for c in ext[r][1:10]) for r in range(6, 11)]
    # a tarifa vira uma linha própria logo abaixo, e o saldo do banco fica nela
    assert [(l[0], l[3], l[4], l[5], l[7]) for l in linhas] == [
        ("Transação (crédito) 09:30", "Transações recebidas", 4, None, None),
        ("Tarifa Stone (Transação)", "Tarifas bancárias", None, 0.39, 1003.61),
        ("Pagamento (crédito) 09:30", "Boletos recebidos", 150, None, None),
        ("Tarifa Stone (Pagamento)", "Tarifas bancárias", None, 2, 1151.61),
        ("Pix enviado 10:00", "PIX enviado", None, 100, 1051.61),
    ]
    assert linhas[2][1] == "34190000000000000001" and linhas[0][2] == "MARIA CLIENTE · ***.111.222-**"
    assert [wb["Resumo"].cell(i, 3).value for i in range(4, 8)] == [1000, None, None, 1051.61]


def test_planilha_nao_reconhecida(client):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["qualquer", "coisa"])
    arq = BytesIO()
    wb.save(arq)
    r = client.post("/ferramentas/pdf-excel", data={"arquivo": (BytesIO(arq.getvalue()), "x.xlsx")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Planilha não reconhecida" in r.get_data(as_text=True)

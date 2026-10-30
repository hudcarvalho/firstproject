"""Extrato "Mensal / Por Período" do Bradesco (Net Empresa) em planilha organizada.

Cada lançamento pode ocupar até três linhas no PDF: o nome do lançamento logo acima, a linha
com data, documento, valor e saldo, e o complemento (remetente, destinatário…) logo abaixo.
O banco imprime o saldo depois de cada lançamento, então a conferência é feita linha a linha.
Também lê os "Últimos Lançamentos" (posteriores ao período) e os saldos do Invest Fácil.
"""
import re
from datetime import datetime

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_CABECALHO_PAGINA = re.compile(
    r"^(Extrato Mensal / Por Período|Nome do usuário:|Data da operação:|Folha \d+/\d+|Os dados acima)")
DISTANCIA_REGISTRO = 6.5  # nome e complemento ficam a ~4,4 pt da linha do valor; registros, a ~10 pt


def e_extrato_bradesco(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Extrato Mensal / Por Período" in texto and bool(re.search(r"Extrato de: Ag: \d+ \| CC: ", texto))


def _linhas(pdf):
    """Todas as linhas do PDF em ordem: (página, top, [palavras])."""
    resultado = []
    for n, page in enumerate(pdf.pages):
        linhas = []
        for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=1), key=lambda w: (w["top"], w["x0"])):
            if linhas and abs(linhas[-1][1] - w["top"]) <= 1.5:
                linhas[-1][2].append(w)
            else:
                linhas.append([n, w["top"], [w]])
        resultado.extend((n, top, sorted(ws, key=lambda w: w["x0"])) for n, top, ws in linhas)
    return resultado


def _favorecido(complementos):
    partes = []
    for c in complementos:
        c = re.sub(r"^(REM|DES|DEST)[:.]\s*", "", c.strip(), flags=re.I)
        c = re.sub(r"\s+\d{2}/\d{2}$", "", c)
        c = re.sub(r"^\d{10,}(?=[A-Za-z])", "", c)  # código colado ao nome: "0200...804BRADESCO ADMIN"
        if c:
            partes.append(c)
    return " · ".join(partes)


def _tipo(hist, credito):
    h = sem_acento(hist)
    if h.startswith("RENTAB.INVEST") or h.startswith("RENTAB INVEST"):
        return "Rendimento Invest Fácil"
    if "CONSORCIO" in h:
        return "Consórcio"
    if h.startswith("PIX RECEBIDO"):
        return "Recebimento PIX/TED"
    if h.startswith("PIX ENVIADO"):
        return "PIX enviado"
    if "TRIBUTO" in h or h.startswith("DARF") or h.startswith("GPS") or "IMPOSTO" in h:
        return "Tributos/guias"
    if h.startswith("TARIFA") or h.startswith("DOC/TED INTERNET") or h.startswith("TAR "):
        return "Tarifas bancárias"
    if "CARTAO DE CREDITO" in h:
        return "Cartão de crédito"
    if h.startswith("DEBITO AUTOMATICO") or h.startswith("DEB AUTOMATICO") or h.startswith("DEB.AUTOM"):
        return "Débito automático"
    if h.startswith("PAGTO ELETRON COBRANCA") or h.startswith("PAGTO COBRANCA") or h.startswith("PAGTO TITULO") \
            or "BOLETO" in h:
        return "Boletos/contas pagas"
    if h.startswith("TRANSF"):
        return "Transferência recebida" if credito else "Transferência entre contas"
    if h.startswith("TED") or h.startswith("DOC"):
        return "Recebimento PIX/TED" if credito else "TED/DOC enviado"
    if h.startswith("DEPOSITO") or h.startswith("DEP "):
        return "Depósitos"
    if h.startswith("IOF") or h.startswith("JUROS") or "ENCARGOS" in h:
        return "Juros/IOF"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Bradesco", origem_resumo="na linha Total do extrato",
                 rotulo_favorecido="Favorecido / Complemento", rotulo_saldo_banco="Saldo banco (R$)")
    texto1 = pdf.pages[0].extract_text() or ""
    m = re.search(r"^(.+?) \| CNPJ: ([\d./-]+)", texto1, flags=re.M)
    if m:
        ex.empresa = m[1].strip()
    m = re.search(r"Extrato de: Ag: (\d+) \| CC: ([\d-]+) \| Entre (\d{2}/\d{2}/\d{4}) e (\d{2}/\d{2}/\d{4})", texto1)
    if m:
        ex.agencia, ex.conta = m[1], m[2]
        ex.inicio = datetime.strptime(m[3], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[4], "%d/%m/%Y").date()

    # separa as linhas por seção
    secoes = {"movimento": [], "ultimos": [], "invest": []}
    secao = None
    vistos_cabecalho = 0
    for pagina, top, ws in _linhas(pdf):
        texto = " ".join(w["text"] for w in ws)
        if _CABECALHO_PAGINA.match(texto) or re.match(r"^.+ \| CNPJ: ", texto):
            continue
        if texto.startswith("Data Lançamento Dcto."):
            vistos_cabecalho += 1
            secao = "movimento" if vistos_cabecalho == 1 else "ultimos"
            continue
        if texto.startswith("Últimos Lançamentos"):
            secao = None
            continue
        if texto.startswith("Saldos Invest"):
            secao = "invest"
            continue
        if secao == "invest" and texto.startswith("Data Histórico"):
            continue
        if secao:
            secoes[secao].append((pagina, top, ws, texto))

    # saldos do Invest Fácil
    for _, _, ws, texto in secoes["invest"]:
        textos = [w["text"] for w in ws]
        if len(textos) >= 3 and _DATA.match(textos[0]) and _VALOR.match(textos[-1]):
            ex.saldos_invest.append((datetime.strptime(textos[0], "%d/%m/%Y").date(),
                                     " ".join(textos[1:-1]), valor(textos[-1])))

    ex.movimentos, ex.data_saldo_anterior, ex.saldo_anterior, totais = _movimentos(secoes["movimento"])
    if totais:
        ex.total_entradas, saidas, ex.saldo_final = totais
        ex.total_saidas = abs(saidas)
    ex.ultimos, ex.ultimos_data_anterior, ex.ultimos_saldo_anterior, _ = _movimentos(secoes["ultimos"])
    if ex.saldos_invest:
        ex.nota_saldo = "saldo da conta corrente; os saldos do Invest Fácil estão na aba própria"
    return ex


def _movimentos(linhas):
    """Lançamentos de uma seção. Devolve (movimentos, data do saldo anterior, saldo anterior, totais)."""
    itens = []
    totais = None
    for pagina, top, ws, texto in linhas:
        textos = [w["text"] for w in ws]
        if textos[0] == "Total":
            vals = [valor(t) for t in textos[1:] if _VALOR.match(t)]
            if len(vals) >= 3:
                totais = (vals[0], vals[1], vals[2])
            break
        data = textos[0] if _DATA.match(textos[0]) else None
        corpo = textos[1:] if data else textos
        valores = [t for t in corpo if _VALOR.match(t)]
        resto = [t for t in corpo if not _VALOR.match(t)]
        documento = ""
        if valores and resto and resto[-1].isdigit():
            documento = resto.pop()
        itens.append({"pagina": pagina, "top": top, "data": data, "valores": [valor(v) for v in valores],
                      "texto": " ".join(resto), "documento": documento, "titulo": [], "complemento": []})

    registros = [i for i in itens if i["valores"]]
    for k, item in enumerate(itens):
        if item["valores"] or not item["texto"]:
            continue
        anterior = next((itens[j] for j in range(k - 1, -1, -1) if itens[j]["valores"]), None)
        proximo = next((itens[j] for j in range(k + 1, len(itens)) if itens[j]["valores"]), None)

        def perto(a, b):
            return a is not None and a["pagina"] == b["pagina"] and abs(a["top"] - b["top"]) <= DISTANCIA_REGISTRO
        if perto(proximo, item) and not proximo["texto"]:
            proximo["titulo"].append(item["texto"])
        elif perto(anterior, item):
            anterior["complemento"].append(item["texto"])
        elif proximo is not None and not proximo["texto"] and not proximo["titulo"]:
            proximo["titulo"].append(item["texto"])
        elif anterior is not None:
            anterior["complemento"].append(item["texto"])

    movimentos, saldo_anterior, data_anterior = [], None, None
    dia = None
    for r in registros:
        if r["data"]:
            dia = datetime.strptime(r["data"], "%d/%m/%Y").date()
        historico = " ".join(r["titulo"] + ([r["texto"]] if r["texto"] else [])).strip()
        if sem_acento(historico).startswith("SALDO ANTERIOR"):
            saldo_anterior, data_anterior = r["valores"][-1], dia
            continue
        if len(r["valores"]) < 2:
            continue
        lancamento, saldo = r["valores"][0], r["valores"][-1]
        credito = lancamento >= 0
        mov = Movimento(dia, historico, lancamento if credito else None, None if credito else -lancamento,
                        saldo_banco=saldo, documento=r["documento"])
        mov.favorecido = _favorecido(r["complemento"])
        mov.tipo = _tipo(historico, credito)
        movimentos.append(mov)
    return movimentos, data_anterior, saldo_anterior, totais

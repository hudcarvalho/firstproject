"""Extrato mensal do Itaú (conta corrente + aplicação automática) em planilha organizada.

Gera as abas:
- Resumo: saldos, entradas e saídas calculados x impressos pelo banco (diferença) e a
  movimentação por tipo (SOMASES / CONT.SE);
- Extrato: data, histórico, favorecido/remetente, tipo, entrada, saída, saldo por fórmula e,
  no fim de cada dia, o saldo do banco (conta corrente + aplicação automática) com "Confere";
- Investimentos CDB: carteira de CDB e renda fixa com rendimento e IR/IOF estimado.

As linhas internas da aplicação automática (Res/Apl Aplic Aut, SALDO APLIC AUT) não entram como
movimento: servem só para conferir o saldo do fim do dia.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from .extrato_planilha import Extrato, Movimento, planilha, sem_acento, valor  # noqa: F401

MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
         "set": 9, "out": 10, "nov": 11, "dez": 12}
_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}-?$")
_DIA = re.compile(r"^(\d{2})/(\d{2})$")
_CDB = re.compile(r"^(?P<produto>.+?)\s+(?P<ap>\d{2}/\d{2}/\d{2})\s+(?P<venc>\d{2}/\d{2}/\d{2})\s+"
                  r"(?P<valor>[\d.]+,\d{2})\s+(?P<taxa>[\d.]+,\d{2})%\s*DI\s+(?P<bruto>[\d.]+,\d{2})\s+"
                  r"(?P<liquido>[\d.]+,\d{2})$")
_sem_acento = sem_acento
_valor = valor


def e_extrato_itau(pdf):
    """O PDF (pdfplumber aberto) é um extrato mensal do Itaú?"""
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return bool(re.search(r"extrato mensal ag \d+ cc [\d-]+", texto)) and "Movimenta" in texto


# ---------------------------------------------------------------- leitura

def _linhas(page, x_min=0):
    """Palavras agrupadas em linhas (tolerância vertical de 3 pt), da esquerda para a direita."""
    linhas = []
    for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=2), key=lambda w: (w["top"], w["x0"])):
        if w["x0"] < x_min:
            continue
        if linhas and abs(linhas[-1][0] - w["top"]) <= 3:
            linhas[-1][1].append(w)
        else:
            linhas.append([w["top"], [w]])
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in linhas]


def _cabecalho_mov(page):
    """Posições das colunas da movimentação na página (ou None se a página não tem a tabela)."""
    for ws in _linhas(page):
        # "entradas R$" às vezes vem colado ("entradasR$")
        textos = [w["text"][:-2] if w["text"].endswith("R$") and len(w["text"]) > 2 else w["text"] for w in ws]
        if "data" in textos and "descrição" in textos and "saldo" in textos and "entradas" in textos:
            def fim(rotulo):
                i = textos.index(rotulo)
                return ws[i + 1]["x1"] if i + 1 < len(ws) and ws[i + 1]["text"] == "R$" else ws[i]["x1"]
            return {"top": ws[0]["top"], "data": ws[textos.index("data")]["x0"],
                    "desc": ws[textos.index("descrição")]["x0"],
                    "entradas": fim("entradas"), "saidas": fim("saídas"), "saldo": fim("saldo")}
    return None


def _favorecido(hist):
    for prefixo in ("Sispag ", "BOLETO PAGO ", "PIX TRANSF ", "PIX ENVIADO ", "PIX RECEBIDO ", "TED ",
                    "DOC ", "DA ", "TBI ", "INT TRANSF ", "TRANSF "):
        if hist.upper().startswith(prefixo.upper()):
            resto = hist[len(prefixo):].strip()
            return re.sub(r"\s*\d{2}/\d{2}$", "", resto).strip()
    return ""


def _tipo(hist, entrada, debitos_automaticos):
    h = _sem_acento(hist)
    credito = entrada is not None
    if h.startswith("APLICACAO CDB") or h.startswith("APLIC CDB"):
        return "Aplicação em CDB"
    if h.startswith("RESGATE CDB") or h.startswith("RESG CDB"):
        return "Resgate de CDB"
    if h.startswith("REND PAGO APLIC"):
        return "Rendimento aplicação automática"
    if h.startswith("MOV TIT COB") or "COBRANCA" in h:
        return "Cobrança (títulos liquidados)"
    if h.startswith("DA ") or h in debitos_automaticos or h.startswith("SISDEB"):
        return "Débito automático"
    if h.startswith("SISPAG TRIB") or h.startswith("DARF") or h.startswith("GPS") or "TRIBUTO" in h:
        return "Tributos/guias"
    if h.startswith("SISPAG TRANSF CC ITAU") or h.startswith("TRANSF CC ITAU"):
        return "Transferência CC Itaú"
    if h.startswith("SISPAG CONCESSIONARIA") or h.startswith("BOLETO PAGO") or h.startswith("PAG BOLETO") \
            or h.startswith("PAGTO") or h.startswith("CONCESSIONARIA"):
        return "Boletos/contas pagas"
    if h.startswith("PIX ENVIADO"):
        return "PIX enviado"
    if h.startswith("PIX") or h.startswith("TED") or h.startswith("DOC") or h.startswith("TBI"):
        return "Recebimento PIX/TED" if credito else "TED/DOC enviado"
    if h.startswith("SISPAG"):
        return "Recebimento Sispag" if credito else "Pagamento Sispag"
    if h.startswith("DEP") or "DEPOSITO" in h:
        return "Depósitos"
    if h.startswith("TAR") or "TARIFA" in h:
        return "Tarifas bancárias"
    if h.startswith("IOF") or h.startswith("JUROS"):
        return "Juros/IOF"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    """Lê o extrato (pdfplumber aberto) e devolve um Extrato."""
    ex = Extrato(banco="Itaú", origem_resumo="na 1ª página do extrato")
    pagina1 = pdf.pages[0].extract_text() or ""
    m = re.search(r"extrato mensal ag (\d+) cc ([\d-]+) (\w{3}) (\d{4})", pagina1)
    if m:
        ex.agencia, ex.conta = m[1], m[2]
        mes, ano = MESES.get(m[3].lower(), 1), int(m[4])
        ex.inicio = date(ano, mes, 1)
    linhas1 = pagina1.splitlines()
    endereco = re.compile(r"^(AV|AVENIDA|R|RUA|AL|ALAMEDA|ROD|RODOVIA|ESTR|PCA|PRACA|TV|TRAVESSA|EST)\.?\s")
    for i, l in enumerate(linhas1[:15]):
        if i and endereco.match(l.strip().upper()):
            ex.empresa = linhas1[i - 1].strip()
            break
    m = re.search(r"saldo em (\d{2}/\d{2}/\d{2}) saldo em (\d{2}/\d{2}/\d{2})", pagina1)
    if m:
        ex.fim = datetime.strptime(m[2], "%d/%m/%y").date()
    m = re.search(r"R\$ (-?[\d.]+,\d{2}-?) R\$ (-?[\d.]+,\d{2}-?)\s*\n?\s*entradas", pagina1) or \
        re.search(r"Automáticas\s*\n\s*R\$ (-?[\d.]+,\d{2}-?) R\$ (-?[\d.]+,\d{2}-?)", pagina1)
    if m:
        ex.saldo_anterior, ex.saldo_final = _valor(m[1]), _valor(m[2])
    totais = re.findall(r"^total (-?[\d.]+,\d{2})$", pagina1, flags=re.M)
    if len(totais) >= 2:
        ex.total_entradas, ex.total_saidas = _valor(totais[0]), _valor(totais[1])

    # débitos automáticos efetuados (para classificar, ex.: "Business 4004-1849")
    debitos_automaticos = set()
    for page in pdf.pages:
        texto = page.extract_text() or ""
        if "Débitos automáticos efetuados" in texto:
            trecho = texto.split("Débitos automáticos efetuados", 1)[1].split("Débitos automáticos não efetuados")[0]
            for _, hist in re.findall(r"(\d{2}/\d{2}/\d{2}) (.+?) [\d.]+,\d{2}", trecho):
                debitos_automaticos.add(_sem_acento(hist.strip()))

    # movimentação
    dia = None
    saldo_aplic = None
    saldo_cc = Decimal("0")
    viu_saldo_no_dia = False
    fim = False
    movimentos_do_dia = []

    def fechar_dia():
        if dia is not None and viu_saldo_no_dia and movimentos_do_dia:
            movimentos_do_dia[-1].saldo_banco = (saldo_aplic or Decimal("0")) + saldo_cc \
                if ex.tem_aplicacao_automatica else saldo_cc

    for page in pdf.pages:
        if fim:
            break
        cab = _cabecalho_mov(page)
        if not cab:
            continue
        for ws in _linhas(page, x_min=cab["data"] - 3):
            if ws[0]["top"] <= cab["top"] + 2:
                continue
            textos = [w["text"] for w in ws]
            if textos[0] == "(créditos)":
                continue
            data_txt = None
            if _DIA.match(textos[0]) and ws[0]["x0"] < cab["desc"] - 5:
                data_txt = textos[0]
                ws, textos = ws[1:], textos[1:]
            valores, desc = [], []
            for w in ws:
                if _VALOR.match(w["text"]) and w["x0"] > cab["desc"] + 100:
                    col = min(("entradas", "saidas", "saldo"), key=lambda c: abs(cab[c] - w["x1"]))
                    valores.append((col, _valor(w["text"])))
                else:
                    desc.append(w["text"])
            historico = " ".join(desc).strip()
            if data_txt:
                novo = date(ex.inicio.year if ex.inicio else date.today().year,
                            int(data_txt[3:5]), int(data_txt[:2]))
                if dia is not None and novo != dia:
                    fechar_dia()
                    movimentos_do_dia = []
                    viu_saldo_no_dia = False
                dia = novo
            if not historico and not valores:
                continue
            h = _sem_acento(historico)
            saldo_col = next((v for c, v in valores if c == "saldo"), None)
            if h.startswith("SALDO ANTERIOR"):
                if ex.saldo_anterior is None and saldo_col is not None:
                    ex.saldo_anterior = saldo_col
                if ex.inicio is None and dia:
                    ex.inicio = dia
                saldo_anterior_data = dia
                continue
            if h.startswith("SALDO FINAL"):
                if saldo_col is not None and ex.saldo_final is None:
                    ex.saldo_final = saldo_col
                fim = True
                break
            if h.startswith("SALDO APLIC AUT") or h.startswith("SDO APLIC AUT"):
                ex.tem_aplicacao_automatica = True
                v = saldo_col if saldo_col is not None else next((v for _, v in valores), None)
                if v is not None:
                    saldo_aplic = v
                    viu_saldo_no_dia = True
                continue
            if h.startswith("SALDO EM C/C") or h.startswith("SALDO DO DIA") or h.startswith("SDO CTA"):
                if saldo_col is not None:
                    saldo_cc = saldo_col
                    viu_saldo_no_dia = True
                continue
            if saldo_col is not None:
                saldo_cc = saldo_col
                viu_saldo_no_dia = True
            if h.startswith("RES APLIC AUT") or h.startswith("APL APLIC AUT"):
                ex.tem_aplicacao_automatica = True
                continue
            entrada = next((v for c, v in valores if c == "entradas"), None)
            saida = next((v for c, v in valores if c == "saidas"), None)
            if entrada is None and saida is None:
                continue
            if saida is not None:
                saida = abs(saida)
            mov = Movimento(dia, historico, entrada, saida)
            mov.favorecido = _favorecido(historico)
            mov.tipo = _tipo(historico, entrada, debitos_automaticos)
            ex.movimentos.append(mov)
            movimentos_do_dia.append(mov)
    fechar_dia()
    if ex.inicio and ex.saldo_anterior is not None:
        ex.inicio = ex.inicio.replace(day=1)
    if ex.tem_aplicacao_automatica:
        ex.nota_saldo = "saldo = conta corrente + aplicação automática Aplic Aut Mais"

    # carteira de CDB / renda fixa
    for page in pdf.pages:
        texto = page.extract_text() or ""
        if "CDB e Renda Fixa" not in texto:
            continue
        for linha in texto.splitlines():
            m = _CDB.match(linha.strip())
            if m:
                ex.cdbs.append({
                    "produto": m["produto"], "aplicacao": datetime.strptime(m["ap"], "%d/%m/%y").date(),
                    "vencimento": datetime.strptime(m["venc"], "%d/%m/%y").date(),
                    "valor": _valor(m["valor"]), "taxa": _valor(m["taxa"]) / 100,
                    "bruto": _valor(m["bruto"]), "liquido": _valor(m["liquido"])})
        m = re.search(r"total aplicações financeiras ([\d.]+,\d{2}) ([\d.]+,\d{2}) ([\d.]+,\d{2})", texto)
        if m:
            ex.total_cdb = tuple(_valor(x) for x in m.groups())
    return ex

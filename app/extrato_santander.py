"""Extrato do Santander (Aplicativo Santander Empresas) em planilha organizada.

O extrato vem do mais novo para o mais antigo e o histórico pode quebrar em linhas acima e
abaixo da linha com data, documento, valor e saldo. O banco imprime o saldo após cada
lançamento; o saldo anterior do período é calculado a partir do lançamento mais antigo.
"""
import re
from datetime import datetime, timedelta

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
DISTANCIA_LINHA = 9  # partes do histórico ficam a ~7 pt da linha do valor; lançamentos, a ~25 pt

# Rótulos do banco (o que vier depois é o favorecido/remetente/complemento)
ROTULOS = [
    "Pagamento De Boleto Outros Bancos", "Pagamento De Boleto Santander", "Pagamento De Boleto",
    "Pagamento Conta Luz Em Canais", "Pagamento Conta Agua Em Canais", "Pagamento Conta Gas Em Canais",
    "Pagamento Conta Telefone Em Canais", "Pagamento Cartao De Credito", "Pagamento Cartao De Debito",
    "Pagamento De Tributos", "Pagamento De Tributo", "Pagamento De Titulo", "Pagamento A Fornecedores",
    "Pagamento Cartao Credito Bce", "Pgto Conta De Telefone Em Canais", "Pgto Conta De Luz Em Canais",
    "Pgto Conta De Agua Em Canais", "Pgto Conta De Gas Em Canais", "Iof Imposto Operacoes Financeiras",
    "Iof Adicional - Automatico", "Tarifa Mensalidade Pacote Servicos", "Tarifa Avulsa Envio Pix",
    "Juros Saldo Utiliz Ate Limite", "Iof Saldo Utiliz Ate Limite", "Mensalidade De Seguro", "Pix Recebido",
    "Pix Enviado", "Ted Recebida", "Ted Enviada", "Transferencia Recebida", "Transferencia Enviada",
    "Resgate Contamax", "Aplicacao Contamax", "Deposito",
]


def e_extrato_santander(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Santander" in texto and "Períodos:" in texto and "Data Histórico Documento Valor (R$) Saldo (R$)" in texto


def _separar(texto):
    """'Pix Enviado FULANO DE TAL' -> ('Pix Enviado', 'FULANO DE TAL')."""
    t = sem_acento(texto)
    for rotulo in sorted(ROTULOS, key=len, reverse=True):
        if t.startswith(sem_acento(rotulo)):
            n = len(rotulo)
            return texto[:n].strip(), texto[n:].strip()
    return texto.strip(), ""


def _tipo(hist, credito):
    h = sem_acento(hist)
    if h.startswith("PIX RECEBIDO") or h.startswith("TED RECEBIDA") or h.startswith("TRANSFERENCIA RECEBIDA"):
        return "Recebimento PIX/TED"
    if h.startswith("PIX ENVIADO"):
        return "PIX enviado"
    if h.startswith("TED ENVIADA") or h.startswith("TRANSFERENCIA ENVIADA"):
        return "TED/DOC enviado"
    if h.startswith("PAGAMENTO CARTAO"):
        return "Recebíveis de cartão" if credito else "Cartão de crédito"
    if "TRIBUTO" in h or h.startswith("DARF") or h.startswith("GPS"):
        return "Tributos/guias"
    if credito and (h.startswith("PAGAMENTO") or h.startswith("PGTO")):
        return "Repasses recebidos"  # ex.: "Pagamento A Fornecedores IFOOD.COM" creditado na conta
    if h.startswith("PAGAMENTO") or h.startswith("PGTO") or "BOLETO" in h:
        return "Boletos/contas pagas"
    if h.startswith("TARIFA"):
        return "Tarifas bancárias"
    if h.startswith("JUROS") or h.startswith("IOF"):
        return "Juros/IOF"
    if "SEGURO" in h:
        return "Seguros"
    if h.startswith("RESGATE"):
        return "Resgate de aplicação"
    if h.startswith("APLICACAO"):
        return "Aplicação financeira"
    if h.startswith("DEPOSITO"):
        return "Depósitos"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Santander", origem_resumo="no extrato (saldo após o lançamento mais antigo e mais novo)",
                 rotulo_saldo_banco="Saldo banco (R$)")
    texto1 = pdf.pages[0].extract_text() or ""
    m = re.search(r"^(.+?)\s+Agência:\s*(\d+)\s+Conta:\s*(\d+)", texto1, flags=re.M)
    if m:
        ex.empresa, ex.agencia, ex.conta = m[1].strip(), m[2], m[3]
    m = re.search(r"Períodos:\s*(\d{2}/\d{2}/\d{4}) a (\d{2}/\d{2}/\d{4})", texto1)
    if m:
        ex.inicio = datetime.strptime(m[1], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2], "%d/%m/%Y").date()

    # colunas, pelo cabeçalho da primeira página
    col = None
    for w in pdf.pages[0].extract_words(x_tolerance=1.5, y_tolerance=1):
        if w["text"] == "Documento":
            col = {"doc": w["x0"] - 8, "valor": w["x1"] + 30, "top": w["top"]}
    if col is None:
        return ex

    registros = []
    fim = False
    for n, page in enumerate(pdf.pages):
        if fim:
            break
        linhas = []
        for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=1), key=lambda w: (w["top"], w["x0"])):
            if n == 0 and w["top"] <= col["top"] + 2:
                continue
            if linhas and abs(linhas[-1][0] - w["top"]) <= 1.5:
                linhas[-1][1].append(w)
            else:
                linhas.append([w["top"], [w]])
        itens = []
        for top, ws in linhas:
            ws.sort(key=lambda w: w["x0"])
            texto = " ".join(w["text"] for w in ws)
            if texto.startswith("Saldo de ContaMax") or texto.startswith("Saldo Disponível"):
                fim = True
                break
            if re.fullmatch(r"\d+/\d+", texto):  # número da página
                continue
            data = ws[0]["text"] if _DATA.match(ws[0]["text"]) and ws[0]["x0"] < 90 else None
            corpo = ws[1:] if data else ws
            valores = [w for w in corpo if _VALOR.match(w["text"]) and w["x0"] > col["doc"] + 40]
            hist = [w["text"] for w in corpo if w not in valores and w["x0"] < col["doc"]]
            doc = [w["text"] for w in corpo if w not in valores and w["x0"] >= col["doc"]]
            itens.append({"top": top, "data": data, "valores": [valor(w["text"]) for w in valores],
                          "hist": " ".join(hist), "doc": " ".join(doc), "acima": [], "abaixo": []})
        principais = [i for i in itens if i["data"] and len(i["valores"]) >= 2]
        for i in itens:
            if i in principais or not i["hist"]:
                continue
            perto = min(principais, key=lambda p: abs(p["top"] - i["top"]), default=None)
            if perto and abs(perto["top"] - i["top"]) <= DISTANCIA_LINHA:
                (perto["acima"] if i["top"] < perto["top"] else perto["abaixo"]).append(i["hist"])
        registros.extend(principais)

    movimentos = []
    for r in reversed(registros):  # o extrato vem do mais novo para o mais antigo
        completo = " ".join(r["acima"] + ([r["hist"]] if r["hist"] else []) + r["abaixo"]).strip()
        hist, fav = _separar(completo)
        lanc, saldo = r["valores"][-2], r["valores"][-1]
        credito = lanc >= 0
        mov = Movimento(datetime.strptime(r["data"], "%d/%m/%Y").date(), hist,
                        lanc if credito else None, None if credito else -lanc, saldo_banco=saldo,
                        favorecido=fav, documento=r["doc"])
        mov.tipo = _tipo(hist, credito)
        movimentos.append(mov)
    ex.movimentos = movimentos
    if movimentos:
        primeiro = movimentos[0]
        ex.saldo_anterior = primeiro.saldo_banco - (primeiro.entrada or 0) + (primeiro.saida or 0)
        ex.saldo_final = movimentos[-1].saldo_banco
        ex.data_saldo_anterior = (ex.inicio or primeiro.data) - timedelta(days=1)
    return ex

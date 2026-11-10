"""Itaú Empresas — "Lançamentos do período" (extrato de entradas e saídas) em planilha organizada.

Layout: Data | Lançamentos | Razão Social | CNPJ/CPF | Valor (R$) | Saldo (R$), do mais novo para o
mais antigo. O texto de "Lançamentos" e de "Razão Social" pode quebrar em linhas logo acima e logo
abaixo da linha com a data. O saldo aparece só na linha "SALDO TOTAL DISPONÍVEL DIA" (no topo de
cada dia) e em "SALDO ANTERIOR" (no fim do extrato).
"""
import re
from datetime import datetime

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_DOC = re.compile(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{3}\.\d{3}\.\d{3}-\d{2})$")
# partes quebradas ficam a ~5 pt (2 linhas) ou ~10,6 pt (3 linhas) da linha da data; cada parte vai
# para a linha com data mais próxima
DISTANCIA_LINHA = 11.5


def e_extrato_itau_periodo(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Lançamentos do período:" in texto and "Data Lançamentos Razão Social CNPJ/CPF Valor (R$) Saldo (R$)" in texto


def _tipo(hist, credito, razao=""):
    h = sem_acento(hist)
    r = sem_acento(razao)
    if h.startswith("PAGAMENTOS") or h.startswith("PAGAMENTO "):
        if any(k in r for k in ("DARF", "SIMPLES NACIONAL", "GPS", "FGTS", "TRIBUT", "PREFEITURA", "RECEITA", "GARE")):
            return "Tributos/guias"
        return "Pagamento Sispag" if not credito else "Outras entradas"
    if h.startswith("BOLETOS RECEBIDOS"):
        return "Boletos recebidos"
    if h.startswith("RENDIMENTOS") or h.startswith("REND PAGO APLIC"):
        return "Rendimento aplicação automática"
    if h.startswith("PIX ENVIADO"):
        return "PIX enviado"
    if h.startswith("PIX") or h.startswith("TED") or h.startswith("DOC"):
        return "Recebimento PIX/TED" if credito else "TED/DOC enviado"
    if h.startswith("BOLETO PAGO") or h.startswith("PAGTO") or h.startswith("CONCESSIONARIA") \
            or h.startswith("SISPAG CONCESSIONARIA"):
        return "Boletos/contas pagas"
    if h.startswith("RECEBIMENTO REDE") or h.startswith("REDE ") or "CIELO" in h or "GETNET" in h:
        return "Recebíveis de cartão"
    if h.startswith("TAR ") or h.startswith("TARIFA"):
        return "Tarifas bancárias"
    if h.startswith("BUSINESS") or h.startswith("DA ") or h.startswith("SISDEB"):
        return "Débito automático"
    if h.startswith("FATURA CARTAO") or h.startswith("RSCCS") or "CARTAO" in h:
        return "Compras no cartão de débito" if not credito else "Outras entradas"
    if h.startswith("SISPAG TRIB") or "TRIBUTO" in h or h.startswith("DARF") or h.startswith("GPS"):
        return "Tributos/guias"
    if h.startswith("SISPAG"):
        return "Recebimento Sispag" if credito else "Pagamento Sispag"
    if h.startswith("MOV TIT COB") or "COBRANCA" in h:
        return "Cobrança (títulos liquidados)"
    if h.startswith("APLICACAO") or h.startswith("APL "):
        return "Aplicação em CDB"
    if h.startswith("RESGATE") or h.startswith("RES "):
        return "Resgate de CDB"
    if h.startswith("IOF") or h.startswith("JUROS"):
        return "Juros/IOF"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Itaú", origem_resumo="no extrato (saldo anterior e saldo total disponível do último dia)",
                 nota_saldo="saldo = saldo total disponível do dia informado pelo Itaú")
    texto1 = pdf.pages[0].extract_text() or ""
    m = re.search(r"^(.+?) CNPJ [\d./-]+ Agência (\d+) Conta ([\d-]+)", texto1, flags=re.M)
    if m:
        ex.empresa, ex.agencia, ex.conta = m[1].strip(), m[2], m[3]
    m = re.search(r"Lançamentos do período:\s*(\d{2}/\d{2}/\d{4}) até (\d{2}/\d{2}/\d{4})", texto1)
    if m:
        ex.inicio = datetime.strptime(m[1], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2], "%d/%m/%Y").date()

    col = None
    palavras1 = pdf.pages[0].extract_words(x_tolerance=1.5, y_tolerance=1)
    for w in palavras1:
        # só o cabeçalho da tabela (outras partes da página também têm "Valor" e "Saldo")
        if w["text"] == "Razão" and col is None:
            col = {"razao": w["x0"] - 2, "top": w["top"]}
            continue
        if not col or abs(w["top"] - col["top"]) > 2:
            continue
        if w["text"] == "CNPJ/CPF" and "doc" not in col:
            col["doc"] = w["x0"] - 2
        elif w["text"] == "Valor" and "valor" not in col:
            col["valor"] = w["x1"] + 17
        elif w["text"] == "Saldo" and "valor" in col and "saldo" not in col:
            col["saldo"] = w["x1"] + 17
    if not col or not {"doc", "valor", "saldo"} <= set(col):
        return ex

    registros = []
    for n, page in enumerate(pdf.pages):
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
            if texto.startswith("aviso:") or texto.startswith("atualizado em") or texto.startswith("Em caso de"):
                break
            data = ws[0]["text"] if _DATA.match(ws[0]["text"]) and ws[0]["x0"] < 85 else None
            corpo = ws[1:] if data else ws
            item = {"top": top, "data": data, "lanc": [], "razao": [], "doc": [], "valor": None, "saldo": None,
                    "acima": {"lanc": [], "razao": []}, "abaixo": {"lanc": [], "razao": []}}
            for w in corpo:
                t = w["text"]
                if _VALOR.match(t) and w["x0"] > col["doc"] + 60:
                    if abs(w["x1"] - col["valor"]) <= abs(w["x1"] - col["saldo"]):
                        item["valor"] = valor(t)
                    else:
                        item["saldo"] = valor(t)
                elif w["x0"] >= col["doc"]:
                    item["doc"].append(t)
                elif w["x0"] >= col["razao"]:
                    item["razao"].append(t)
                else:
                    item["lanc"].append(t)
            itens.append(item)
        principais = [i for i in itens if i["data"]]
        for i in itens:
            if i["data"]:
                continue
            perto = min(principais, key=lambda p: abs(p["top"] - i["top"]), default=None)
            if perto and abs(perto["top"] - i["top"]) <= DISTANCIA_LINHA:
                lado = perto["acima"] if i["top"] < perto["top"] else perto["abaixo"]
                lado["lanc"] += i["lanc"]
                lado["razao"] += i["razao"]
        registros.extend(principais)

    movimentos = []
    for r in reversed(registros):  # do mais antigo para o mais novo
        dia = datetime.strptime(r["data"], "%d/%m/%Y").date()
        lanc = " ".join(r["acima"]["lanc"] + r["lanc"] + r["abaixo"]["lanc"]).strip()
        razao = " ".join(r["acima"]["razao"] + r["razao"] + r["abaixo"]["razao"]).strip()
        doc = " ".join(r["doc"]).strip()
        m = _DOC.search(razao)
        if m and not doc:  # nome comprido colado ao CNPJ: "…LTDA.30.256.863/0001-95"
            doc, razao = m[1], razao[:m.start()].rstrip(" .") + ("." if razao[:m.start()].endswith(".") else "")
        h = sem_acento(lanc)
        if h.startswith("SALDO ANTERIOR"):
            ex.saldo_anterior, ex.data_saldo_anterior = r["saldo"], dia
            continue
        if h.startswith("SALDO TOTAL DISPONIVEL"):
            if movimentos and movimentos[-1].data == dia:
                movimentos[-1].saldo_banco = r["saldo"]
            ex.saldo_final = r["saldo"]
            continue
        if r["valor"] is None:
            continue
        credito = r["valor"] >= 0
        mov = Movimento(dia, lanc, r["valor"] if credito else None, None if credito else -r["valor"],
                        favorecido=" · ".join(x for x in (razao, doc) if x))
        mov.tipo = _tipo(lanc, credito, razao)
        movimentos.append(mov)
    ex.movimentos = movimentos
    return ex

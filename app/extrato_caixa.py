"""Extrato por período da Caixa (Internet Banking) em planilha organizada.

Cada lançamento ocupa uma linha: data, nº do documento, histórico (abreviado), valor com C/D e
saldo com C/D (D = saldo devedor). O saldo vem em todas as linhas, então a conferência é linha a
linha. "Lançamentos do Dia" (posteriores ao período) vão para uma aba própria.
"""
import re
from datetime import date, datetime, timedelta

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_LINHA = re.compile(r"^(?P<data>\d{2}/\d{2}/\d{4}) (?P<doc>\d+) (?P<hist>.+?) (?P<valor>[\d.]+,\d{2}) (?P<vcd>[CD]) "
                    r"(?P<saldo>[\d.]+,\d{2}) (?P<scd>[CD])$")
_ANTERIOR = re.compile(r"^\d+ SALDO ANTERIOR [\d.]+,\d{2}(?: [CD])? (?P<saldo>[\d.]+,\d{2}) (?P<scd>[CD])$")
ADQUIRENTES = {"CIEL": "Cielo", "STON": "Stone", "GETN": "Getnet", "REDE": "Rede", "PAGS": "PagSeguro",
               "SAFR": "Safrapay", "SIPA": "Sipag", "BIN": "Bin"}
BANDEIRAS = {"MS": "Maestro", "VE": "Visa Electron", "ED": "Elo débito", "MC": "Mastercard", "VS": "Visa",
             "EL": "Elo", "AE": "Amex", "HC": "Hipercard", "DI": "Diners", "CB": "Cabal"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def e_extrato_caixa(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Extrato por período" in texto and "Data Mov. Nr. Doc. Histórico Valor Saldo" in texto \
        and ("caixa" in texto.lower() or "C-AIXA" in texto)


def _com_sinal(numero, cd):
    v = valor(numero)
    return -v if cd == "D" else v


def _cartao(hist):
    """'CIEL MS CD' -> 'Cielo · Maestro (débito)'."""
    m = re.match(r"^(\w{4}) (\w{2}) (CD|CC)$", hist)
    if m and m[1] in ADQUIRENTES:
        bandeira = BANDEIRAS.get(m[2], m[2])
        return f"{ADQUIRENTES[m[1]]} · {bandeira} ({'débito' if m[3] == 'CD' else 'crédito'})"
    return ""


def _tipo(hist, credito):
    h = sem_acento(hist)
    if _cartao(hist) or h.startswith("CR VD CART") or h.startswith("CRED CARTAO"):
        return "Recebíveis de cartão" if credito else "Outras saídas"
    if h.startswith("PIX") or h.startswith("CRED TED") or h.startswith("CRED TEV") or h.startswith("TED REC") \
            or h.startswith("CRED PIX"):
        return "Recebimento PIX/TED" if credito else "PIX enviado"
    if h.startswith("ENVIO TEV") or h.startswith("TRANSF"):
        return "Transferência entre contas" if not credito else "Transferência recebida"
    if h.startswith("ENVIO TED") or h.startswith("ENVIO DOC"):
        return "TED/DOC enviado"
    if h.startswith("DEP") or h.startswith("CR DEP"):
        return "Depósitos"
    if any(h.startswith(p) for p in ("PAG IPVA", "PAG DARF", "PAG GPS", "PAG GRU", "PG ORG GOV", "DEB P FGTS",
                                     "PAG FGTS", "PAG SIMPLES", "PAG TRIB", "PG TRIB")):
        return "Tributos/guias"
    if h.startswith("PAG BOLETO") or h.startswith("PG LUZ") or h.startswith("PG AGUA") or h.startswith("PG TEL") \
            or h.startswith("PAG CONTA") or h.startswith("PG CONTA") or h.startswith("PAG FATURA"):
        return "Boletos/contas pagas"
    if "SALARIO" in h or h.startswith("DB FOLHA") or h.startswith("PAG FOLHA"):
        return "Salários"
    if h.startswith("DEB TARIFA") or h.startswith("DB CEST") or h.startswith("TARIFA") or h.startswith("TAR "):
        return "Tarifas bancárias"
    if "IOF" in h or "JUROS" in h or "JRS" in h:
        return "Juros/IOF"
    if "SEGUR" in h:
        return "Seguros"
    if h.startswith("DB AT") or h.startswith("DEB AUT") or h.startswith("DB AUT"):
        return "Débito automático"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Caixa", origem_resumo="no extrato (saldo anterior e saldo do último lançamento)",
                 rotulo_favorecido="Favorecido / Detalhe", rotulo_saldo_banco="Saldo banco (R$)")
    texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"Cliente:\s*(.+)", texto)
    if m:
        ex.empresa = m[1].strip()
    m = re.search(r"Conta:\s*(\d+)\s*/\s*(\d+)\s*/\s*([\d-]+)", texto)
    if m:
        ex.agencia, ex.conta = m[1], f"{m[2]}/{m[3]}"
    m = re.search(r"hdnDataInicio=(\d{2}/\d{2}/\d{4})&hdnDataFinal=(\d{2}/\d{2}/\d{4})", texto)
    if m:
        ex.inicio = datetime.strptime(m[1], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2], "%d/%m/%Y").date()
    else:
        m = re.search(r"Mês:\s*(\w+)/(\d{4})", texto)
        p = re.search(r"Período:\s*(\d+)\s*-\s*(\d+)", texto)
        if m and p and sem_acento(m[1]).lower() in [sem_acento(x).lower() for x in MESES]:
            mes = [sem_acento(x).lower() for x in MESES].index(sem_acento(m[1]).lower()) + 1
            ex.inicio, ex.fim = date(int(m[2]), mes, int(p[1])), date(int(m[2]), mes, int(p[2]))

    secao = "periodo"
    alvo = ex.movimentos
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("Lançamentos do Dia"):
            secao, alvo = "dia", ex.ultimos
            continue
        m = _ANTERIOR.match(linha)
        if m and secao == "periodo" and ex.saldo_anterior is None:
            ex.saldo_anterior = _com_sinal(m["saldo"], m["scd"])
            continue
        m = _LINHA.match(linha)
        if not m:
            continue
        lanc = _com_sinal(m["valor"], m["vcd"])
        credito = lanc >= 0
        hist = m["hist"].strip()
        mov = Movimento(datetime.strptime(m["data"], "%d/%m/%Y").date(), hist,
                        lanc if credito else None, None if credito else -lanc,
                        saldo_banco=_com_sinal(m["saldo"], m["scd"]), favorecido=_cartao(hist),
                        documento=m["doc"].lstrip("0") or "")
        mov.tipo = _tipo(hist, credito)
        alvo.append(mov)
    if ex.movimentos:
        ex.saldo_final = ex.movimentos[-1].saldo_banco
        if ex.inicio is None:
            ex.inicio = ex.movimentos[0].data.replace(day=1)
    if ex.inicio:
        ex.data_saldo_anterior = ex.inicio - timedelta(days=1)
    if ex.ultimos:
        ex.ultimos_saldo_anterior = ex.saldo_final
        ex.ultimos_data_anterior = ex.fim or ex.movimentos[-1].data
    return ex

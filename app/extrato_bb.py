"""Extrato de conta corrente do Banco do Brasil (Consultas - Extrato de conta corrente).

Linhas: Dt. balancete | Dt. movimento (ag. origem) | Lote | Histórico | Documento | Valor C/D | Saldo C/D,
em ordem cronológica. O detalhe (remetente/destinatário) vem na linha seguinte. O saldo aparece na
última linha de cada dia (depois da aplicação automática BB Rende Fácil).
"""
import re
from datetime import datetime

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_LINHA = re.compile(r"^(?P<data>\d{2}/\d{2}/\d{4}) (?P<ag>\d{4}) (?P<lote>\d+) (?P<resto>.+?) "
                    r"(?P<valor>[\d.]+,\d{2}) (?P<vcd>[CD])(?: (?P<saldo>[\d.]+,\d{2}) (?P<scd>[CD]))?$")
_FIM = ("------", "Transação efetuada", "Serviço de Atendimento", "Para deficientes")


def e_extrato_bb(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Extrato de conta corrente" in texto and "Dt. balancete" in texto


def _sinal(v, cd):
    v = valor(v)
    return -v if cd == "D" else v


def _favorecido(detalhe):
    d = re.sub(r"^\d{2}/\d{2} \d{2}:\d{2}\s+", "", detalhe.strip())
    return d


def _tipo(hist, credito, detalhe=""):
    h, d = sem_acento(hist), sem_acento(detalhe)
    if h.startswith("PIX - RECEBIDO") or h.startswith("PIX RECEBIDO"):
        return "Recebimento PIX/TED"
    if h.startswith("PIX - ENVIADO") or h.startswith("PIX ENVIADO") or h.startswith("PIX - AGENDADO"):
        return "PIX enviado"
    if h.startswith("TED") or h.startswith("DOC"):
        return "Recebimento PIX/TED" if credito else "TED/DOC enviado"
    if h.startswith("TRANSF"):
        return "Transferência recebida" if credito else "Transferência entre contas"
    if "CARTAO CREDITO" in h and not credito or h.startswith("PAGTO CARTAO"):
        return "Cartão de crédito"
    if any(k in h for k in ("CIELO", "REDE", "STONE", "GETNET", "VENDAS", "CARTOES", "CARTAO")):
        return "Recebíveis de cartão" if credito else "Outras saídas"
    if h.startswith("RECEBIMENTO FORNECEDOR") or h.startswith("CESSAO CRED"):
        return "Repasses recebidos" if credito else "Outras saídas"
    if h.startswith("COBRANCA") and credito:
        return "Cobrança (títulos liquidados)"
    if "RENDE FACIL" in h or "APLICACAO" in h or "RESGATE" in h:
        return "Resgate de aplicação" if credito else "Aplicação financeira"
    if h.startswith("IMPOSTOS") or "DARF" in d or "TRIBUT" in h or h.startswith("GPS") or "FGTS" in h:
        return "Tributos/guias"
    if h.startswith("PGTO") or h.startswith("PAGTO") or h.startswith("PAGAMENTO") or "BOLETO" in h \
            or h.startswith("PAG "):
        return "Boletos/contas pagas"
    if h.startswith("CBR") or h.startswith("TAR") or "TARIFA" in h or "TAR." in d or "CARTORARIA" in h:
        return "Tarifas bancárias"
    if "PREV" in h or "SEGUR" in h or "SEGUR" in d:
        return "Seguros"
    if "SALARIO" in h or "FOLHA" in h:
        return "Salários"
    if "IOF" in h or "JUROS" in h:
        return "Juros/IOF"
    if h.startswith("DEPOSITO") or h.startswith("DEP "):
        return "Depósitos"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Banco do Brasil", origem_resumo="no extrato (saldo anterior e saldo final)",
                 rotulo_favorecido="Favorecido / Detalhe", rotulo_saldo_banco="Saldo banco (R$)")
    texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"Agência\s+([\d-]+)", texto)
    if m:
        ex.agencia = m[1]
    m = re.search(r"Conta corrente\s+([\d]+-[\dXx])\s*(.*)", texto)
    if m:
        ex.conta, ex.empresa = m[1], m[2].strip()
    m = re.search(r"Período do extrato de ([\d /]+?) até ([\d /]+)", texto)
    if m:
        ex.inicio = datetime.strptime(m[1].replace(" ", ""), "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2].replace(" ", ""), "%d/%m/%Y").date()

    atual = None
    detalhes = {}
    dentro = False
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith(_FIM):
            atual = None
            continue
        m = _LINHA.match(linha)
        if not m:
            if atual is not None and linha:
                detalhes.setdefault(id(atual), []).append(linha)
            continue
        dentro = True
        resto = m["resto"].split()
        documento = ""
        if len(resto) > 1 and re.fullmatch(r"[\d.]+", resto[-1]):
            documento = resto.pop()
        hist = " ".join(resto)
        h = sem_acento(hist).replace(" ", "")
        lanc = _sinal(m["valor"], m["vcd"])
        saldo = _sinal(m["saldo"], m["scd"]) if m["saldo"] else None
        dia = datetime.strptime(m["data"], "%d/%m/%Y").date()
        if h.startswith("SALDOANTERIOR"):
            ex.saldo_anterior, ex.data_saldo_anterior = lanc if saldo is None else saldo, dia
            atual = None
            continue
        if h == "SALDO":
            ex.saldo_final = lanc
            atual = None
            continue
        credito = lanc >= 0
        atual = Movimento(dia, hist, lanc if credito else None, None if credito else -lanc,
                          saldo_banco=saldo, documento=documento)
        ex.movimentos.append(atual)
    for mov in ex.movimentos:
        det = " ".join(detalhes.get(id(mov), []))
        mov.favorecido = _favorecido(det)
        mov.tipo = _tipo(mov.historico, mov.entrada is not None, det)
    if ex.saldo_final is None and ex.movimentos:
        ex.saldo_final = next((m.saldo_banco for m in reversed(ex.movimentos) if m.saldo_banco is not None), None)
    return ex

"""Extrato de Movimentação do Banco Safra em planilha organizada.

O Safra lista os lançamentos agrupados por dia e por tipo (coluna Quantidade), do mais novo para o
mais antigo. Ao fim de cada dia vêm "CONTA CORRENTE" (saldo da conta), "SALDO POUPANCA PLUS" e
"SALDO TOTAL" (com a poupança automática).
"""
import re
from collections import OrderedDict
from datetime import date, datetime, timedelta

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_LINHA = re.compile(r"^(?P<data>\d{2}/\d{2}) (?P<hist>.+?) (?P<qtd>\d+) (?P<valor>-?[\d.]+,\d{2})$")


def e_extrato_safra(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Banco Safra" in texto and "LANÇAMENTOS REALIZADOS" in texto


def _tipo(hist, credito):
    h = sem_acento(hist)
    if h.startswith("PIX RECEBIDO") or h.startswith("TED") and credito or h.startswith("DOC") and credito:
        return "Recebimento PIX/TED"
    if h.startswith("PIX ENVIADO"):
        return "PIX enviado"
    if h.startswith("TED") or h.startswith("DOC"):
        return "TED/DOC enviado"
    if h.startswith("DEPOSITO EM POUPANCA") or h.startswith("APLICACAO"):
        return "Aplicação financeira"
    if h.startswith("CREDITO DE POUPANCA") or h.startswith("RESGATE"):
        return "Resgate de aplicação"
    if "ALUGUEL" in h:
        return "Tarifas bancárias"
    if "SAFRAPAY" in h or "MAQUINA" in h or "CARTAO" in h:
        return "Recebíveis de cartão" if credito else "Outras saídas"
    if "BOLETO" in h or h.startswith("PAGAMENTO") or h.startswith("PAGTO"):
        if "TRIBUT" in h or "DARF" in h or "GPS" in h:
            return "Tributos/guias"
        return "Boletos/contas pagas" if not credito else "Boletos recebidos"
    if "PACOTE" in h or "TARIFA" in h or h.startswith("TAR "):
        return "Tarifas bancárias"
    if "IOF" in h or "JUROS" in h:
        return "Juros/IOF"
    if "DEPOSITO" in h and credito:
        return "Depósitos"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Safra", origem_resumo="no extrato (saldo da conta corrente do último dia)",
                 rotulo_favorecido="Detalhe", rotulo_saldo_banco="Saldo conta corrente (R$)",
                 titulo_invest="Poupança Plus",
                 descricao_invest="Saldos diários da Poupança Plus e saldo total informados pelo Safra.")
    texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"Extrato de Movimentação\s+(.+)", texto)
    if m:
        ex.empresa = m[1].strip()
    m = re.search(r"AG:\s*(\d+)\s*\|\s*CONTA:\s*([\d-]+)", texto)
    if m:
        ex.agencia, ex.conta = m[1], m[2]
    m = re.search(r"Período de (\d{2}/\d{2}/\d{4}) a (\d{2}/\d{2}/\d{4})", texto)
    if m:
        ex.inicio = datetime.strptime(m[1], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2], "%d/%m/%Y").date()
    ano_fim = (ex.fim or date.today()).year

    dias = OrderedDict()  # data -> linhas do dia, na ordem do extrato
    for linha in texto.splitlines():
        m = _LINHA.match(linha.strip())
        if not m:
            continue
        dd, mm = int(m["data"][:2]), int(m["data"][3:])
        ano = ano_fim - 1 if ex.fim and mm > ex.fim.month else ano_fim
        dias.setdefault(date(ano, mm, dd), []).append(m)

    for dia in sorted(dias):
        ultimo_mov = None
        for m in dias[dia]:
            h = sem_acento(m["hist"])
            v = valor(m["valor"])
            if h.startswith("CONTA CORRENTE"):
                if ultimo_mov is not None:
                    ultimo_mov.saldo_banco = v
                ex.saldo_final = v
                continue
            if h.startswith("SALDO"):
                ex.saldos_invest.append((dia, m["hist"].strip(), v))
                continue
            credito = v >= 0
            qtd = int(m["qtd"])
            mov = Movimento(dia, m["hist"].strip(), v if credito else None, None if credito else -v,
                            favorecido=f"{qtd} lançamentos" if qtd > 1 else "")
            mov.tipo = _tipo(m["hist"], credito)
            ex.movimentos.append(mov)
            ultimo_mov = mov
    s = None
    for i, mv in enumerate(ex.movimentos):
        if mv.saldo_banco is not None:
            s = mv.saldo_banco - sum((x.entrada or 0) - (x.saida or 0) for x in ex.movimentos[:i + 1])
            break
    ex.saldo_anterior = s
    if ex.inicio:
        ex.data_saldo_anterior = ex.inicio - timedelta(days=1)
    return ex

"""Extrato do C6 Bank (PJ, exportado pelo app) em planilha organizada.

Linhas: data lançamento | data contábil | tipo | descrição | valor ("R$ 1,00" / "-R$ 1,00"), em ordem
cronológica, com "Saldo do dia dd/mm/aa R$ ..." ao fim de cada dia e totais de entradas/saídas por mês.
"""
import re
from datetime import date, datetime, timedelta

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")


def e_extrato_c6(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "Extrato exportado no dia" in texto and "Extrato Período" in texto and "C6" in texto


def _data_extenso(t):
    m = re.match(r"(\d{1,2}) de (\w+) de (\d{4})", t.strip())
    if not m:
        return None
    return date(int(m[3]), MESES.get(sem_acento(m[2]).lower(), 1), int(m[1]))


def _tipo(tipo, desc, credito):
    t, d = sem_acento(tipo), sem_acento(desc)
    if "PIX" in t or "TED" in t or "TRANSFER" in t:
        return ("Recebimento PIX/TED" if credito else ("PIX enviado" if "PIX" in t else "TED/DOC enviado"))
    if t.startswith("PAGAMENTO"):
        if any(k in d for k in ("DARF", "SIMPLES NACIONAL", "TRIBUT", "GPS", "FGTS", "DAS ")):
            return "Tributos/guias"
        return "Boletos/contas pagas"
    if "CARTAO" in t:
        return "Compras no cartão de débito" if not credito else "Outras entradas"
    if "SEGURO" in d:
        return "Seguros"
    if "TARIFA" in t or "TARIFA" in d:
        return "Tarifas bancárias"
    if "RENDIMENTO" in t or "RENDIMENTO" in d:
        return "Rendimento aplicação automática"
    if "BOLETO" in t and credito:
        return "Boletos recebidos"
    return "Outras entradas" if credito else "Outras saídas"


def _favorecido(desc):
    return re.sub(r"^(Pix (recebido de|enviado para)|TED (recebida de|enviada para))\s+", "", desc, flags=re.I).strip()


def ler(pdf):
    ex = Extrato(banco="C6 Bank", origem_resumo="no extrato (totais do mês e saldo do dia)",
                 rotulo_saldo_banco="Saldo banco fim do dia (R$)")
    texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"^(.+?) • [\d./-]+\s*$", texto, flags=re.M)
    if m:
        ex.empresa = m[1].strip()
    m = re.search(r"Agência:\s*(\d+)\s*•\s*Conta:\s*([\d-]+)", texto)
    if m:
        ex.agencia, ex.conta = m[1], m[2]
    m = re.search(r"Extrato Período • (.+?) até (.+?)$", texto, flags=re.M)
    if m:
        ex.inicio, ex.fim = _data_extenso(m[1]), _data_extenso(m[2])
    entradas = [valor(x) for x in re.findall(r"Entradas: R\$ ([\d.]+,\d{2})", texto)]
    saidas = [valor(x) for x in re.findall(r"Saídas: R\$ ([\d.]+,\d{2})", texto)]
    if entradas:
        ex.total_entradas, ex.total_saidas = sum(entradas), sum(saidas)

    col = None
    for w in pdf.pages[0].extract_words(x_tolerance=1.5, y_tolerance=1):
        if w["text"] == "Tipo" and col is None:
            col = {"tipo": w["x0"] - 2}
        elif col and w["text"] == "Descrição" and "desc" not in col:
            col["desc"] = w["x0"] - 2
        elif col and w["text"] == "Valor" and "valor" not in col:
            col["valor"] = w["x0"] - 30
    if not col or len(col) < 3:
        return ex

    ano_por_mes = {}
    for a, b in re.findall(r"\( (\d{2}/\d{2}/\d{4}) - (\d{2}/\d{2}/\d{4}) \)", texto):
        for d in (a, b):
            ano_por_mes[int(d[3:5])] = int(d[6:])
    ano_padrao = (ex.inicio or date.today()).year

    movimentos = []
    for page in pdf.pages:
        linhas = []
        for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=1), key=lambda w: (w["top"], w["x0"])):
            if linhas and abs(linhas[-1][0] - w["top"]) <= 2:
                linhas[-1][1].append(w)
            else:
                linhas.append([w["top"], [w]])
        for _, ws in linhas:
            ws.sort(key=lambda w: w["x0"])
            textos = [w["text"] for w in ws]
            if len(textos) >= 5 and textos[:3] == ["Saldo", "do", "dia"] and re.fullmatch(r"\d{2}/\d{2}/\d{2}", textos[3]):
                saldo = valor(textos[-1]) * (-1 if textos[-2].startswith("-") else 1)
                d = datetime.strptime(textos[3], "%d/%m/%y").date()
                if movimentos and movimentos[-1].data == d:
                    movimentos[-1].saldo_banco = saldo
                ex.saldo_final = saldo
                continue
            if len(textos) < 4 or not (re.fullmatch(r"\d{2}/\d{2}", textos[0]) and re.fullmatch(r"\d{2}/\d{2}", textos[1])):
                continue
            if not _VALOR.match(textos[-1]) or not textos[-2].endswith("R$"):
                continue
            lanc = valor(textos[-1]) * (-1 if textos[-2].startswith("-") else 1)
            tipo = " ".join(w["text"] for w in ws[2:-2] if w["x0"] < col["desc"])
            desc = " ".join(w["text"] for w in ws[2:-2] if w["x0"] >= col["desc"])
            mes = int(textos[0][3:])
            dia = date(ano_por_mes.get(mes, ano_padrao), mes, int(textos[0][:2]))
            credito = lanc >= 0
            mov = Movimento(dia, tipo, lanc if credito else None, None if credito else -lanc,
                            favorecido=_favorecido(desc))
            mov.tipo = _tipo(tipo, desc, credito)
            movimentos.append(mov)
    ex.movimentos = movimentos
    # saldo anterior: primeiro saldo do dia menos o líquido dos lançamentos até ele
    s = None
    for i, m in enumerate(movimentos):
        if m.saldo_banco is not None:
            s = m.saldo_banco - sum((x.entrada or 0) - (x.saida or 0) for x in movimentos[:i + 1])
            break
    ex.saldo_anterior = s
    if ex.inicio:
        ex.data_saldo_anterior = ex.inicio - timedelta(days=1)
    return ex

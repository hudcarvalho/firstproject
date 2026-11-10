"""Itaú — "lançamentos período" da conta corrente (data no formato "02 / set") em planilha organizada.

Layout: data | lançamentos | ag/origem | valor (R$) | saldo (R$), em ordem cronológica, um
lançamento por linha, com linhas de mês ("setembro 2026"). O saldo aparece em "SALDO ANTERIOR" e
em "SALDO TOTAL DISPONÍVEL DIA" no fim de cada dia (o PDF às vezes imprime "DISPON#VEL").
"""
import re
from datetime import date, datetime

from .extrato_itau import _favorecido
from .extrato_itau_periodo import _tipo
from .extrato_planilha import Extrato, Movimento, sem_acento, valor

MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
         "nov": 11, "dez": 12}
NOMES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")


def e_extrato_itau_conta(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].extract_text() or ""
    return "lançamentos período:" in texto and "data lançamentos ag/origem valor (R$) saldo (R$)" in texto


def ler(pdf):
    ex = Extrato(banco="Itaú", origem_resumo="no extrato (saldo anterior e saldo total disponível do último dia)",
                 nota_saldo="saldo = saldo total disponível do dia informado pelo Itaú")
    texto1 = pdf.pages[0].extract_text() or ""
    m = re.search(r"^(.+?) agência conta corrente\s*\n\s*[\d./-]+ (\d+) ([\d-]+)", texto1, flags=re.M)
    if m:
        ex.empresa, ex.agencia, ex.conta = m[1].strip(), m[2], m[3]
    m = re.search(r"lançamentos período:\s*(\d{2}/\d{2}/\d{4}) até (\d{2}/\d{2}/\d{4})", texto1)
    if m:
        ex.inicio = datetime.strptime(m[1], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2], "%d/%m/%Y").date()

    col = None
    for w in pdf.pages[0].extract_words(x_tolerance=1.5, y_tolerance=1):
        # só o cabeçalho da tabela (o quadro de saldos no fim também tem "valor" e "saldo")
        if w["text"] == "ag/origem" and col is None:
            col = {"origem": w["x0"] - 5, "top": w["top"]}
        elif col and abs(w["top"] - col["top"]) <= 2 and w["text"] == "valor" and "valor" not in col:
            col["valor"] = w["x1"] + 16
        elif col and abs(w["top"] - col["top"]) <= 2 and w["text"] == "saldo" and "saldo" not in col:
            col["saldo"] = w["x1"] + 16
    if not col or not {"valor", "saldo"} <= set(col):
        return ex

    ano = (ex.inicio or date.today()).year
    mes_inicio = ex.inicio.month if ex.inicio else None
    movimentos = []
    fim = False
    for n, page in enumerate(pdf.pages):
        if fim:
            break
        linhas = []
        for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=1), key=lambda w: (w["top"], w["x0"])):
            if n == 0 and w["top"] <= col["top"] + 2:
                continue
            if linhas and abs(linhas[-1][0] - w["top"]) <= 2:
                linhas[-1][1].append(w)
            else:
                linhas.append([w["top"], [w]])
        for _, ws in linhas:
            ws.sort(key=lambda w: w["x0"])
            textos = [w["text"] for w in ws]
            junto = " ".join(textos)
            if junto.startswith("saldo da conta corrente") or junto.startswith("aviso:"):
                fim = True
                break
            m = re.fullmatch(r"(\w+) (\d{4})", junto)
            if m and sem_acento(m[1]).lower() in NOMES:  # linha de mês ("setembro 2026")
                ano = int(m[2])
                continue
            if len(textos) < 4 or not re.fullmatch(r"\d{2}", textos[0]) or textos[1] != "/" \
                    or textos[2].lower()[:3] not in MESES:
                continue
            mes = MESES[textos[2].lower()[:3]]
            ano_linha = ano - 1 if (mes_inicio and mes > mes_inicio and mes - mes_inicio > 6) else ano
            dia = date(ano_linha, mes, int(textos[0]))
            desc, origem, lanc, saldo = [], [], None, None
            for w in ws[3:]:
                if _VALOR.match(w["text"]) and w["x0"] > col["origem"]:
                    if abs(w["x1"] - col["valor"]) <= abs(w["x1"] - col["saldo"]):
                        lanc = valor(w["text"])
                    else:
                        saldo = valor(w["text"])
                elif w["x0"] >= col["origem"]:
                    origem.append(w["text"])
                else:
                    desc.append(w["text"])
            hist = " ".join(desc).replace("DISPON#VEL", "DISPONÍVEL")
            h = sem_acento(hist)
            if h.startswith("SALDO ANTERIOR"):
                ex.saldo_anterior, ex.data_saldo_anterior = saldo, dia
                continue
            if h.startswith("SALDO TOTAL DISPONIVEL") or h.startswith("SALDO DO DIA"):
                if movimentos and movimentos[-1].data == dia:
                    movimentos[-1].saldo_banco = saldo
                ex.saldo_final = saldo
                continue
            if lanc is None:
                continue
            credito = lanc >= 0
            mov = Movimento(dia, hist, lanc if credito else None, None if credito else -lanc,
                            favorecido=_favorecido(hist), documento=" ".join(origem))
            mov.tipo = _tipo(hist, credito)
            movimentos.append(mov)
    ex.movimentos = movimentos
    return ex

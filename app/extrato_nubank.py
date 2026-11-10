"""Extrato da conta PJ do Nubank em planilha organizada.

Por dia: "DD MMM AAAA Total de entradas + X", os lançamentos de entrada, "Total de saídas - Y", os de
saída e "Saldo do dia". Cada lançamento tem a descrição à esquerda, o favorecido (com banco,
agência e conta, em várias linhas) ao centro e o valor à direita. O rendimento líquido do período
aparece só no resumo: vira um lançamento no último dia para o saldo final conferir.
"""
import re
from datetime import date, timedelta

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
         "NOV": 11, "DEZ": 12}
NOMES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8,
         "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}
_VALOR = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})*,\d{2}$")
_RODAPE = ("Tem alguma dúvida", "metropolitanas)", "Caso a solução", "disponíveis em nubank", "Extrato gerado dia",
           "O saldo líquido corresponde", "Não nos responsabilizamos", "Asseguramos a autenticidade",
           "Nu Financeira", "Nu Pagamentos S.A.", "e Investimento", "CNPJ: ")


def e_extrato_nubank(pdf):
    if not pdf.pages:
        return False
    texto = pdf.pages[0].dedupe_chars().extract_text() or ""
    return "Movimentações" in texto and "Saldo inicial" in texto and "VALORES EM R$" in texto \
        and "Total de entradas" in texto


def _data_extenso(t):
    m = re.match(r"(\d{1,2}) DE (\w+) DE (\d{4})", sem_acento(t.strip()))
    return date(int(m[3]), NOMES.get(m[2], 1), int(m[1])) if m else None


def _tipo(hist, credito):
    h = sem_acento(hist)
    if "RESGATE RDB" in h or h.startswith("RESGATE"):
        return "Resgate de aplicação"
    if "APLICACAO RDB" in h or h.startswith("APLICACAO"):
        return "Aplicação financeira"
    if "PIX" in h or "TRANSFERENCIA" in h or "TED" in h:
        if credito:
            return "Recebimento PIX/TED"
        return "PIX enviado" if "PIX" in h else "TED/DOC enviado"
    if "BOLETO" in h:
        return "Boletos/contas pagas" if not credito else "Boletos recebidos"
    if "CARTAO DE CREDITO" in h and credito:
        return "Outras entradas"
    if "FATURA" in h or "CARTAO DE CREDITO" in h:
        return "Cartão de crédito"
    if "COMPRA" in h or "DEBITO" in h:
        return "Compras no cartão de débito"
    if "RENDIMENTO" in h:
        return "Rendimento aplicação automática"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="Nubank", origem_resumo="no resumo do extrato (saldo inicial, totais e saldo final do período)",
                 rotulo_saldo_banco="Saldo banco fim do dia (R$)")
    paginas = [p.dedupe_chars() for p in pdf.pages]
    texto1 = paginas[0].extract_text() or ""
    m = re.search(r"^(.*?)\s*CNPJ [\d./-]+ Agência (\d+) Conta\s*\n\s*([\d-]+)", texto1, flags=re.M | re.S)
    if m:
        ex.empresa = " ".join(m[1].split()).strip()
        ex.agencia, ex.conta = m[2], m[3]
    m = re.search(r"(\d{2} DE \w+ DE \d{4}) a (\d{2} DE \w+ DE \d{4})", texto1)
    if m:
        ex.inicio, ex.fim = _data_extenso(m[1]), _data_extenso(m[2])
    resumo = {}
    for chave, padrao in (("inicial", r"Saldo inicial ([+-]?[\d.]+,\d{2})"),
                          ("rendimento", r"Rendimento líquido ([+-]?[\d.]+,\d{2})"),
                          ("entradas", r"Total de entradas ([+-]?[\d.]+,\d{2})"),
                          ("saidas", r"Total de saídas ([+-]?[\d.]+,\d{2})"),
                          ("final", r"Saldo final do período ([+-]?[\d.]+,\d{2})")):
        m = re.search(padrao, texto1)
        if m:
            resumo[chave] = valor(m[1].lstrip("+"))
    ex.saldo_anterior = resumo.get("inicial")
    ex.total_entradas = resumo.get("entradas")
    ex.total_saidas = abs(resumo["saidas"]) if "saidas" in resumo else None
    ex.saldo_final = resumo.get("final")

    col = None
    movimentos = []
    dia, sinal, atual = None, 1, None
    for n, page in enumerate(paginas):
        linhas = []
        for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=1), key=lambda w: (w["top"], w["x0"])):
            if linhas and abs(linhas[-1][0] - w["top"]) <= 2:
                linhas[-1][1].append(w)
            else:
                linhas.append([w["top"], [w]])
        comecou = False
        for _, ws in linhas:
            ws.sort(key=lambda w: w["x0"])
            junto = " ".join(w["text"] for w in ws)
            if not comecou:
                comecou = junto.startswith("Movimentações") if n == 0 else "VALORES EM R$" in junto
                continue
            if junto.startswith(_RODAPE):
                break
            # dia
            m = re.match(r"^(\d{2}) ([A-Z]{3}) (\d{4})\b", junto)
            if m and m[2] in MESES:
                dia = date(int(m[3]), MESES[m[2]], int(m[1]))
                ws = [w for w in ws if w["x0"] > ws[2]["x1"] + 1]
                junto = " ".join(w["text"] for w in ws)
                atual = None
                if not ws:
                    continue
            if col is None and ws:
                col = {"desc": ws[0]["x0"] - 2}
            if junto.startswith("Total de entradas"):
                sinal, atual = 1, None
                continue
            if junto.startswith("Total de saídas"):
                sinal, atual = -1, None
                continue
            if junto.startswith("Saldo do dia"):
                saldo = valor(ws[-1]["text"].lstrip("+"))
                if movimentos and movimentos[-1].data == dia:
                    movimentos[-1].saldo_banco = saldo
                atual = None
                continue
            valores = [w for w in ws if _VALOR.match(w["text"]) and w["x0"] > 450]
            corpo = [w for w in ws if w not in valores]
            if valores and dia is not None:
                v = valor(valores[-1]["text"].lstrip("+-"))
                hist = [w["text"] for w in corpo if w["x0"] < 255]
                fav = [w["text"] for w in corpo if w["x0"] >= 255]
                credito = sinal > 0
                atual = Movimento(dia, " ".join(hist), v if credito else None, None if credito else v)
                atual.favorecido = " ".join(fav)
                movimentos.append(atual)
            elif atual is not None and corpo:
                hist = [w["text"] for w in corpo if w["x0"] < 255]
                fav = [w["text"] for w in corpo if w["x0"] >= 255]
                if hist:
                    atual.historico += " " + " ".join(hist)
                if fav:
                    base = re.sub(r"\s+-\s*$", "", atual.favorecido).strip()
                    atual.favorecido = (base + " · " if base else "") + " ".join(fav)
    for mov in movimentos:
        mov.favorecido = re.sub(r"\s+-\s*$", "", mov.favorecido).strip()
        mov.tipo = _tipo(mov.historico, mov.entrada is not None)
    rendimento = resumo.get("rendimento")
    if rendimento and movimentos:
        mov = Movimento(ex.fim or movimentos[-1].data, "Rendimento líquido do período (resumo do Nubank)",
                        rendimento if rendimento > 0 else None, -rendimento if rendimento < 0 else None,
                        saldo_banco=ex.saldo_final, tipo="Rendimento aplicação automática")
        movimentos.append(mov)
        if ex.total_entradas is not None and rendimento > 0:
            ex.total_entradas += rendimento  # o banco informa o rendimento fora dos totais
        elif ex.total_saidas is not None and rendimento < 0:
            ex.total_saidas -= rendimento
    ex.movimentos = movimentos
    if ex.inicio:
        ex.data_saldo_anterior = ex.inicio - timedelta(days=1)
    return ex

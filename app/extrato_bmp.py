"""Extrato Geral do BMP (Banco Moneyplus / BMP SCMEPP) em planilha organizada.

Dias do mais novo para o mais antigo: "dd/mm/aaaa dia-da-semana Saldo inicial do dia R$ X", os
lançamentos (data e hora, tipo em até duas linhas, identificação com DOC, instituição, nº de
controle e ID da transação, valor "+ R$ X" / "- R$ X" e observações) e "Saldo final do dia R$ X".
O PDF imprime o negrito com letras duplicadas, que são removidas na leitura.
"""
import re
from datetime import datetime

from .extrato_planilha import Extrato, Movimento, sem_acento, valor

_VALOR = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")


def e_extrato_bmp(pdf):
    if len(pdf.pages) < 2:
        return False
    texto = pdf.pages[1].dedupe_chars().extract_text() or ""
    return "Extrato Geral" in texto and "MOVIMENTAÇÕES" in texto and "Saldo inicial do dia" in texto


def _tipo(tipo, credito):
    t = sem_acento(tipo)
    if "CUSTO" in t or "TAXA" in t or "TARIFA" in t or "MANUTENCAO" in t:
        return "Tarifas bancárias"
    if "PROTESTO" in t or "CONCILIACAO" in t:
        return "Cobrança (títulos liquidados)" if credito else "Outras saídas"
    if "BOLETO" in t:
        return "Boletos recebidos" if credito else "Boletos/contas pagas"
    if "PIX" in t or "TED" in t or "TRANSFER" in t:
        if credito:
            return "Recebimento PIX/TED"
        return "PIX enviado" if "PIX" in t else "TED/DOC enviado"
    if "TRIBUT" in t or "DARF" in t:
        return "Tributos/guias"
    return "Outras entradas" if credito else "Outras saídas"


def ler(pdf):
    ex = Extrato(banco="BMP", origem_resumo="no extrato (saldo inicial do primeiro dia e saldo final do último)",
                 rotulo_saldo_banco="Saldo banco fim do dia (R$)")
    paginas = [p.dedupe_chars() for p in pdf.pages]
    texto1 = paginas[0].extract_text() or ""
    linhas1 = [l.strip() for l in texto1.splitlines()]
    for i, l in enumerate(linhas1):
        m = re.match(r"BANCO (\d+) \| AGÊNCIA ([\d-]+) \| CONTA (?:\w+ )?([\d-]+)", l)
        if m:
            ex.agencia, ex.conta = m[2], m[3]
            if i:
                ex.empresa = linhas1[i - 1]
            break
    texto2 = paginas[1].extract_text() if len(paginas) > 1 else ""
    m = re.search(r"Período: (\d{2}/\d{2}/\d{4}) a (\d{2}/\d{2}/\d{4})", texto2 or "")
    if m:
        ex.inicio = datetime.strptime(m[1], "%d/%m/%Y").date()
        ex.fim = datetime.strptime(m[2], "%d/%m/%Y").date()

    col = None
    registros = []  # na ordem do PDF
    saldos_finais, saldos_iniciais = {}, {}
    dia_bloco = None
    atual = None
    for page in paginas:
        linhas = []
        for w in sorted(page.extract_words(x_tolerance=1.5, y_tolerance=1), key=lambda w: (w["top"], w["x0"])):
            if linhas and abs(linhas[-1][0] - w["top"]) <= 2:
                linhas[-1][1].append(w)
            else:
                linhas.append([w["top"], [w]])
        for _, ws in linhas:
            ws.sort(key=lambda w: w["x0"])
            textos = [w["text"] for w in ws]
            junto = " ".join(textos)
            if junto.startswith("Hora Tipo Identificação"):
                pos = {w["text"]: w["x0"] for w in ws}  # as colunas mudam de posição entre páginas
                col = {"tipo": pos["Tipo"] - 3, "ident": pos["Identificação"] - 3,
                       "valor": pos["Movimentações"] - 3, "obs": pos["Observações"] - 3}
                continue
            m = re.search(r"^(\d{2}/\d{2}/\d{4}) .*Saldo inicial do dia R\$ ([\d.]+,\d{2})", junto)
            if m:
                dia_bloco = datetime.strptime(m[1], "%d/%m/%Y").date()
                saldos_iniciais[dia_bloco] = valor(m[2])
                atual = None
                continue
            m = re.search(r"Saldo final do dia R\$ (-?[\d.]+,\d{2})", junto)
            if m:
                if dia_bloco:
                    saldos_finais[dia_bloco] = valor(m[1])
                atual = None
                continue
            if col is None or junto.startswith("Página ") or junto.startswith("Documento gerado"):
                continue
            if re.fullmatch(r"\d{2}/\d{2}/\d{2}", textos[0]) and ws[0]["x0"] < col["tipo"]:
                atual = {"data": datetime.strptime(textos[0], "%d/%m/%y").date(), "hora": "", "tipo": [],
                         "ident": [], "obs": [], "valor": None}
                registros.append(atual)
                ws = ws[1:]
            elif atual is None:
                continue
            anterior_tipo = None
            for i, w in enumerate(ws):
                t = w["text"]
                if w["x0"] < col["tipo"]:
                    if re.fullmatch(r"\d{2}h\d{2}", t):
                        atual["hora"] = t
                elif w["x0"] < col["ident"] or (anterior_tipo is not None and w["x0"] - anterior_tipo["x1"] < 4):
                    # o tipo pode passar do início da coluna de identificação
                    atual["tipo"].append(t)
                    anterior_tipo = w
                    continue
                elif w["x0"] < col["valor"]:
                    atual["ident"].append((w["top"], t))
                elif w["x0"] < col["obs"]:
                    if _VALOR.match(t) and atual["valor"] is None:
                        sinal = next((x["text"] for x in ws[:i] if x["text"] in "+-" and x["x0"] >= col["valor"]), "+")
                        atual["valor"] = valor(t) * (-1 if sinal == "-" else 1)
                else:
                    atual["obs"].append(t)

    movimentos = []
    for r in reversed(registros):  # do mais antigo para o mais novo
        if r["valor"] is None:
            continue
        linhas_ident = {}
        for top, t in r["ident"]:
            chave = next((k for k in linhas_ident if abs(k - top) <= 2), top)
            linhas_ident.setdefault(chave, []).append(t)
        ident = [" ".join(v) for _, v in sorted(linhas_ident.items())]
        nome = ident[0] if ident and not ident[0].startswith(("DOC:", "Instituição:", "ID Transação:", "Nº Controle:")) else ""
        nome = "" if nome.strip("- ") == "" else nome
        doc = next((l.split(":", 1)[1].strip() for l in ident if l.startswith("DOC:")), "")
        instituicao = next((l.split(":", 1)[1].strip() for l in ident if l.startswith("Instituição:")), "")
        id_transacao = next((l.split(":", 1)[1].strip() for l in ident if l.startswith("ID Transação:")), "")
        tipo = " ".join(r["tipo"])
        credito = r["valor"] >= 0
        partes = [x for x in (nome, doc) if x]
        if not partes and instituicao and instituicao != "-":
            partes = [instituicao]
        obs = " ".join(r["obs"]).strip(" -")
        mov = Movimento(r["data"], f"{tipo} ({r['hora']})" if r["hora"] else tipo, r["valor"] if credito else None,
                        None if credito else -r["valor"], favorecido=" · ".join(partes + ([obs] if obs else [])),
                        documento=id_transacao)
        mov.tipo = _tipo(tipo, credito)
        movimentos.append(mov)
    # saldo do banco: no último lançamento de cada dia
    for i, mov in enumerate(movimentos):
        if i == len(movimentos) - 1 or movimentos[i + 1].data != mov.data:
            mov.saldo_banco = saldos_finais.get(mov.data)
    ex.movimentos = movimentos
    if saldos_iniciais:
        primeiro = min(saldos_iniciais)
        ex.saldo_anterior, ex.data_saldo_anterior = saldos_iniciais[primeiro], primeiro
    if saldos_finais:
        ex.saldo_final = saldos_finais[max(saldos_finais)]
    return ex

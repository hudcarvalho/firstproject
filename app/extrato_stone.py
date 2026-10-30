"""Extrato da conta Stone (planilha exportada pelo app/portal) em planilha organizada.

A planilha da Stone vem do mais novo para o mais antigo, com uma linha por movimentação:
Movimentação (Crédito/Débito), Tipo, Valor, Saldo antes, Saldo depois, Tarifa, Data (com hora),
Nosso Número, Situação, Destino… e Origem…. A tarifa é descontada do saldo; aqui ela vira uma
linha própria ("Tarifa Stone") logo abaixo do lançamento, para o saldo por fórmula conferir.
"""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal

from .extrato_planilha import Extrato, Movimento

COLUNAS = ["Movimentação", "Tipo", "Valor", "Saldo antes", "Saldo depois", "Tarifa", "Data"]


def _texto(v):
    return "" if v is None else str(v).strip()


def _dinheiro(v):
    """'R$ 1.234,56', '-50,00', 'Grátis' ou número -> Decimal."""
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    t = _texto(v).replace("R$", "").replace("\xa0", "").strip()
    if not t or t.lower() in ("grátis", "gratis", "-"):
        return Decimal("0")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return Decimal(t).quantize(Decimal("0.01"))


def _data(v):
    if isinstance(v, datetime):
        return v
    t = _texto(v)
    for formato in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, formato)
        except ValueError:
            pass
    raise ValueError(t)


def e_extrato_stone(linhas):
    """linhas: lista de listas (a 1ª é o cabeçalho)."""
    return bool(linhas) and all(c in [_texto(x) for x in linhas[0]] for c in COLUNAS)


def _conhecido(v):
    v = _texto(v)
    return "" if v.lower() in ("", "desconhecido", "none") else v


def ler(linhas):
    cab = [_texto(x) for x in linhas[0]]
    i = {nome: cab.index(nome) for nome in cab if nome}

    def campo(linha, nome):
        return linha[i[nome]] if nome in i and i[nome] < len(linha) else None

    # a planilha vem do mais novo para o mais antigo: inverte e ordena de forma estável pela hora,
    # mantendo a ordem do banco entre movimentações do mesmo minuto
    dados = [l for l in linhas[1:] if _texto(campo(l, "Data"))][::-1]
    dados.sort(key=lambda l: _data(campo(l, "Data")))

    # titular da conta: o destino mais comum dos créditos
    titulares = Counter((_conhecido(campo(l, "Destino")), _conhecido(campo(l, "Destino Documento")),
                         _conhecido(campo(l, "Destino Agência")), _conhecido(campo(l, "Destino Conta")))
                        for l in dados if _texto(campo(l, "Movimentação")).startswith("Cr"))
    nome, documento, agencia, conta = titulares.most_common(1)[0][0] if titulares else ("", "", "", "")
    ex = Extrato(banco="Stone", empresa=nome, agencia=agencia, conta=conta,
                 origem_resumo="na planilha (saldo antes da 1ª e depois da última movimentação)",
                 rotulo_saldo_banco="Saldo banco (R$)")
    if not dados:
        return ex
    primeira, ultima = _data(campo(dados[0], "Data")), _data(campo(dados[-1], "Data"))
    ex.inicio, ex.fim = primeira.date().replace(day=1), ultima.date()
    ex.saldo_anterior = _dinheiro(campo(dados[0], "Saldo antes"))
    ex.saldo_final = _dinheiro(campo(dados[-1], "Saldo depois"))
    ex.data_saldo_anterior = primeira.date() - timedelta(days=1)

    for l in dados:
        quando = _data(campo(l, "Data"))
        credito = _texto(campo(l, "Movimentação")).startswith("Cr")
        tipo_stone = _texto(campo(l, "Tipo"))
        valor = _dinheiro(campo(l, "Valor"))
        tarifa = _dinheiro(campo(l, "Tarifa"))
        if credito:
            parte = _conhecido(campo(l, "Origem")) or _conhecido(campo(l, "Origem Instituição"))
            doc_parte = _conhecido(campo(l, "Origem Documento"))
        else:
            parte = _conhecido(campo(l, "Destino")) or _conhecido(campo(l, "Destino Instituição"))
            doc_parte = _conhecido(campo(l, "Destino Documento"))
        historico = f"{tipo_stone} {'recebido' if credito else 'enviado'}" if tipo_stone in ("Pix",) else \
            f"{tipo_stone} ({'crédito' if credito else 'débito'})"
        favorecido = " · ".join(x for x in (parte, doc_parte) if x)
        nosso_numero = _texto(campo(l, "Nosso Número"))
        mov = Movimento(quando.date(), historico, abs(valor) if credito else None, None if credito else abs(valor),
                        favorecido=favorecido, documento=nosso_numero, tipo=_tipo(tipo_stone, credito))
        mov.historico = f"{historico} {quando:%H:%M}"
        depois = _dinheiro(campo(l, "Saldo depois"))
        if tarifa:
            ex.movimentos.append(mov)
            mov = Movimento(quando.date(), f"Tarifa Stone ({tipo_stone})", None, tarifa,
                            favorecido=favorecido, tipo="Tarifas bancárias")
        mov.saldo_banco = depois
        ex.movimentos.append(mov)
    return ex


def _tipo(tipo_stone, credito):
    t = tipo_stone.lower()
    if t == "pix":
        return "Recebimento PIX/TED" if credito else "PIX enviado"
    if "receb" in t and "cart" in t:
        return "Recebíveis de cartão"
    if t == "pagamento":
        return "Boletos recebidos" if credito else "Boletos/contas pagas"
    if t in ("transação", "transacao"):
        return "Transações recebidas" if credito else "Transações debitadas (Stone)"
    if "ted" in t or "transfer" in t:
        return "Recebimento PIX/TED" if credito else "TED/DOC enviado"
    if "tarifa" in t:
        return "Tarifas bancárias"
    return "Outras entradas" if credito else "Outras saídas"

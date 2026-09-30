"""Utilitários para competências (mês/ano) e CNPJ."""
import re
from datetime import date


def parse_competencia(valor):
    """Converte 'AAAA-MM' (input type=month) ou 'MM/AAAA' em date(dia 1). Retorna None se vazio/inválido."""
    if not valor:
        return None
    valor = valor.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", valor) or re.fullmatch(r"(\d{1,2})/(\d{4})", valor)
    if not m:
        return None
    a, b = m.groups()
    ano, mes = (int(a), int(b)) if len(a) == 4 else (int(b), int(a))
    if not 1 <= mes <= 12:
        return None
    return date(ano, mes, 1)


def fmt_competencia(d):
    return d.strftime("%m/%Y") if d else "—"


def input_competencia(d):
    return d.strftime("%Y-%m") if d else ""


def meses_entre(inicio, fim):
    """Número de meses de `inicio` até `fim` (fim - inicio)."""
    return (fim.year - inicio.year) * 12 + (fim.month - inicio.month)


def somar_meses(d, n):
    total = d.year * 12 + (d.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


def competencia_esperada(periodicidade, hoje):
    """Última competência já encerrada que deveria estar cumprida na data `hoje`.

    - mensal: mês anterior
    - trimestral: último mês do trimestre anterior (03, 06, 09, 12)
    - anual: dezembro do ano anterior
    - eventual: None (sem controle de periodicidade)
    """
    mes_atual = date(hoje.year, hoje.month, 1)
    if periodicidade == "mensal":
        return somar_meses(mes_atual, -1)
    if periodicidade == "trimestral":
        fim_trim_atual = ((hoje.month - 1) // 3 + 1) * 3
        return somar_meses(date(hoje.year, fim_trim_atual, 1), -3)
    if periodicidade == "anual":
        return date(hoje.year - 1, 12, 1)
    return None


def so_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def cnpj_valido(cnpj):
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False

    def dv(base, pesos):
        s = sum(int(x) * p for x, p in zip(base, pesos))
        r = s % 11
        return "0" if r < 2 else str(11 - r)

    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(c[:12], p1)
    d2 = dv(c[:12] + d1, [6] + p1)
    return c[12:] == d1 + d2


def cpf_valido(cpf):
    c = so_digitos(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(c[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10 % 11) % 10
        if int(c[tamanho]) != digito:
            return False
    return True


def fmt_documento(doc):
    """CPF (11 dígitos) ou CNPJ (14 dígitos) com pontuação."""
    d = so_digitos(doc)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return doc or ""


def parse_valor(texto):
    """Valor em reais digitado no formato brasileiro ("1.234,56") -> Decimal; vazio -> None.

    Levanta ValueError se não for um número.
    """
    from decimal import Decimal, InvalidOperation
    t = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")  # "2.000" e "1.500.000": ponto como separador de milhar
    try:
        valor = Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(texto)
    return valor


def fmt_valor(valor, vazio=""):
    """Decimal -> "1.234,56" (sem R$)."""
    if valor is None:
        return vazio
    inteiro, _, centavos = f"{valor:,.2f}".partition(".")
    return inteiro.replace(",", ".") + "," + centavos

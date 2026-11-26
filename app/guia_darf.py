"""Quotas do IRPJ e da CSLL apurados no LALUR: divisão em quotas, vencimentos e juros.

Regras (Lei 9.430/1996, arts. 5º e 6º):
- trimestral: quota única até o último dia útil do mês seguinte ao fim do trimestre, ou até
  3 quotas mensais iguais, nenhuma menor que R$ 1.000,00 (imposto abaixo de R$ 2.000,00 é pago
  em quota única), vencendo no último dia útil de cada um dos 3 meses seguintes; a 2ª quota tem
  juros de 1% e a 3ª, Selic do mês anterior ao pagamento + 1%;
- anual (saldo do ajuste): quota única até o último dia útil de março do ano seguinte.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
QUOTA_MINIMA = Decimal("1000")



def _q(v):
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ultimo_dia_util(ano, mes):
    """Último dia de segunda a sexta do mês (feriados não são considerados)."""
    d = date(ano, mes, calendar.monthrange(ano, mes)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _mes_somado(ano, mes, n):
    total = ano * 12 + (mes - 1) + n
    return total // 12, total % 12 + 1


def fim_do_periodo(ano, periodo):
    mes = 12 if periodo == 0 else periodo * 3
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


@dataclass
class Quota:
    numero: int
    vencimento: date
    principal: Decimal
    juros_pct: Decimal | None  # None = Selic não informada
    juros: Decimal | None

    @property
    def total(self):
        return None if self.juros is None else self.principal + self.juros


def quotas(valor, ano, periodo, parcelas=1, selic=None):
    """Divide o imposto em quotas. Devolve (lista de Quota, aviso ou None)."""
    aviso = None
    if valor <= 0:
        return [], None
    if periodo == 0:  # ajuste anual: só quota única, vence em março do ano seguinte
        if parcelas > 1:
            aviso = "O saldo do ajuste anual é pago em quota única."
        return [Quota(1, ultimo_dia_util(ano + 1, 3), _q(valor), ZERO, ZERO)], aviso
    parcelas = max(1, min(3, parcelas))
    if parcelas > 1:
        possivel = int(valor // QUOTA_MINIMA)
        if possivel < parcelas:
            parcelas = max(1, min(possivel, 3))
            aviso = ("Imposto abaixo de R$ 2.000,00: pagamento em quota única." if parcelas == 1 else
                     f"Nenhuma quota pode ser menor que R$ 1.000,00: dividido em {parcelas} quotas.")
    fim = periodo * 3
    base = _q(valor / parcelas)
    lista = []
    for n in range(1, parcelas + 1):
        principal = base if n < parcelas else _q(valor) - base * (parcelas - 1)
        if n == 1:
            pct = ZERO
        elif n == 2:
            pct = Decimal("1")
        else:
            pct = None if selic is None else selic + 1
        juros = None if pct is None else _q(principal * pct / 100)
        lista.append(Quota(n, ultimo_dia_util(*_mes_somado(ano, fim, n)), principal, pct, juros))
    return lista, aviso

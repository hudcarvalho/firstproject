"""Demonstrativo para emissão de DARF do IRPJ e da CSLL apurados no LALUR.

Não é documento de arrecadação: o DARF com código de barras é numerado e registrado pela
Receita Federal (Sicalc Web / DCTFWeb). Aqui calculamos as quotas, vencimentos e juros e
reunimos os dados que vão em cada campo do DARF, para emitir a guia oficial.

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

# Códigos de receita do DARF (Lucro Real), editáveis na tela.
CODIGOS = {
    "trimestral": {"irpj": "0220", "csll": "6012"},
    "anual": {"irpj": "2430", "csll": "6773"},
}

SICALC = "https://sicalc.receita.economia.gov.br/sicalc/principal"


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


def pdf(empresa, ano, periodo, guias, forma):
    """guias: [(tributo, codigo, [Quota])]. Uma ficha por quota, com os campos do DARF."""
    from .competencia import fmt_valor
    from .pdf_simples import Documento

    rotulo = "Ajuste anual" if periodo == 0 else f"{periodo}º trimestre"
    doc = Documento(f"Dados para DARF {rotulo} {ano} - {empresa.razao_social}")
    m, larg = 36, doc.largura_pagina - 72
    d = m + larg

    def cabecalho():
        doc.texto(m, 40, "Demonstrativo para emissão de DARF — IRPJ e CSLL", 13, negrito=True)
        doc.texto(d, 40, f"{rotulo} de {ano}", 11, negrito=True, alinhar="direita")
        doc.texto(m, 56, empresa.razao_social, 10)
        doc.texto(m, 69, f"CNPJ {empresa.cnpj_formatado} · Lucro Real · "
                         f"{'Quota única' if forma == 'unica' else 'Parcelado'}", 8.5, cinza=0.35)
        doc.linha(m, 76, d, 76, 1, 0.3)
        doc.faixa(m, 84, larg, 30, 0.95)
        doc.texto(m + 8, 97, "Este demonstrativo NÃO é documento de arrecadação e não tem código de barras.",
                  8.5, negrito=True)
        doc.texto(m + 8, 109, "Emita o DARF numerado no Sicalc Web (Receita Federal) ou pela DCTFWeb com "
                              "os dados abaixo.", 8.5)
        doc.texto(m, doc.altura_pagina - 24,
                  f"Emitido em {date.today():%d/%m/%Y} pelo Controle de Rotina · {SICALC}", 7.5, cinza=0.45)

    cabecalho()
    y = 132
    altura_ficha = 132
    apuracao = fim_do_periodo(ano, periodo)
    for tributo, codigo, lista in guias:
        for q in lista:
            if y + altura_ficha > doc.altura_pagina - 40:
                doc.nova_pagina()
                cabecalho()
                y = 132
            titulo = f"{tributo} — {'quota única' if len(lista) == 1 else f'{q.numero}ª quota de {len(lista)}'}"
            doc.faixa(m, y, larg, 16, 0.85)
            doc.texto(m + 6, y + 11.5, titulo, 9.5, negrito=True)
            campos = [
                ("01", "Nome / telefone", empresa.razao_social[:60]),
                ("02", "Período de apuração", f"{apuracao:%d/%m/%Y}"),
                ("03", "Número do CPF ou CNPJ", empresa.cnpj_formatado),
                ("04", "Código da receita", codigo),
                ("05", "Número de referência", "—"),
                ("06", "Data de vencimento", f"{q.vencimento:%d/%m/%Y}"),
                ("07", "Valor do principal", fmt_valor(q.principal)),
                ("08", "Valor da multa", "0,00"),
                ("09", "Valor dos juros / encargos",
                 fmt_valor(q.juros) + (f"  ({fmt_valor(q.juros_pct)}%)" if q.juros_pct else "")
                 if q.juros is not None else "Selic do mês anterior + 1% (calcular no Sicalc)"),
                ("10", "Valor total", fmt_valor(q.total) if q.total is not None else "principal + juros"),
            ]
            yy = y + 16
            col = larg / 2
            for i, (num, nome, valor) in enumerate(campos):
                x = m + (i % 2) * col
                if i % 2 == 0 and i:
                    yy += 22
                doc.linha(x, yy, x, yy + 22, 0.4, 0.75)
                doc.texto(x + 5, yy + 8, f"{num}  {nome}", 6.8, cinza=0.4)
                destaque = num in ("04", "06", "10")
                doc.texto(x + col - 6, yy + 18.5, valor, 9.5, negrito=destaque, alinhar="direita")
                doc.linha(x, yy + 22, x + col, yy + 22, 0.4, 0.75)
            doc.linha(m + larg, y + 16, m + larg, yy + 22, 0.4, 0.75)
            y = yy + 22 + 14
    return doc.gerar()

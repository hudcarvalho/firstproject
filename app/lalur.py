"""Aba LALUR (empresas do Lucro Real).

Parte A: por período (trimestre ou anual), lucro líquido antes do IRPJ/CSLL, adições e
exclusões, compensação de prejuízo fiscal / base negativa (limite de 30% do lucro ajustado)
e cálculo do IRPJ (15% + adicional de 10% sobre o que passar de R$ 20.000,00 por mês) e da
CSLL. Parte B: saldos de prejuízo fiscal e de base negativa, encadeados de um período ao
outro a partir do saldo de abertura informado.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .competencia import parse_valor
from .models import Empresa, LalurApuracao, LalurLancamento, LalurSaldoInicial, db

bp = Blueprint("lalur", __name__, url_prefix="/lalur")

ZERO = Decimal("0")
LIMITE_COMPENSACAO = Decimal("0.30")
ALIQUOTA_IRPJ = Decimal("0.15")
ALIQUOTA_ADICIONAL = Decimal("0.10")
LIMITE_ADICIONAL_MES = Decimal("20000")

SUGESTOES_ADICAO = [
    "Multas por infrações fiscais", "Brindes", "Doações não dedutíveis",
    "Provisões não dedutíveis", "Despesas com alimentação de sócios/dirigentes",
    "Resultado negativo de equivalência patrimonial", "Gratificações a administradores",
    "Despesas não necessárias à atividade", "Depreciação acima do limite fiscal",
]
SUGESTOES_EXCLUSAO = [
    "Resultado positivo de equivalência patrimonial", "Dividendos recebidos",
    "Reversão de provisões adicionadas anteriormente", "Juros sobre o capital próprio pagos",
    "Depreciação acelerada incentivada", "Ganhos de AVJ (diferidos)",
]


# Linhas do demonstrativo: (rótulo, valor no Demonstrativo, estilo). Estilo "secao" = título.
LINHAS = [
    ("Lucro líquido antes do IRPJ/CSLL", lambda d: d.apuracao.lucro_antes, ""),
    ("IRPJ", None, "secao"),
    ("(+) Adições", lambda d: d.irpj.adicoes, ""),
    ("(−) Exclusões", lambda d: d.irpj.exclusoes, ""),
    ("= Lucro ajustado", lambda d: d.irpj.ajustado, "subtotal"),
    ("(−) Compensação de prejuízo fiscal", lambda d: d.irpj.compensacao, ""),
    ("= Lucro real", lambda d: d.irpj.base, "subtotal"),
    ("IRPJ 15%", lambda d: d.irpj_normal, ""),
    ("Adicional 10%", lambda d: d.irpj_adicional, ""),
    ("(−) Deduções (retenções/antecipações)", lambda d: d.apuracao.irpj_deduzir, ""),
    ("IRPJ a pagar", lambda d: d.irpj_a_pagar, "total"),
    ("CSLL", None, "secao"),
    ("(+) Adições", lambda d: d.csll.adicoes, ""),
    ("(−) Exclusões", lambda d: d.csll.exclusoes, ""),
    ("= Base ajustada", lambda d: d.csll.ajustado, "subtotal"),
    ("(−) Compensação de base negativa", lambda d: d.csll.compensacao, ""),
    ("= Base de cálculo", lambda d: d.csll.base, "subtotal"),
    ("CSLL devida", lambda d: d.csll_devida, ""),
    ("(−) Deduções (retenções/antecipações)", lambda d: d.apuracao.csll_deduzir, ""),
    ("CSLL a pagar", lambda d: d.csll_a_pagar, "total"),
    ("Parte B — saldos ao final do período", None, "secao"),
    ("Prejuízo fiscal a compensar (IRPJ)", lambda d: d.irpj.saldo_final, ""),
    ("Base negativa a compensar (CSLL)", lambda d: d.csll.saldo_final, ""),
]


def rotulo_periodo(periodo, curto=False):
    if periodo == 0:
        return "Anual"
    return f"{periodo}º trim." if curto else f"{periodo}º trimestre"


def _q(v):
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Tributo:
    """Apuração de um tributo (IRPJ ou CSLL) em um período."""

    adicoes: Decimal = ZERO
    exclusoes: Decimal = ZERO
    ajustado: Decimal = ZERO        # lucro ajustado antes da compensação
    saldo_anterior: Decimal = ZERO  # prejuízo fiscal / base negativa disponível
    compensacao: Decimal = ZERO
    gerado: Decimal = ZERO          # prejuízo / base negativa gerada no período
    base: Decimal = ZERO            # lucro real / base de cálculo da CSLL

    @property
    def saldo_final(self):
        return self.saldo_anterior - self.compensacao + self.gerado


@dataclass
class Demonstrativo:
    apuracao: LalurApuracao
    irpj: Tributo = field(default_factory=Tributo)
    csll: Tributo = field(default_factory=Tributo)
    irpj_normal: Decimal = ZERO
    irpj_adicional: Decimal = ZERO
    csll_devida: Decimal = ZERO

    @property
    def irpj_devido(self):
        return self.irpj_normal + self.irpj_adicional

    @property
    def irpj_a_pagar(self):
        return max(self.irpj_devido - self.apuracao.irpj_deduzir, ZERO)

    @property
    def csll_a_pagar(self):
        return max(self.csll_devida - self.apuracao.csll_deduzir, ZERO)


def _apurar_tributo(apuracao, chave, saldo):
    t = Tributo(saldo_anterior=saldo)
    for l in apuracao.lancamentos:
        if l.tributo in ("ambos", chave):
            if l.tipo == "adicao":
                t.adicoes += l.valor
            else:
                t.exclusoes += l.valor
    t.ajustado = apuracao.lucro_antes + t.adicoes - t.exclusoes
    if t.ajustado < 0:
        t.gerado = -t.ajustado
    else:
        if apuracao.compensar:
            t.compensacao = min(saldo, _q(t.ajustado * LIMITE_COMPENSACAO))
        t.base = t.ajustado - t.compensacao
    return t


def ordem(apuracao):
    """Ordem cronológica: trimestres 1-4 e a anual (0) ao fim do ano."""
    return apuracao.ano, apuracao.periodo or 5


def demonstrativos(empresa):
    """Calcula todas as apurações da empresa em ordem, encadeando os saldos da Parte B.

    Devolve {(ano, periodo): Demonstrativo} e os saldos finais (prejuízo, base negativa).
    Períodos sem lucro informado não entram no cálculo (os saldos passam direto).
    """
    abertura = db.session.query(LalurSaldoInicial).filter_by(empresa_id=empresa.id).first()
    prejuizo = abertura.prejuizo_fiscal if abertura else ZERO
    base_negativa = abertura.base_negativa if abertura else ZERO
    resultado = {}
    apuracoes = LalurApuracao.query.filter_by(empresa_id=empresa.id).all()
    for a in sorted(apuracoes, key=ordem):
        if a.lucro_antes is None:
            continue
        d = Demonstrativo(a)
        d.irpj = _apurar_tributo(a, "irpj", prejuizo)
        d.csll = _apurar_tributo(a, "csll", base_negativa)
        meses = 12 if a.periodo == 0 else 3
        d.irpj_normal = _q(d.irpj.base * ALIQUOTA_IRPJ)
        d.irpj_adicional = _q(max(d.irpj.base - LIMITE_ADICIONAL_MES * meses, ZERO) * ALIQUOTA_ADICIONAL)
        d.csll_devida = _q(d.csll.base * a.aliquota_csll / 100)
        prejuizo, base_negativa = d.irpj.saldo_final, d.csll.saldo_final
        resultado[(a.ano, a.periodo)] = d
    return resultado, (prejuizo, base_negativa)


# ---------------------------------------------------------------- telas

def _empresa(id_):
    empresa = db.session.get(Empresa, id_)
    if empresa is None:
        abort(404)
    return empresa


def _ano():
    try:
        ano = int(request.values.get("ano", ""))
    except ValueError:
        return date.today().year
    return ano if 2000 <= ano <= 2100 else date.today().year


def _exige_lucro_real(empresa):
    if not empresa.lucro_real:
        flash("O LALUR é usado só por empresas do Lucro Real.", "warning")
        return redirect(url_for("main.empresa_detalhe", id=empresa.id))
    return None


def _periodo(valor):
    if valor not in (0, 1, 2, 3, 4):
        abort(404)
    return valor


def _modo(empresa, ano):
    """'anual' ou 'trimestral' para o ano (pelo que já foi lançado; padrão trimestral)."""
    periodos = {p for (p,) in db.session.query(LalurApuracao.periodo)
                .filter_by(empresa_id=empresa.id, ano=ano)}
    if 0 in periodos:
        return "anual", True
    if periodos:
        return "trimestral", True
    return ("anual" if request.args.get("modo") == "anual" else "trimestral"), False


@bp.route("/<int:id>")
def empresa(id):
    empresa = _empresa(id)
    if (r := _exige_lucro_real(empresa)):
        return r
    ano = _ano()
    modo, modo_fixo = _modo(empresa, ano)
    periodos = [0] if modo == "anual" else [1, 2, 3, 4]
    calc, _ = demonstrativos(empresa)
    existentes = {a.periodo: a for a in LalurApuracao.query.filter_by(empresa_id=empresa.id, ano=ano)}
    colunas = [{"periodo": p, "rotulo": rotulo_periodo(p, curto=True),
                "apuracao": existentes.get(p), "d": calc.get((ano, p))} for p in periodos]
    abertura = LalurSaldoInicial.query.filter_by(empresa_id=empresa.id).first()
    return render_template("lalur/empresa.html", empresa=empresa, ano=ano, modo=modo,
                           modo_fixo=modo_fixo, colunas=colunas, abertura=abertura, linhas=LINHAS,
                           apurados=[c for c in colunas if c["d"]])


@bp.post("/<int:id>/saldo-inicial")
def saldo_inicial(id):
    empresa = _empresa(id)
    try:
        prejuizo = parse_valor(request.form.get("prejuizo_fiscal")) or ZERO
        base = parse_valor(request.form.get("base_negativa")) or ZERO
        if prejuizo < 0 or base < 0:
            raise ValueError
    except ValueError:
        flash("Saldos de abertura inválidos: informe valores positivos, como 15.000,00.", "danger")
    else:
        abertura = LalurSaldoInicial.query.filter_by(empresa_id=empresa.id).first()
        if abertura is None:
            abertura = LalurSaldoInicial(empresa_id=empresa.id)
            db.session.add(abertura)
        abertura.prejuizo_fiscal, abertura.base_negativa = prejuizo, base
        db.session.commit()
        flash("Saldos de abertura da Parte B salvos.", "success")
    return redirect(url_for("lalur.empresa", id=id, ano=_ano()))


def _obter_apuracao(empresa, ano, periodo, criar=False):
    a = LalurApuracao.query.filter_by(empresa_id=empresa.id, ano=ano, periodo=periodo).first()
    if a is None and criar:
        a = LalurApuracao(empresa_id=empresa.id, ano=ano, periodo=periodo, compensar=True,
                          aliquota_csll=Decimal("9"), irpj_deduzir=ZERO, csll_deduzir=ZERO)
        db.session.add(a)
    return a


def _conflito_de_modo(empresa, ano, periodo):
    """Não mistura apuração anual e trimestral no mesmo ano."""
    outros = LalurApuracao.query.filter_by(empresa_id=empresa.id, ano=ano)
    if periodo == 0:
        return outros.filter(LalurApuracao.periodo != 0).count() > 0
    return outros.filter_by(periodo=0).count() > 0


@bp.route("/<int:id>/<int:ano>/<int:periodo>")
def periodo(id, ano, periodo):
    empresa = _empresa(id)
    if (r := _exige_lucro_real(empresa)):
        return r
    periodo = _periodo(periodo)
    apuracao = _obter_apuracao(empresa, ano, periodo)
    calc, _ = demonstrativos(empresa)
    rotulo = rotulo_periodo(periodo)
    return render_template(
        "lalur/periodo.html", empresa=empresa, ano=ano, periodo=periodo, rotulo=rotulo,
        apuracao=apuracao, d=calc.get((ano, periodo)), tipos=LalurLancamento.TIPOS,
        tributos=LalurLancamento.TRIBUTOS, sugestoes_adicao=SUGESTOES_ADICAO,
        sugestoes_exclusao=SUGESTOES_EXCLUSAO,
    )


def _voltar_periodo(id, ano, periodo, ancora=""):
    return redirect(url_for("lalur.periodo", id=id, ano=ano, periodo=periodo) + ancora)


@bp.post("/<int:id>/<int:ano>/<int:periodo>")
def salvar(id, ano, periodo):
    empresa = _empresa(id)
    periodo = _periodo(periodo)
    if _conflito_de_modo(empresa, ano, periodo):
        flash("Este ano já tem apuração em outro formato (anual × trimestral).", "danger")
        return redirect(url_for("lalur.empresa", id=id, ano=ano))
    f = request.form
    try:
        lucro = parse_valor(f.get("lucro_antes"))
        aliquota = parse_valor(f.get("aliquota_csll")) or Decimal("9")
        irpj_ded = parse_valor(f.get("irpj_deduzir")) or ZERO
        csll_ded = parse_valor(f.get("csll_deduzir")) or ZERO
        if not ZERO <= aliquota <= 100 or irpj_ded < 0 or csll_ded < 0:
            raise ValueError
    except ValueError:
        flash("Valores inválidos. Use o formato 1.234,56 (o lucro pode ser negativo: -1.234,56).", "danger")
        return _voltar_periodo(id, ano, periodo)
    a = _obter_apuracao(empresa, ano, periodo, criar=True)
    a.lucro_antes = lucro
    a.compensar = f.get("compensar") == "on"
    a.aliquota_csll, a.irpj_deduzir, a.csll_deduzir = aliquota, irpj_ded, csll_ded
    a.observacao = (f.get("observacao") or "").strip() or None
    db.session.commit()
    flash("Apuração salva." if lucro is not None else
          "Apuração salva. Informe o lucro antes do IRPJ/CSLL para calcular.", "success")
    return _voltar_periodo(id, ano, periodo)


@bp.post("/<int:id>/<int:ano>/<int:periodo>/lancamentos")
def lancamento_novo(id, ano, periodo):
    empresa = _empresa(id)
    periodo = _periodo(periodo)
    if _conflito_de_modo(empresa, ano, periodo):
        flash("Este ano já tem apuração em outro formato (anual × trimestral).", "danger")
        return redirect(url_for("lalur.empresa", id=id, ano=ano))
    f = request.form
    tipo, tributo = f.get("tipo"), f.get("tributo") or "ambos"
    descricao = (f.get("descricao") or "").strip()
    try:
        valor = parse_valor(f.get("valor"))
    except ValueError:
        valor = None
    if tipo not in LalurLancamento.TIPOS or tributo not in LalurLancamento.TRIBUTOS \
            or not descricao or valor is None or valor <= 0:
        flash("Lançamento inválido: informe tipo, descrição e um valor positivo.", "danger")
        return _voltar_periodo(id, ano, periodo, "#lancamentos")
    a = _obter_apuracao(empresa, ano, periodo, criar=True)
    a.lancamentos.append(LalurLancamento(tipo=tipo, tributo=tributo, descricao=descricao[:200],
                                         valor=valor))
    db.session.commit()
    flash(f"{LalurLancamento.TIPOS[tipo]} lançada.", "success")
    return _voltar_periodo(id, ano, periodo, "#lancamentos")


@bp.post("/lancamentos/<int:lid>/remover")
def lancamento_remover(lid):
    l = db.session.get(LalurLancamento, lid)
    if l is None:
        abort(404)
    a = l.apuracao
    db.session.delete(l)
    db.session.commit()
    flash("Lançamento removido.", "success")
    return _voltar_periodo(a.empresa_id, a.ano, a.periodo, "#lancamentos")


@bp.post("/<int:id>/<int:ano>/<int:periodo>/excluir")
def excluir(id, ano, periodo):
    empresa = _empresa(id)
    a = _obter_apuracao(empresa, ano, _periodo(periodo))
    if a is not None:
        db.session.delete(a)
        db.session.commit()
        flash("Apuração do período excluída.", "success")
    return redirect(url_for("lalur.empresa", id=id, ano=ano))


# ---------------------------------------------------------------- exportação (PDF e Excel)

def _fmt(v):
    from .competencia import fmt_valor
    return fmt_valor(v) if v is not None else ""


def _nome_arquivo(empresa, ano, periodos, extensao):
    sufixo = "todos" if len(periodos) > 1 else ("anual" if periodos[0][0] == 0 else f"{periodos[0][0]}tri")
    return f"lalur_{empresa.codigo or empresa.id}_{ano}_{sufixo}.{extensao}"


def _pdf(empresa, ano, periodos):
    """periodos: [(periodo, Demonstrativo)] já apurados."""
    from .pdf_simples import Documento

    doc = Documento(f"LALUR {ano} - {empresa.razao_social}")
    margem, largura_util = 36, doc.largura_pagina - 72
    direita = margem + largura_util
    y = 0
    pagina = [0]

    def cabecalho():
        nonlocal y
        pagina[0] += 1
        doc.texto(margem, 40, "LALUR — Livro de Apuração do Lucro Real", 13, negrito=True)
        doc.texto(direita, 40, f"Exercício {ano}", 11, negrito=True, alinhar="direita")
        doc.texto(margem, 56, empresa.razao_social, 10)
        info = " · ".join(x for x in [f"Cód. {empresa.codigo}" if empresa.codigo else "",
                                       f"CNPJ {empresa.cnpj_formatado}", empresa.regime.nome] if x)
        doc.texto(margem, 69, info, 8.5, cinza=0.35)
        doc.linha(margem, 76, direita, 76, 1, 0.3)
        doc.texto(margem, doc.altura_pagina - 24,
                  f"Emitido em {date.today():%d/%m/%Y} pelo Controle de Rotina", 7.5, cinza=0.45)
        doc.texto(direita, doc.altura_pagina - 24, f"Página {pagina[0]}", 7.5, alinhar="direita", cinza=0.45)
        y = 96

    def espaco(altura):
        nonlocal y
        if y + altura > doc.altura_pagina - 44:
            doc.nova_pagina()
            cabecalho()

    def titulo(texto):
        nonlocal y
        espaco(40)
        doc.texto(margem, y, texto, 11, negrito=True)
        y += 10

    def tabela(cabecalhos, larguras, linhas, alinhar_numeros=True):
        """linhas: [(celulas, estilo)]; 1ª coluna texto, demais valores à direita."""
        nonlocal y
        alt = 14

        def topo():
            nonlocal y
            doc.faixa(margem, y, largura_util, alt, 0.85)
            x = margem
            for i, (c, w) in enumerate(zip(cabecalhos, larguras)):
                if i == 0 or not alinhar_numeros:
                    doc.texto(x + 4, y + 10, c, 8.5, negrito=True)
                else:
                    doc.texto(x + w - 4, y + 10, c, 8.5, negrito=True, alinhar="direita")
                x += w
            y += alt

        espaco(alt * 3)
        topo()
        for celulas, estilo in linhas:
            if y + alt > doc.altura_pagina - 44:
                doc.nova_pagina()
                cabecalho()
                topo()
            if estilo == "secao":
                doc.faixa(margem, y, largura_util, alt, 0.95)
                doc.texto(margem + 4, y + 10, celulas[0].upper(), 7.5, negrito=True, cinza=0.35)
            else:
                negrito = estilo in ("subtotal", "total")
                if estilo == "total":
                    doc.faixa(margem, y, largura_util, alt, 0.97)
                x = margem
                for i, (c, w) in enumerate(zip(celulas, larguras)):
                    if i == 0 or not alinhar_numeros:
                        doc.texto(x + 4, y + 10, c, 8.5, negrito=negrito)
                    else:
                        doc.texto(x + w - 4, y + 10, c, 8.5, negrito=negrito, alinhar="direita")
                    x += w
                doc.linha(margem, y + alt, direita, y + alt, 0.3, 0.8)
            y += alt
        y += 14

    cabecalho()
    # Parte A: uma coluna por período
    rot = largura_util * (0.42 if len(periodos) > 1 else 0.65)
    col = (largura_util - rot) / len(periodos)
    titulo("Parte A — Demonstração do lucro real e cálculo do IRPJ e da CSLL")
    linhas = []
    for rotulo, valor, estilo in LINHAS:
        if estilo == "secao":
            linhas.append(([rotulo], "secao"))
        else:
            linhas.append(([rotulo] + [_fmt(valor(d)) for _, d in periodos], estilo))
    tabela(["R$"] + [rotulo_periodo(p, curto=True) for p, _ in periodos],
           [rot] + [col] * len(periodos), linhas)

    # Adições e exclusões de cada período
    for p, d in periodos:
        itens = d.apuracao.lancamentos
        titulo(f"Adições e exclusões — {rotulo_periodo(p)}")
        if not itens:
            espaco(16)
            doc.texto(margem, y + 6, "Nenhuma adição ou exclusão lançada.", 8.5, cinza=0.4)
            y += 24
        else:
            larguras = [70, largura_util - 70 - 90 - 90, 90, 90]
            tabela(["Tipo", "Descrição", "Tributo", "Valor (R$)"], larguras,
                   [([LalurLancamento.TIPOS[l.tipo], l.descricao[:80],
                      LalurLancamento.TRIBUTOS[l.tributo], _fmt(l.valor)], "") for l in itens],
                   alinhar_numeros=False)
        if d.apuracao.observacao:
            espaco(16)
            doc.texto(margem, y + 6, f"Observação: {d.apuracao.observacao[:140]}", 8.5, cinza=0.3)
            y += 22
    return doc.gerar()


def _excel(empresa, ano, periodos):
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    negrito = Font(bold=True)
    fundo = PatternFill("solid", fgColor="D9E1F2")
    secao = PatternFill("solid", fgColor="F2F2F2")
    numero = "#,##0.00;-#,##0.00"

    def cabecalho(ws):
        ws.append(["LALUR — Livro de Apuração do Lucro Real", None, f"Exercício {ano}"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([empresa.razao_social])
        ws.append([f"Cód. {empresa.codigo or '-'} · CNPJ {empresa.cnpj_formatado} · {empresa.regime.nome}"])
        ws.append([])

    wb = Workbook()
    ws = wb.active
    ws.title = "Parte A"
    cabecalho(ws)
    ws.append(["R$"] + [rotulo_periodo(p, curto=True) for p, _ in periodos])
    for c in ws[ws.max_row]:
        c.font, c.fill = negrito, fundo
        c.alignment = Alignment(horizontal="center")
    for rotulo, valor, estilo in LINHAS:
        if estilo == "secao":
            ws.append([rotulo])
            for c in ws[ws.max_row][:1 + len(periodos)]:
                c.fill, c.font = secao, negrito
            continue
        ws.append([rotulo] + [valor(d) for _, d in periodos])
        for c in ws[ws.max_row][1:]:
            c.number_format = numero
        if estilo in ("subtotal", "total"):
            for c in ws[ws.max_row]:
                c.font = negrito
    ws.column_dimensions["A"].width = 42
    for i in range(len(periodos)):
        ws.column_dimensions[chr(ord("B") + i)].width = 16
    ws.freeze_panes = "B6"

    lanc = wb.create_sheet("Adições e exclusões")
    cabecalho(lanc)
    lanc.append(["Período", "Tipo", "Descrição", "Tributo", "Valor (R$)"])
    for c in lanc[lanc.max_row]:
        c.font, c.fill = negrito, fundo
    for p, d in periodos:
        for l in d.apuracao.lancamentos:
            lanc.append([rotulo_periodo(p), LalurLancamento.TIPOS[l.tipo], l.descricao,
                         LalurLancamento.TRIBUTOS[l.tributo], l.valor])
            lanc.cell(lanc.max_row, 5).number_format = numero
    for letra, w in zip("ABCDE", [14, 10, 50, 14, 16]):
        lanc.column_dimensions[letra].width = w
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue()


@bp.route("/<int:id>/<int:ano>/exportar")
def exportar(id, ano):
    """?periodo=todos (todos os apurados do exercício) ou 0-4; ?formato=pdf ou xlsx."""
    from flask import Response

    empresa = _empresa(id)
    if (r := _exige_lucro_real(empresa)):
        return r
    calc, _ = demonstrativos(empresa)
    do_ano = sorted(((p, d) for (a, p), d in calc.items() if a == ano), key=lambda x: x[0] or 5)
    escolha = request.args.get("periodo", "todos")
    periodos = do_ano if escolha == "todos" else [(p, d) for p, d in do_ano if str(p) == escolha]
    if not periodos:
        flash("Não há período apurado para exportar (informe o lucro e salve a apuração).", "warning")
        return redirect(url_for("lalur.empresa", id=id, ano=ano))
    if request.args.get("formato") == "xlsx":
        conteudo = _excel(empresa, ano, periodos)
        tipo, extensao = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    else:
        conteudo = _pdf(empresa, ano, periodos)
        tipo, extensao = "application/pdf", "pdf"
    nome = _nome_arquivo(empresa, ano, periodos, extensao)
    return Response(conteudo, mimetype=tipo,
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# ---------------------------------------------------------------- dados para o DARF

@bp.route("/<int:id>/<int:ano>/<int:periodo>/guia")
def guia(id, ano, periodo):
    """Quota única ou parcelado: quotas, vencimentos, juros e campos do DARF (tela e PDF)."""
    from flask import Response

    from . import guia_darf

    empresa = _empresa(id)
    if (r := _exige_lucro_real(empresa)):
        return r
    periodo = _periodo(periodo)
    calc, _ = demonstrativos(empresa)
    d = calc.get((ano, periodo))
    if d is None or (d.irpj_a_pagar <= 0 and d.csll_a_pagar <= 0):
        flash("Não há IRPJ nem CSLL a pagar neste período.", "warning")
        return _voltar_periodo(id, ano, periodo)
    a = request.args
    anual = periodo == 0
    forma = "unica" if anual or a.get("forma") != "parcelado" else "parcelado"
    try:
        parcelas = 1 if forma == "unica" else int(a.get("parcelas", "3"))
    except ValueError:
        parcelas = 3
    try:
        selic = parse_valor(a.get("selic"))
    except ValueError:
        selic = None
        flash("Selic inválida: informe o percentual, como 1,05.", "warning")
    padrao = guia_darf.CODIGOS["anual" if anual else "trimestral"]
    codigos = {t: (a.get(f"cod_{t}") or padrao[t]).strip()[:6] for t in ("irpj", "csll")}
    guias, avisos = [], []
    for tributo, chave, valor in (("IRPJ", "irpj", d.irpj_a_pagar), ("CSLL", "csll", d.csll_a_pagar)):
        lista, aviso = guia_darf.quotas(valor, ano, periodo, parcelas, selic)
        if lista:
            guias.append((tributo, codigos[chave], lista))
        if aviso:
            avisos.append(f"{tributo}: {aviso}")
    if a.get("baixar"):
        conteudo = guia_darf.pdf(empresa, ano, periodo, guias, forma)
        nome = (f"darf_dados_{empresa.codigo or empresa.id}_{ano}_"
                f"{'anual' if anual else f'{periodo}tri'}_{forma}.pdf")
        return Response(conteudo, mimetype="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})
    return render_template(
        "lalur/guia.html", empresa=empresa, ano=ano, periodo=periodo, rotulo=rotulo_periodo(periodo),
        d=d, forma=forma, parcelas=parcelas, selic=selic, codigos=codigos, guias=guias,
        avisos=avisos, anual=anual, apuracao=guia_darf.fim_do_periodo(ano, periodo),
        sicalc=guia_darf.SICALC,
    )

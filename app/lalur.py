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
    colunas = [{"periodo": p, "rotulo": "Anual" if p == 0 else f"{p}º trim.",
                "apuracao": existentes.get(p), "d": calc.get((ano, p))} for p in periodos]
    abertura = LalurSaldoInicial.query.filter_by(empresa_id=empresa.id).first()
    return render_template("lalur/empresa.html", empresa=empresa, ano=ano, modo=modo,
                           modo_fixo=modo_fixo, colunas=colunas, abertura=abertura)


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
    rotulo = "Anual" if periodo == 0 else f"{periodo}º trimestre"
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

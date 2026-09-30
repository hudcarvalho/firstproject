"""Telas do sistema.

Cadastros compartilhados (clientes, regimes, responsáveis, módulos) ficam em URLs próprias.
Tudo que é da rotina de uma área fica sob o código do módulo: /contabil/, /contabil/obrigacoes,
/empresas/<id>/contabil… Ao ativar um novo módulo (Fiscal, DP, Paralegal) as mesmas telas
passam a atendê-lo.
"""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from .competencia import cnpj_valido, parse_competencia, so_digitos
from .models import (
    ESFERAS, PERIODICIDADES, Empresa, EmpresaObrigacaoAjuste, Entrega, Modulo, Obrigacao,
    RegimeTributario, Responsavel, db,
)

bp = Blueprint("main", __name__)


def _get(model, id_):
    obj = db.session.get(model, id_)
    if obj is None:
        abort(404)
    return obj


def _modulo(codigo):
    """Módulo ativo pelo código da URL, ou 404."""
    m = Modulo.query.filter_by(codigo=codigo, ativo=True).first()
    if m is None:
        abort(404)
    return m


def _int_or_none(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _responsaveis_ativos():
    return Responsavel.query.filter_by(ativo=True).order_by(Responsavel.nome).all()


@bp.route("/")
def inicio():
    ativos = Modulo.ativos()
    if not ativos:
        return redirect(url_for("main.modulos_lista"))
    return redirect(url_for("main.painel", modulo=ativos[0].codigo))


# ---------------------------------------------------------------- Painel (por módulo)

@bp.route("/<modulo>/")
def painel(modulo):
    modulo = _modulo(modulo)
    responsavel = request.args.get("responsavel", "")  # "" = todos, "0" = sem responsável
    regime_id = _int_or_none(request.args.get("regime"))
    busca = (request.args.get("q") or "").strip()

    q = Empresa.query.filter_by(ativo=True)
    if regime_id:
        q = q.filter_by(regime_id=regime_id)
    if busca:
        like = f"%{busca}%"
        q = q.filter(
            Empresa.razao_social.ilike(like) | Empresa.nome_fantasia.ilike(like)
            | Empresa.cnpj.ilike(f"%{so_digitos(busca) or busca}%")
        )

    hoje = date.today()
    linhas = []
    for e in q.order_by(Empresa.razao_social):
        controle = e.controle(modulo)
        resp_id = controle.responsavel_id if controle else None
        if responsavel and (resp_id or 0) != _int_or_none(responsavel):
            continue
        situacao = e.situacao_obrigacoes(modulo, hoje)
        linhas.append({
            "empresa": e,
            "controle": controle,
            "atraso": controle.meses_atrasados(hoje) if controle else None,
            "pendentes": sum(1 for s in situacao if s["status"] == "pendente"),
            "total": len(situacao),
        })

    return render_template(
        "painel.html", modulo=modulo, linhas=linhas, responsaveis=_responsaveis_ativos(),
        regimes=RegimeTributario.query.order_by(RegimeTributario.nome).all(),
        filtros={"responsavel": responsavel, "regime": regime_id, "q": busca},
    )


# ---------------------------------------------------------------- Empresas (cadastro compartilhado)

@bp.route("/empresas")
def empresas_lista():
    mostrar_inativas = request.args.get("inativas") == "1"
    q = Empresa.query
    if not mostrar_inativas:
        q = q.filter_by(ativo=True)
    return render_template(
        "empresas/lista.html", empresas=q.order_by(Empresa.razao_social).all(),
        mostrar_inativas=mostrar_inativas, modulos=Modulo.ativos(),
    )


def _form_empresa(empresa):
    f = request.form
    erros = []
    cnpj = so_digitos(f.get("cnpj"))
    if not f.get("razao_social", "").strip():
        erros.append("Informe a razão social.")
    if not cnpj_valido(cnpj):
        erros.append("CNPJ inválido.")
    else:
        existente = Empresa.query.filter_by(cnpj=cnpj).first()
        if existente and existente.id != empresa.id:
            erros.append(f"CNPJ já cadastrado para {existente.razao_social}.")
    regime = db.session.get(RegimeTributario, _int_or_none(f.get("regime_id")) or 0)
    if regime is None:
        erros.append("Selecione a tributação.")

    empresa.razao_social = f.get("razao_social", "").strip()
    empresa.nome_fantasia = f.get("nome_fantasia", "").strip() or None
    empresa.cnpj = cnpj
    empresa.inscricao_estadual = f.get("inscricao_estadual", "").strip() or None
    empresa.inscricao_municipal = f.get("inscricao_municipal", "").strip() or None
    empresa.email = f.get("email", "").strip() or None
    empresa.telefone = f.get("telefone", "").strip() or None
    empresa.regime = regime
    empresa.observacoes = f.get("observacoes", "").strip() or None
    empresa.ativo = f.get("ativo") == "on"

    # Responsável e andamento por módulo ativo.
    for m in Modulo.ativos():
        controle = empresa.controle(m, criar=True)
        controle.responsavel_id = _int_or_none(f.get(f"responsavel_{m.codigo}"))
        bruto = f.get(f"concluido_{m.codigo}")
        controle.concluido_ate = parse_competencia(bruto)
        if bruto and controle.concluido_ate is None:
            erros.append(f"{m.nome}: competência inválida em “{m.rotulo_controle}”.")
    return erros


def _render_form_empresa(empresa):
    return render_template(
        "empresas/form.html", empresa=empresa, modulos=Modulo.ativos(),
        regimes=RegimeTributario.query.filter_by(ativo=True).order_by(RegimeTributario.nome).all(),
        responsaveis=_responsaveis_ativos(),
    )


def _salvar_form_empresa(empresa, nova):
    with db.session.no_autoflush:
        erros = _form_empresa(empresa)
    if not erros:
        if nova:
            db.session.add(empresa)
        db.session.commit()
        flash("Empresa cadastrada." if nova else "Empresa atualizada.", "success")
        return redirect(url_for("main.empresa_detalhe", id=empresa.id))
    for e in erros:
        flash(e, "danger")
    # Renderiza com o que foi digitado e descarta as alterações inválidas.
    with db.session.no_autoflush:
        html = _render_form_empresa(empresa)
    db.session.rollback()
    return html


@bp.route("/empresas/nova", methods=["GET", "POST"])
def empresa_nova():
    empresa = Empresa(ativo=True)
    if request.method == "POST":
        return _salvar_form_empresa(empresa, nova=True)
    return _render_form_empresa(empresa)


@bp.route("/empresas/<int:id>/editar", methods=["GET", "POST"])
def empresa_editar(id):
    empresa = _get(Empresa, id)
    if request.method == "POST":
        return _salvar_form_empresa(empresa, nova=False)
    return _render_form_empresa(empresa)


@bp.route("/empresas/<int:id>")
def empresa_detalhe(id):
    _get(Empresa, id)
    ativos = Modulo.ativos()
    if not ativos:
        return redirect(url_for("main.empresa_editar", id=id))
    return redirect(url_for("main.empresa_modulo", id=id, modulo=ativos[0].codigo))


# ---------------------------------------------------------------- Empresa dentro de um módulo

@bp.route("/empresas/<int:id>/<modulo>")
def empresa_modulo(id, modulo):
    empresa = _get(Empresa, id)
    modulo = _modulo(modulo)
    hoje = date.today()
    controle = empresa.controle(modulo)
    ajustes = [a for a in empresa.ajustes if a.obrigacao.modulo_id == modulo.id]
    ids_ajustados = {a.obrigacao_id for a in ajustes}
    do_regime = empresa.regime.obrigacoes_do_modulo(modulo)
    ids_regime = {o.id for o in do_regime}
    return render_template(
        "empresas/detalhe.html", empresa=empresa, modulo=modulo, modulos=Modulo.ativos(),
        hoje=hoje, controle=controle, ajustes=ajustes,
        atraso=controle.meses_atrasados(hoje) if controle else None,
        situacao=empresa.situacao_obrigacoes(modulo, hoje),
        entregas=empresa.entregas_do_modulo(modulo),
        obrigacoes_aplicaveis=empresa.obrigacoes_aplicaveis(modulo),
        podem_incluir=[o for o in modulo.obrigacoes
                       if o.ativo and o.id not in ids_regime and o.id not in ids_ajustados],
        podem_excluir=[o for o in do_regime if o.id not in ids_ajustados],
        responsaveis=_responsaveis_ativos(),
    )


@bp.post("/empresas/<int:id>/<modulo>/controle")
def empresa_controle(id, modulo):
    empresa = _get(Empresa, id)
    modulo = _modulo(modulo)
    comp = parse_competencia(request.form.get("concluido_ate"))
    if comp is None:
        flash("Competência inválida.", "danger")
    else:
        empresa.controle(modulo, criar=True).concluido_ate = comp
        db.session.commit()
        flash(f"{modulo.rotulo_controle} {comp:%m/%Y}.", "success")
    return redirect(url_for("main.empresa_modulo", id=id, modulo=modulo.codigo))


@bp.post("/empresas/<int:id>/<modulo>/ajustes")
def empresa_ajuste_novo(id, modulo):
    empresa = _get(Empresa, id)
    modulo = _modulo(modulo)
    tipo = request.form.get("tipo")
    obrigacao = db.session.get(Obrigacao, _int_or_none(request.form.get("obrigacao_id")) or 0)
    if tipo not in ("incluir", "excluir") or obrigacao is None or obrigacao.modulo_id != modulo.id:
        flash("Ajuste inválido.", "danger")
    else:
        db.session.add(EmpresaObrigacaoAjuste(empresa=empresa, obrigacao=obrigacao, tipo=tipo))
        try:
            db.session.commit()
            flash("Ajuste registrado.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Já existe um ajuste para essa obrigação.", "warning")
    return redirect(url_for("main.empresa_modulo", id=id, modulo=modulo.codigo))


@bp.post("/empresas/<int:id>/ajustes/<int:ajuste_id>/remover")
def empresa_ajuste_remover(id, ajuste_id):
    ajuste = _get(EmpresaObrigacaoAjuste, ajuste_id)
    if ajuste.empresa_id != id:
        abort(404)
    codigo = ajuste.obrigacao.modulo.codigo
    db.session.delete(ajuste)
    db.session.commit()
    flash("Ajuste removido.", "success")
    return redirect(url_for("main.empresa_modulo", id=id, modulo=codigo))


@bp.post("/empresas/<int:id>/<modulo>/entregas")
def entrega_nova(id, modulo):
    empresa = _get(Empresa, id)
    modulo = _modulo(modulo)
    f = request.form
    obrigacao = db.session.get(Obrigacao, _int_or_none(f.get("obrigacao_id")) or 0)
    comp = parse_competencia(f.get("competencia"))
    try:
        data_entrega = date.fromisoformat(f["data_entrega"]) if f.get("data_entrega") else date.today()
    except ValueError:
        data_entrega = None
    destino = redirect(url_for("main.empresa_modulo", id=id, modulo=modulo.codigo))
    if obrigacao is None or obrigacao.modulo_id != modulo.id or comp is None or data_entrega is None:
        flash("Preencha obrigação, competência e data corretamente.", "danger")
        return destino

    db.session.add(Entrega(
        empresa=empresa, obrigacao=obrigacao, competencia=comp, data_entrega=data_entrega,
        responsavel_id=_int_or_none(f.get("responsavel_id")),
        observacao=f.get("observacao", "").strip() or None,
    ))
    try:
        db.session.commit()
        flash(f"{obrigacao.nome} {comp:%m/%Y} registrada.", "success")
    except IntegrityError:
        db.session.rollback()
        flash(f"{obrigacao.nome} {comp:%m/%Y} já estava registrada.", "warning")
    return destino


@bp.post("/entregas/<int:id>/remover")
def entrega_remover(id):
    entrega = _get(Entrega, id)
    destino = url_for("main.empresa_modulo", id=entrega.empresa_id,
                      modulo=entrega.obrigacao.modulo.codigo)
    db.session.delete(entrega)
    db.session.commit()
    flash("Registro removido.", "success")
    return redirect(destino)


# ---------------------------------------------------------------- Obrigações (por módulo)

@bp.route("/<modulo>/obrigacoes")
def obrigacoes_lista(modulo):
    modulo = _modulo(modulo)
    return render_template("obrigacoes/lista.html", modulo=modulo, obrigacoes=modulo.obrigacoes)


@bp.route("/<modulo>/obrigacoes/nova", methods=["GET", "POST"], defaults={"id": None})
@bp.route("/<modulo>/obrigacoes/<int:id>/editar", methods=["GET", "POST"])
def obrigacao_form(modulo, id):
    modulo = _modulo(modulo)
    if id:
        obrigacao = _get(Obrigacao, id)
        if obrigacao.modulo_id != modulo.id:
            abort(404)
    else:
        obrigacao = Obrigacao(ativo=True, periodicidade="mensal", esfera="federal")
    regimes = RegimeTributario.query.order_by(RegimeTributario.nome).all()
    if request.method == "POST":
        f = request.form
        nome = f.get("nome", "").strip()
        existente = Obrigacao.query.filter_by(modulo_id=modulo.id, nome=nome).first()
        erros = []
        if not nome:
            erros.append("Informe o nome.")
        elif existente and existente.id != obrigacao.id:
            erros.append("Já existe uma obrigação com esse nome neste módulo.")
        if f.get("periodicidade") not in PERIODICIDADES:
            erros.append("Periodicidade inválida.")
        if f.get("esfera") not in ESFERAS:
            erros.append("Esfera inválida.")
        dia = _int_or_none(f.get("dia_vencimento"))
        if f.get("dia_vencimento") and not (dia and 1 <= dia <= 31):
            erros.append("Dia de vencimento deve estar entre 1 e 31.")
        if erros:
            for e in erros:
                flash(e, "danger")
        else:
            obrigacao.modulo = modulo
            obrigacao.nome = nome
            obrigacao.descricao = f.get("descricao", "").strip() or None
            obrigacao.periodicidade = f["periodicidade"]
            obrigacao.esfera = f["esfera"]
            obrigacao.dia_vencimento = dia
            obrigacao.ativo = f.get("ativo") == "on"
            ids = {int(x) for x in f.getlist("regimes")}
            obrigacao.regimes = [r for r in regimes if r.id in ids]
            if not id:
                db.session.add(obrigacao)
            db.session.commit()
            flash("Obrigação salva.", "success")
            return redirect(url_for("main.obrigacoes_lista", modulo=modulo.codigo))
    return render_template("obrigacoes/form.html", modulo=modulo, obrigacao=obrigacao, regimes=regimes)


@bp.route("/<modulo>/matriz", methods=["GET", "POST"])
def matriz(modulo):
    """Parametrização das obrigações do módulo por tipo de tributação (grade de checkboxes)."""
    modulo = _modulo(modulo)
    regimes = RegimeTributario.query.order_by(RegimeTributario.nome).all()
    obrigacoes = modulo.obrigacoes
    if request.method == "POST":
        marcados = set(request.form.getlist("vinculo"))  # "regimeId-obrigacaoId"
        for r in regimes:
            # Preserva os vínculos de outros módulos.
            outros = [o for o in r.obrigacoes if o.modulo_id != modulo.id]
            r.obrigacoes = outros + [o for o in obrigacoes if f"{r.id}-{o.id}" in marcados]
        db.session.commit()
        flash("Parametrização salva.", "success")
        return redirect(url_for("main.matriz", modulo=modulo.codigo))
    vinculos = {(r.id, o.id) for r in regimes for o in r.obrigacoes}
    return render_template(
        "regimes/matriz.html", modulo=modulo, regimes=regimes, obrigacoes=obrigacoes,
        vinculos=vinculos,
    )


# ---------------------------------------------------------------- Regimes

@bp.route("/regimes")
def regimes_lista():
    return render_template(
        "regimes/lista.html", regimes=RegimeTributario.query.order_by(RegimeTributario.nome).all(),
        modulos=Modulo.ativos(),
    )


@bp.route("/regimes/novo", methods=["GET", "POST"], defaults={"id": None})
@bp.route("/regimes/<int:id>/editar", methods=["GET", "POST"])
def regime_form(id):
    regime = _get(RegimeTributario, id) if id else RegimeTributario(ativo=True)
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        existente = RegimeTributario.query.filter_by(nome=nome).first()
        if not nome:
            flash("Informe o nome.", "danger")
        elif existente and existente.id != regime.id:
            flash("Já existe um regime com esse nome.", "danger")
        else:
            regime.nome = nome
            regime.descricao = request.form.get("descricao", "").strip() or None
            regime.ativo = request.form.get("ativo") == "on"
            if not id:
                db.session.add(regime)
            db.session.commit()
            flash("Regime salvo.", "success")
            return redirect(url_for("main.regimes_lista"))
    return render_template("regimes/form.html", regime=regime)


# ---------------------------------------------------------------- Responsáveis

@bp.route("/responsaveis")
def responsaveis_lista():
    return render_template(
        "responsaveis/lista.html", modulos=Modulo.ativos(),
        responsaveis=Responsavel.query.order_by(Responsavel.nome).all(),
    )


@bp.route("/responsaveis/novo", methods=["GET", "POST"], defaults={"id": None})
@bp.route("/responsaveis/<int:id>/editar", methods=["GET", "POST"])
def responsavel_form(id):
    resp = _get(Responsavel, id) if id else Responsavel(ativo=True)
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Informe o nome.", "danger")
        else:
            resp.nome = nome
            resp.email = request.form.get("email", "").strip() or None
            resp.ativo = request.form.get("ativo") == "on"
            if not id:
                db.session.add(resp)
            db.session.commit()
            flash("Responsável salvo.", "success")
            return redirect(url_for("main.responsaveis_lista"))
    return render_template("responsaveis/form.html", resp=resp)


# ---------------------------------------------------------------- Módulos

@bp.route("/modulos")
def modulos_lista():
    return render_template("modulos/lista.html", modulos=Modulo.query.order_by(Modulo.ordem).all())


@bp.route("/modulos/<int:id>/editar", methods=["GET", "POST"])
def modulo_form(id):
    modulo = _get(Modulo, id)
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        rotulo = request.form.get("rotulo_controle", "").strip()
        if not nome or not rotulo:
            flash("Informe o nome e o rótulo do controle.", "danger")
        else:
            modulo.nome = nome
            modulo.rotulo_controle = rotulo
            modulo.ativo = request.form.get("ativo") == "on"
            db.session.commit()
            flash("Módulo salvo.", "success")
            return redirect(url_for("main.modulos_lista"))
    return render_template("modulos/form.html", modulo=modulo)

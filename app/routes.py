from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from .competencia import cnpj_valido, parse_competencia, so_digitos
from .models import (
    ESFERAS, PERIODICIDADES, Empresa, EmpresaObrigacaoAjuste, Entrega, Obrigacao,
    RegimeTributario, Responsavel, db,
)

bp = Blueprint("main", __name__)


def _get(model, id_):
    obj = db.session.get(model, id_)
    if obj is None:
        abort(404)
    return obj


def _int_or_none(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Painel

@bp.route("/")
def painel():
    responsavel_id = _int_or_none(request.args.get("responsavel"))
    regime_id = _int_or_none(request.args.get("regime"))
    busca = (request.args.get("q") or "").strip()

    q = Empresa.query.filter_by(ativo=True)
    if responsavel_id:
        q = q.filter_by(responsavel_id=responsavel_id)
    if regime_id:
        q = q.filter_by(regime_id=regime_id)
    if busca:
        like = f"%{busca}%"
        q = q.filter(
            Empresa.razao_social.ilike(like) | Empresa.nome_fantasia.ilike(like)
            | Empresa.cnpj.ilike(f"%{so_digitos(busca) or busca}%")
        )
    empresas = q.order_by(Empresa.razao_social).all()

    hoje = date.today()
    linhas = []
    for e in empresas:
        situacao = e.situacao_obrigacoes(hoje)
        linhas.append({
            "empresa": e,
            "atraso": e.meses_escrituracao_atrasada(hoje),
            "pendentes": sum(1 for s in situacao if s["status"] == "pendente"),
            "total": len(situacao),
        })

    return render_template(
        "painel.html", linhas=linhas,
        responsaveis=Responsavel.query.filter_by(ativo=True).order_by(Responsavel.nome).all(),
        regimes=RegimeTributario.query.order_by(RegimeTributario.nome).all(),
        filtros={"responsavel": responsavel_id, "regime": regime_id, "q": busca},
    )


# ---------------------------------------------------------------- Empresas

@bp.route("/empresas")
def empresas_lista():
    mostrar_inativas = request.args.get("inativas") == "1"
    q = Empresa.query
    if not mostrar_inativas:
        q = q.filter_by(ativo=True)
    return render_template(
        "empresas/lista.html", empresas=q.order_by(Empresa.razao_social).all(),
        mostrar_inativas=mostrar_inativas,
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
    if f.get("escriturada_ate") and parse_competencia(f.get("escriturada_ate")) is None:
        erros.append("Competência de escrituração inválida.")

    empresa.razao_social = f.get("razao_social", "").strip()
    empresa.nome_fantasia = f.get("nome_fantasia", "").strip() or None
    empresa.cnpj = cnpj
    empresa.inscricao_estadual = f.get("inscricao_estadual", "").strip() or None
    empresa.inscricao_municipal = f.get("inscricao_municipal", "").strip() or None
    empresa.email = f.get("email", "").strip() or None
    empresa.telefone = f.get("telefone", "").strip() or None
    empresa.regime = regime
    empresa.responsavel_id = _int_or_none(f.get("responsavel_id"))
    empresa.escriturada_ate = parse_competencia(f.get("escriturada_ate"))
    empresa.observacoes = f.get("observacoes", "").strip() or None
    empresa.ativo = f.get("ativo") == "on"
    return erros


def _render_form_empresa(empresa):
    return render_template(
        "empresas/form.html", empresa=empresa,
        regimes=RegimeTributario.query.filter_by(ativo=True).order_by(RegimeTributario.nome).all(),
        responsaveis=Responsavel.query.filter_by(ativo=True).order_by(Responsavel.nome).all(),
    )


@bp.route("/empresas/nova", methods=["GET", "POST"])
def empresa_nova():
    empresa = Empresa(ativo=True)
    if request.method == "POST":
        erros = _form_empresa(empresa)
        if not erros:
            db.session.add(empresa)
            db.session.commit()
            flash("Empresa cadastrada.", "success")
            return redirect(url_for("main.empresa_detalhe", id=empresa.id))
        for e in erros:
            flash(e, "danger")
        with db.session.no_autoflush:
            html = _render_form_empresa(empresa)
        db.session.rollback()
        return html
    return _render_form_empresa(empresa)


@bp.route("/empresas/<int:id>/editar", methods=["GET", "POST"])
def empresa_editar(id):
    empresa = _get(Empresa, id)
    if request.method == "POST":
        with db.session.no_autoflush:
            erros = _form_empresa(empresa)
        if not erros:
            db.session.commit()
            flash("Empresa atualizada.", "success")
            return redirect(url_for("main.empresa_detalhe", id=empresa.id))
        for e in erros:
            flash(e, "danger")
        # Renderiza com o que foi digitado e descarta as alterações inválidas.
        with db.session.no_autoflush:
            html = _render_form_empresa(empresa)
        db.session.rollback()
        return html
    return _render_form_empresa(empresa)


@bp.route("/empresas/<int:id>")
def empresa_detalhe(id):
    empresa = _get(Empresa, id)
    hoje = date.today()
    ids_ajustados = {a.obrigacao_id for a in empresa.ajustes}
    ids_regime = {o.id for o in empresa.regime.obrigacoes}
    todas = Obrigacao.query.filter_by(ativo=True).order_by(Obrigacao.nome).all()
    return render_template(
        "empresas/detalhe.html", empresa=empresa, hoje=hoje,
        situacao=empresa.situacao_obrigacoes(hoje),
        atraso=empresa.meses_escrituracao_atrasada(hoje),
        obrigacoes_aplicaveis=empresa.obrigacoes_aplicaveis(),
        podem_incluir=[o for o in todas if o.id not in ids_regime and o.id not in ids_ajustados],
        podem_excluir=[o for o in empresa.regime.obrigacoes if o.id not in ids_ajustados],
        responsaveis=Responsavel.query.filter_by(ativo=True).order_by(Responsavel.nome).all(),
    )


@bp.post("/empresas/<int:id>/escrituracao")
def empresa_escrituracao(id):
    empresa = _get(Empresa, id)
    comp = parse_competencia(request.form.get("escriturada_ate"))
    if comp is None:
        flash("Competência inválida.", "danger")
    else:
        empresa.escriturada_ate = comp
        db.session.commit()
        flash(f"Escrituração atualizada até {comp:%m/%Y}.", "success")
    return redirect(url_for("main.empresa_detalhe", id=id))


@bp.post("/empresas/<int:id>/ajustes")
def empresa_ajuste_novo(id):
    empresa = _get(Empresa, id)
    tipo = request.form.get("tipo")
    obrigacao = db.session.get(Obrigacao, _int_or_none(request.form.get("obrigacao_id")) or 0)
    if tipo not in ("incluir", "excluir") or obrigacao is None:
        flash("Ajuste inválido.", "danger")
    else:
        db.session.add(EmpresaObrigacaoAjuste(empresa=empresa, obrigacao=obrigacao, tipo=tipo))
        try:
            db.session.commit()
            flash("Ajuste registrado.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Já existe um ajuste para essa obrigação.", "warning")
    return redirect(url_for("main.empresa_detalhe", id=id))


@bp.post("/empresas/<int:id>/ajustes/<int:ajuste_id>/remover")
def empresa_ajuste_remover(id, ajuste_id):
    ajuste = _get(EmpresaObrigacaoAjuste, ajuste_id)
    if ajuste.empresa_id != id:
        abort(404)
    db.session.delete(ajuste)
    db.session.commit()
    flash("Ajuste removido.", "success")
    return redirect(url_for("main.empresa_detalhe", id=id))


@bp.post("/empresas/<int:id>/entregas")
def entrega_nova(id):
    empresa = _get(Empresa, id)
    f = request.form
    obrigacao = db.session.get(Obrigacao, _int_or_none(f.get("obrigacao_id")) or 0)
    comp = parse_competencia(f.get("competencia"))
    try:
        data_entrega = date.fromisoformat(f.get("data_entrega")) if f.get("data_entrega") else date.today()
    except ValueError:
        data_entrega = None
    if obrigacao is None or comp is None or data_entrega is None:
        flash("Preencha obrigação, competência e data corretamente.", "danger")
        return redirect(url_for("main.empresa_detalhe", id=id))

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
    return redirect(url_for("main.empresa_detalhe", id=id))


@bp.post("/entregas/<int:id>/remover")
def entrega_remover(id):
    entrega = _get(Entrega, id)
    empresa_id = entrega.empresa_id
    db.session.delete(entrega)
    db.session.commit()
    flash("Registro removido.", "success")
    return redirect(url_for("main.empresa_detalhe", id=empresa_id))


# ---------------------------------------------------------------- Obrigações

@bp.route("/obrigacoes")
def obrigacoes_lista():
    return render_template(
        "obrigacoes/lista.html", obrigacoes=Obrigacao.query.order_by(Obrigacao.nome).all()
    )


@bp.route("/obrigacoes/nova", methods=["GET", "POST"], defaults={"id": None})
@bp.route("/obrigacoes/<int:id>/editar", methods=["GET", "POST"])
def obrigacao_form(id):
    obrigacao = _get(Obrigacao, id) if id else Obrigacao(ativo=True, periodicidade="mensal", esfera="federal")
    regimes = RegimeTributario.query.order_by(RegimeTributario.nome).all()
    if request.method == "POST":
        f = request.form
        nome = f.get("nome", "").strip()
        existente = Obrigacao.query.filter(Obrigacao.nome == nome).first()
        erros = []
        if not nome:
            erros.append("Informe o nome.")
        elif existente and existente.id != obrigacao.id:
            erros.append("Já existe uma obrigação com esse nome.")
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
            return redirect(url_for("main.obrigacoes_lista"))
    return render_template("obrigacoes/form.html", obrigacao=obrigacao, regimes=regimes)


# ---------------------------------------------------------------- Regimes / matriz

@bp.route("/regimes")
def regimes_lista():
    return render_template(
        "regimes/lista.html", regimes=RegimeTributario.query.order_by(RegimeTributario.nome).all()
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


@bp.route("/regimes/matriz", methods=["GET", "POST"])
def regimes_matriz():
    """Parametrização das obrigações por tipo de tributação (grade de checkboxes)."""
    regimes = RegimeTributario.query.order_by(RegimeTributario.nome).all()
    obrigacoes = Obrigacao.query.order_by(Obrigacao.nome).all()
    if request.method == "POST":
        marcados = set(request.form.getlist("vinculo"))  # "regimeId-obrigacaoId"
        for r in regimes:
            r.obrigacoes = [o for o in obrigacoes if f"{r.id}-{o.id}" in marcados]
        db.session.commit()
        flash("Parametrização salva.", "success")
        return redirect(url_for("main.regimes_matriz"))
    vinculos = {(r.id, o.id) for r in regimes for o in r.obrigacoes}
    return render_template(
        "regimes/matriz.html", regimes=regimes, obrigacoes=obrigacoes, vinculos=vinculos
    )


# ---------------------------------------------------------------- Responsáveis

@bp.route("/responsaveis")
def responsaveis_lista():
    return render_template(
        "responsaveis/lista.html", responsaveis=Responsavel.query.order_by(Responsavel.nome).all()
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

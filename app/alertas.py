"""Meus alertas: cada usuário cria os seus (texto, data e, se quiser, uma empresa). Só quem criou vê.
A partir da data, o alerta aparece no topo do sistema até ser marcado como concluído."""
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from . import acesso
from .models import Alerta, Empresa, db

bp = Blueprint("alertas", __name__, url_prefix="/alertas")


def pendentes_hoje(usuario=None):
    """Alertas do usuário com data até hoje e ainda não concluídos."""
    usuario = usuario or current_user
    return (Alerta.query.filter(Alerta.usuario_id == usuario.id, Alerta.concluido_em.is_(None),
                                Alerta.data <= date.today())
            .order_by(Alerta.data, Alerta.id).all())


def _meu(id_):
    alerta = db.session.get(Alerta, id_)
    if alerta is None or alerta.usuario_id != current_user.id:
        abort(404)  # alerta de outra pessoa: "não existe"
    return alerta


def _empresa_do_form():
    """Empresa escolhida na lista ("código — razão social"), se o usuário tiver acesso a ela."""
    texto = (request.form.get("empresa") or "").strip()
    if not texto:
        return None, None
    codigo, _, nome = texto.partition(" — ")
    consulta = acesso.filtrar(Empresa.query)
    empresa = None
    if nome:
        empresa = consulta.filter(Empresa.razao_social == nome.strip()).first()
    empresa = empresa or consulta.filter(Empresa.codigo == codigo.strip()).first() \
        or consulta.filter(Empresa.razao_social.ilike(texto)).first()
    return empresa, (None if empresa else f"Empresa “{texto}” não encontrada.")


def _voltar():
    destino = request.form.get("voltar") or ""
    if destino.startswith("/") and not destino.startswith("//"):
        return redirect(destino)
    return redirect(url_for("alertas.lista"))


@bp.route("/", methods=["GET", "POST"])
def lista():
    if request.method == "POST":
        texto = " ".join((request.form.get("texto") or "").split())[:500]
        try:
            quando = date.fromisoformat(request.form.get("data", ""))
        except ValueError:
            quando = None
        empresa, erro = _empresa_do_form()
        if not texto or quando is None or erro:
            flash(erro or "Escreva o alerta e escolha a data.", "danger")
        else:
            db.session.add(Alerta(usuario_id=current_user.id, texto=texto, data=quando,
                                  empresa_id=empresa.id if empresa else None,
                                  criado_em=datetime.now().replace(microsecond=0)))
            db.session.commit()
            flash(f"Alerta criado para {quando:%d/%m/%Y}.", "success")
        return _voltar()
    meus = Alerta.query.filter_by(usuario_id=current_user.id)
    abertos = meus.filter(Alerta.concluido_em.is_(None)).order_by(Alerta.data, Alerta.id).all()
    concluidos = meus.filter(Alerta.concluido_em.isnot(None)).order_by(Alerta.concluido_em.desc()).limit(50).all()
    empresas = acesso.filtrar(Empresa.query.filter_by(ativo=True)).order_by(Empresa.razao_social).all()
    empresa_inicial = None
    if request.args.get("empresa", type=int):
        e = db.session.get(Empresa, request.args.get("empresa", type=int))
        if e is not None and acesso.pode(e.id):
            empresa_inicial = e
    return render_template("alertas/lista.html", abertos=abertos, concluidos=concluidos, empresas=empresas,
                           hoje=date.today(), empresa_inicial=empresa_inicial)


@bp.post("/<int:id>/concluir")
def concluir(id):
    _meu(id).concluido_em = datetime.now().replace(microsecond=0)
    db.session.commit()
    return _voltar()


@bp.post("/<int:id>/reabrir")
def reabrir(id):
    _meu(id).concluido_em = None
    db.session.commit()
    return _voltar()


@bp.post("/<int:id>/adiar")
def adiar(id):
    alerta = _meu(id)
    try:
        alerta.data = date.fromisoformat(request.form.get("data", ""))
        db.session.commit()
        flash(f"Alerta adiado para {alerta.data:%d/%m/%Y}.", "success")
    except ValueError:
        flash("Data inválida.", "danger")
    return _voltar()


@bp.post("/<int:id>/excluir")
def excluir(id):
    db.session.delete(_meu(id))
    db.session.commit()
    flash("Alerta excluído.", "success")
    return _voltar()

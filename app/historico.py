"""Tela do histórico de alterações — só para o dono do sistema (os demais recebem 404)."""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, render_template, request, send_file
from flask_login import current_user

from .models import RegistroAlteracao, Usuario, db

bp = Blueprint("historico", __name__, url_prefix="/historico")
POR_PAGINA = 200


@bp.before_request
def so_o_dono():
    if not (current_user.is_authenticated and current_user.dono):
        abort(404)


def _data(nome):
    try:
        return date.fromisoformat(request.args.get(nome, ""))
    except ValueError:
        return None


def _consulta():
    a = request.args
    q = RegistroAlteracao.query
    usuarios = [int(x) for x in a.get("usuario", "").split(",") if x.isdigit()]
    if usuarios:
        q = q.filter(RegistroAlteracao.usuario_id.in_(usuarios))
    acoes = [x for x in a.get("acao", "").split(",") if x in ("criou", "alterou", "apagou", "entrou")]
    if acoes:
        q = q.filter(RegistroAlteracao.acao.in_(acoes))
    if (empresa := (a.get("empresa") or "").strip()):
        q = q.filter(RegistroAlteracao.empresa_nome.ilike(f"%{empresa}%"))
    if (de := _data("de")):
        q = q.filter(RegistroAlteracao.quando >= datetime.combine(de, datetime.min.time()))
    if (ate := _data("ate")):
        q = q.filter(RegistroAlteracao.quando < datetime.combine(ate + timedelta(days=1), datetime.min.time()))
    return q.order_by(RegistroAlteracao.quando.desc(), RegistroAlteracao.id.desc())


@bp.route("/")
def lista():
    consulta = _consulta()
    if request.args.get("formato") == "xlsx":
        return _excel(consulta.limit(50000).all())
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    total = consulta.count()
    registros = consulta.offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA).all()
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    return render_template("historico/lista.html", registros=registros, total=total, pagina=pagina,
                           paginas=max(1, -(-total // POR_PAGINA)), usuarios=usuarios, args=request.args)


def _excel(registros):
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Histórico"
    ws.append(["Data/hora", "Usuário", "Ação", "O quê", "Empresa", "Detalhes"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in registros:
        ws.append([r.quando, r.usuario_nome, r.acao, r.tipo, r.empresa_nome, r.detalhes])
        ws.cell(ws.max_row, 1).number_format = "DD/MM/YYYY HH:MM"
        ws.cell(ws.max_row, 6).alignment = Alignment(wrap_text=True, vertical="top")
    for letra, largura in zip("ABCDEF", (17, 20, 10, 28, 40, 80)):
        ws.column_dimensions[letra].width = largura
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"historico_{date.today():%Y-%m-%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

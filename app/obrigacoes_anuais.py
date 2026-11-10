"""Aba Obrigações: todos os clientes em formato de planilha, com DEFIS, ECD, ECF, IBGE e
observação preenchidos direto na tabela (cada célula salva sozinha ao sair dela)."""
import re
from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from .competencia import fmt_documento
from .models import Empresa, ObrigacaoAnual, db

bp = Blueprint("obrigacoes_anuais", __name__, url_prefix="/obrigacoes")

COLUNAS = ["CÓDIGO", "EMPRESA", "CNPJ", "TRIBUTAÇÃO", "DEFIS", "ECD", "ECF", "IBGE", "OBSERVAÇÃO"]
CAMPOS = ObrigacaoAnual.CAMPOS_DATA + ("observacao",)


def _ano():
    try:
        ano = int(request.values.get("ano") or date.today().year)
    except ValueError:
        ano = date.today().year
    return ano if 2000 <= ano <= 2100 else date.today().year


def _ordem_codigo(e):
    c = (e.codigo or "").strip()
    return (0, int(c), "") if c.isdigit() else (1 if c else 2, 0, c.lower() or e.razao_social.lower())


def _dados(ano, inativas=False):
    q = Empresa.query
    if not inativas:
        q = q.filter(Empresa.ativo.is_(True))
    empresas = sorted(q.all(), key=lambda e: (_ordem_codigo(e), e.razao_social.lower()))
    registros = {r.empresa_id: r for r in ObrigacaoAnual.query.filter_by(ano=ano)}
    return empresas, registros


@bp.route("/")
def lista():
    ano = _ano()
    empresas, registros = _dados(ano)
    regimes = sorted({e.regime for e in empresas}, key=lambda r: r.nome.lower())
    return render_template("obrigacoes_anuais/lista.html", ano=ano, empresas=empresas, registros=registros,
                           regimes=regimes, colunas=COLUNAS, anos=range(date.today().year + 1, 2019, -1))


def _data(texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = datetime.strptime(texto, fmt).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError
    if not 2000 <= d.year <= 2100:
        raise ValueError
    return d


@bp.route("/salvar", methods=["POST"])
def salvar():
    """Salva uma célula: empresa_id, ano, campo (defis/ecd/ecf/ibge/observacao) e valor."""
    campo = request.form.get("campo")
    if campo not in CAMPOS:
        abort(400)
    empresa = db.session.get(Empresa, request.form.get("empresa_id", type=int) or 0)
    if empresa is None:
        abort(404)
    ano = _ano()
    valor = request.form.get("valor", "")
    if campo == "observacao":
        novo = re.sub(r"\s+", " ", valor).strip()[:255] or None
    else:
        try:
            novo = _data(valor)
        except ValueError:
            return jsonify(ok=False, erro="Data inválida. Use dd/mm/aaaa."), 400
    reg = ObrigacaoAnual.query.filter_by(empresa_id=empresa.id, ano=ano).first()
    if reg is None:
        if novo is None:
            return jsonify(ok=True)
        reg = ObrigacaoAnual(empresa_id=empresa.id, ano=ano)
        db.session.add(reg)
    setattr(reg, campo, novo)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/exportar")
def exportar():
    """Mesma tabela em Excel, com o cabeçalho da planilha do escritório."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    ano = _ano()
    empresas, registros = _dados(ano)
    wb = Workbook()
    ws = wb.active
    ws.title = f"Obrigações {ano}"
    ws.append(COLUNAS)
    fino = Side(style="thin", color="999999")
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9D9D9")
        c.border = Border(top=fino, bottom=fino, left=fino, right=fino)
    for e in empresas:
        r = registros.get(e.id)
        codigo = int(e.codigo) if (e.codigo or "").strip().isdigit() else e.codigo
        ws.append([codigo, e.razao_social, fmt_documento(e.cnpj), e.regime.nome.upper()]
                  + [getattr(r, c) if r else None for c in ObrigacaoAnual.CAMPOS_DATA]
                  + [r.observacao if r else None])
        for col in range(5, 9):
            ws.cell(ws.max_row, col).number_format = "DD/MM/YYYY"
    for letra, largura in zip("ABCDEFGHI", (9, 45, 20, 16, 12, 12, 12, 12, 40)):
        ws.column_dimensions[letra].width = largura
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in "EFGH":
        ws[f"{col}1"].alignment = Alignment(horizontal="center")
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"obrigacoes_{ano}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

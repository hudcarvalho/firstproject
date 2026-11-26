"""Aba Obrigações: todos os clientes em formato de planilha, com DEFIS, ECD, ECF, IBGE e
observação preenchidos direto na tabela (cada célula salva sozinha ao sair dela)."""
import re
from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for

from . import acesso
from .competencia import fmt_documento
from .models import Empresa, Modulo, ObrigacaoAnual, db

bp = Blueprint("obrigacoes_anuais", __name__, url_prefix="/obrigacoes")

COLUNAS = ["CÓDIGO", "EMPRESA", "CNPJ", "TRIBUTAÇÃO", "RESPONSÁVEL", "DEFIS", "ECD", "ECF", "IBGE", "OBSERVAÇÃO"]
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


def _modulo_responsavel():
    """Módulo de onde vem o responsável: o Contábil (ou o primeiro módulo ativo)."""
    ativos = Modulo.ativos()
    return next((m for m in ativos if m.codigo == "contabil"), ativos[0] if ativos else None)


def _responsavel(empresa, modulo):
    c = empresa.controle(modulo) if modulo else None
    return c.responsavel if c and c.responsavel else None


def _dados(ano, inativas=False):
    q = acesso.filtrar(Empresa.query)
    if not inativas:
        q = q.filter(Empresa.ativo.is_(True))
    empresas = sorted(q.all(), key=lambda e: (_ordem_codigo(e), e.razao_social.lower()))
    registros = {r.empresa_id: r for r in ObrigacaoAnual.query.filter_by(ano=ano)}
    return empresas, registros


@bp.route("/")
def lista():
    ano = _ano()
    empresas, registros = _dados(ano)
    regimes = sorted({e.regime for e in empresas if e.regime}, key=lambda r: r.nome.lower())
    modulo = _modulo_responsavel()
    responsavel = {e.id: _responsavel(e, modulo) for e in empresas}
    responsaveis = sorted({r for r in responsavel.values() if r}, key=lambda r: r.nome.lower())
    return render_template("obrigacoes_anuais/lista.html", ano=ano, empresas=empresas, registros=registros,
                           regimes=regimes, responsavel=responsavel, responsaveis=responsaveis, colunas=COLUNAS, anos=range(date.today().year + 1, 2019, -1))


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
    empresa = acesso.exigir(db.session.get(Empresa, request.form.get("empresa_id", type=int) or 0))
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
    modulo = _modulo_responsavel()
    for e in empresas:
        r = registros.get(e.id)
        resp = _responsavel(e, modulo)
        codigo = int(e.codigo) if (e.codigo or "").strip().isdigit() else e.codigo
        ws.append([codigo, e.razao_social, fmt_documento(e.cnpj), e.regime.nome.upper() if e.regime else None, resp.nome if resp else None]
                  + [getattr(r, c) if r else None for c in ObrigacaoAnual.CAMPOS_DATA]
                  + [r.observacao if r else None])
        for col in range(6, 10):
            ws.cell(ws.max_row, col).number_format = "DD/MM/YYYY"
    for letra, largura in zip("ABCDEFGHIJ", (9, 45, 20, 16, 18, 12, 12, 12, 12, 40)):
        ws.column_dimensions[letra].width = largura
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in "FGHI":
        ws[f"{col}1"].alignment = Alignment(horizontal="center")
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"obrigacoes_{ano}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- importar recibos de entrega

@bp.route("/importar", methods=["GET", "POST"])
def importar():
    """Recibos (PDFs ou .zip) → prévia com empresa, declaração e data; nada é gravado ainda.
    Os arquivos são lidos na hora e não ficam guardados no servidor."""
    from . import recibos

    if request.method == "GET":
        return render_template("obrigacoes_anuais/importar.html", previa=None, tipos=recibos.TIPOS)
    arquivos = recibos.arquivos_enviados(request.files.getlist("arquivos"))
    if not arquivos:
        flash("Escolha os recibos em PDF ou uma pasta compactada (.zip) com os PDFs.", "warning")
        return redirect(url_for("obrigacoes_anuais.importar"))
    empresas = {e.cnpj: e for e in acesso.filtrar(Empresa.query).all()}
    lidos = [recibos.ler_pdf(nome, conteudo) for nome, conteudo in arquivos]
    linhas = []
    for r in lidos:
        empresa = empresas.get(r.cnpj) if r.cnpj else None
        erro = r.erro or (None if empresa else "CNPJ não cadastrado no sistema")
        linhas.append({"r": r, "empresa": empresa, "erro": erro, "ano": r.data.year if r.data else None})
    # mesmo cliente e declaração mais de uma vez no lote: vale o recibo mais recente
    validas = [l for l in linhas if not l["erro"]]
    mais_recente = {}
    for l in validas:
        chave = (l["empresa"].id, l["r"].tipo, l["ano"])
        if chave not in mais_recente or l["r"].data > mais_recente[chave]["r"].data:
            mais_recente[chave] = l
    for l in validas:
        if mais_recente[(l["empresa"].id, l["r"].tipo, l["ano"])] is not l:
            l["erro"] = "há recibo mais recente desta declaração no lote"
    atuais = {(o.empresa_id, o.ano): o for o in ObrigacaoAnual.query.filter(
        ObrigacaoAnual.empresa_id.in_([l["empresa"].id for l in mais_recente.values()] or [0]))}
    for l in mais_recente.values():
        reg = atuais.get((l["empresa"].id, l["ano"]))
        l["atual"] = getattr(reg, l["r"].tipo) if reg else None
    linhas.sort(key=lambda l: (bool(l["erro"]), l["empresa"].razao_social if l["empresa"] else "", l["r"].tipo or ""))
    return render_template("obrigacoes_anuais/importar.html", previa=linhas, tipos=recibos.TIPOS,
                           validas=sum(1 for l in linhas if not l["erro"]))


@bp.post("/importar/confirmar")
def importar_confirmar():
    gravados, anos = 0, set()
    for item in request.form.getlist("item"):
        try:
            empresa_id, campo, data_iso = item.split("|")
            empresa_id, quando = int(empresa_id), date.fromisoformat(data_iso)
        except ValueError:
            continue
        if campo not in ObrigacaoAnual.CAMPOS_DATA or db.session.get(Empresa, empresa_id) is None \
                or not acesso.pode(empresa_id):
            continue
        reg = ObrigacaoAnual.query.filter_by(empresa_id=empresa_id, ano=quando.year).first()
        if reg is None:
            reg = ObrigacaoAnual(empresa_id=empresa_id, ano=quando.year)
            db.session.add(reg)
        setattr(reg, campo, quando)
        gravados += 1
        anos.add(quando.year)
    db.session.commit()
    flash(f"{gravados} data(s) de entrega gravada(s) a partir dos recibos.", "success")
    return redirect(url_for("obrigacoes_anuais.lista", ano=max(anos) if anos else None))

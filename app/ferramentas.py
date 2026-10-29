"""Ferramentas avulsas do escritório (ex.: converter PDF em Excel)."""
from io import BytesIO
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from .pdf_excel import MAX_PAGINAS, MODOS, ErroPDF, converter

bp = Blueprint("ferramentas", __name__, url_prefix="/ferramentas")


@bp.route("/pdf-excel", methods=["GET", "POST"])
def pdf_excel():
    """Recebe um PDF e devolve a planilha .xlsx. O arquivo não é guardado no servidor."""
    if request.method == "GET":
        return render_template("ferramentas/pdf_excel.html", modos=MODOS, max_paginas=MAX_PAGINAS)
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Escolha um arquivo PDF.", "warning")
        return redirect(url_for("ferramentas.pdf_excel"))
    conteudo = arquivo.read()
    if not conteudo.startswith(b"%PDF"):
        flash("O arquivo escolhido não é um PDF.", "danger")
        return redirect(url_for("ferramentas.pdf_excel"))
    modo = request.form.get("modo") if request.form.get("modo") in MODOS else "layout"
    try:
        planilha, paginas, linhas = converter(
            conteudo, modo=modo, aba_por_pagina=request.form.get("aba_por_pagina") == "on",
            converter_numeros=request.form.get("numeros") == "on")
    except ErroPDF as e:
        flash(str(e), "danger")
        return redirect(url_for("ferramentas.pdf_excel"))
    nome = Path(arquivo.filename).stem
    nome = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in nome).strip() or "convertido"
    resposta = send_file(BytesIO(planilha), as_attachment=True, download_name=f"{nome[:80]}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resposta.headers["X-Paginas"], resposta.headers["X-Linhas"] = str(paginas), str(linhas)
    return resposta

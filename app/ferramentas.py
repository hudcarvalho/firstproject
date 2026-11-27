"""Ferramentas avulsas do escritório (converter PDF em Excel, Excel em TXT)."""
from io import BytesIO
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from . import excel_txt as excel_txt_mod
from .ocr import MAX_PAGINAS_OCR, disponivel as ocr_disponivel, e_imagem
from .pdf_excel import (MAX_PAGINAS, MODOS, ErroPDF, converter, converter_imagem, converter_planilha, converter_varios,
                        e_planilha)

bp = Blueprint("ferramentas", __name__, url_prefix="/ferramentas")


@bp.route("/pdf-excel", methods=["GET", "POST"])
def pdf_excel():
    """Recebe um PDF (ou o extrato da Stone em Excel) e devolve a planilha .xlsx.
    O arquivo não é guardado no servidor."""
    if request.method == "GET":
        return render_template("ferramentas/pdf_excel.html", modos=MODOS, max_paginas=MAX_PAGINAS,
                               ocr=ocr_disponivel(), max_ocr=MAX_PAGINAS_OCR)
    enviados = [a for a in request.files.getlist("arquivo") if a and a.filename]
    if not enviados:
        flash("Escolha um arquivo PDF.", "warning")
        return redirect(url_for("ferramentas.pdf_excel"))
    if len(enviados) > 1:
        return _converter_varios(enviados)
    arquivo = enviados[0]
    conteudo = arquivo.read()
    eh_planilha = e_planilha(conteudo)
    if not conteudo.startswith(b"%PDF") and not eh_planilha and not e_imagem(conteudo):
        flash("O arquivo escolhido não é um PDF, uma imagem (JPG/PNG) nem uma planilha Excel.", "danger")
        return redirect(url_for("ferramentas.pdf_excel"))
    modo = request.form.get("modo") if request.form.get("modo") in MODOS else "auto"
    info = {}
    try:
        if eh_planilha:
            planilha, paginas, linhas = converter_planilha(conteudo)
        elif e_imagem(conteudo):
            planilha, paginas, linhas = converter_imagem(
                conteudo, converter_numeros=request.form.get("numeros") == "on", info=info)
        else:
            planilha, paginas, linhas = converter(
                conteudo, modo=modo, aba_por_pagina=request.form.get("aba_por_pagina") == "on",
                converter_numeros=request.form.get("numeros") == "on", info=info)
    except ErroPDF as e:
        flash(str(e), "danger")
        return redirect(url_for("ferramentas.pdf_excel"))
    nome = Path(arquivo.filename).stem
    nome = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in nome).strip() or "convertido"
    resposta = send_file(BytesIO(planilha), as_attachment=True, download_name=f"{nome[:80]}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resposta.headers["X-Paginas"], resposta.headers["X-Linhas"] = str(paginas), str(linhas)
    resposta.headers["X-OCR"] = str(info.get("ocr", 0))
    return resposta


def _nome_saida(filename, padrao):
    nome = Path(filename).stem
    return "".join(c if c.isalnum() or c in "-_ ." else "_" for c in nome).strip()[:80] or padrao


@bp.route("/excel-txt", methods=["GET", "POST"])
def excel_txt():
    """Planilha de lançamentos -> TXT de importação. O arquivo não é guardado no servidor."""
    codigo = (request.form.get("codigo") or excel_txt_mod.CODIGO_PADRAO).strip()
    if request.method == "GET":
        return render_template("ferramentas/excel_txt.html", codigo=codigo)
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Escolha uma planilha Excel.", "warning")
        return render_template("ferramentas/excel_txt.html", codigo=codigo)
    conteudo = arquivo.read()
    if not e_planilha(conteudo):
        flash("O arquivo escolhido não é uma planilha Excel (.xlsx ou .xls).", "danger")
        return render_template("ferramentas/excel_txt.html", codigo=codigo)
    if not codigo.isdigit():
        flash("O código deve ter apenas números.", "danger")
        return render_template("ferramentas/excel_txt.html", codigo=codigo)
    try:
        txt, linhas = excel_txt_mod.converter(conteudo, codigo=codigo)
    except excel_txt_mod.ErroPlanilha as e:
        flash(str(e), "danger")
        return render_template("ferramentas/excel_txt.html", codigo=codigo)
    resposta = send_file(BytesIO(txt), as_attachment=True,
                         download_name=f"{_nome_saida(arquivo.filename, 'lancamentos')}.txt", mimetype="text/plain")
    resposta.headers["X-Linhas"] = str(linhas)
    return resposta


def _converter_varios(enviados):
    """Vários arquivos → uma planilha só (extratos da mesma conta unidos; demais PDFs juntos)."""
    arquivos = []
    for a in enviados:
        conteudo = a.read()
        if not conteudo.startswith(b"%PDF") and not e_planilha(conteudo) and not e_imagem(conteudo):
            flash(f"“{a.filename}” não é um PDF, uma imagem (JPG/PNG) nem uma planilha Excel.", "danger")
            return redirect(url_for("ferramentas.pdf_excel"))
        arquivos.append((a.filename, conteudo))
    modo = request.form.get("modo") if request.form.get("modo") in MODOS else "auto"
    info = {}
    try:
        planilha, n, linhas = converter_varios(
            arquivos, modo=modo, converter_numeros=request.form.get("numeros") == "on",
            aba_por_arquivo=request.form.get("aba_por_arquivo") == "on", info=info)
    except ErroPDF as e:
        flash(str(e), "danger")
        return redirect(url_for("ferramentas.pdf_excel"))
    resposta = send_file(BytesIO(planilha), as_attachment=True, download_name=f"unificado_{n}_arquivos.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resposta.headers["X-Arquivos"], resposta.headers["X-Linhas"] = str(n), str(linhas)
    resposta.headers["X-OCR"] = str(info.get("ocr", 0))
    return resposta

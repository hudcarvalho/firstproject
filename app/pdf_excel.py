"""Conversão de PDF em planilha Excel.

Lê o texto do PDF com o pdfplumber; páginas escaneadas (sem texto) e fotos/imagens passam pelo
OCR gratuito do servidor (app.ocr, Tesseract). Monta as colunas de duas formas:
- "layout": usa o alinhamento do texto na página inteira para formar linhas e colunas (bom para
  relatórios contábeis sem bordas: balancetes, razões, DRE);
- "tabelas": só as tabelas desenhadas com linhas/bordas.
Valores no formato brasileiro (1.234,56, -1.234,56, (1.234,56), 1.234,56-) viram números.
"""
import re
from decimal import Decimal, InvalidOperation
from io import BytesIO

MAX_PAGINAS = 150
MODOS = {"auto": "Automático (reconhece extratos do Itaú, Bradesco, Santander, Caixa, Banco do Brasil, C6, Nubank, "
                 "Safra e BMP; nos demais, layout da página)",
         "layout": "Layout da página (relatórios, com ou sem bordas)",
         "tabelas": "Somente tabelas com linhas/bordas"}

_NUMERO = re.compile(r"^(?P<neg1>[-(])?\s*(?:R\$\s*)?(?P<num>\d{1,3}(?:\.\d{3})*,\d{1,4}|\d+,\d{1,4})\s*(?P<neg2>[-)])?\s*(?P<dc>[DC])?$")


class ErroPDF(Exception):
    """PDF que não pôde ser lido (inválido, protegido por senha, sem texto…)."""


def numero_br(texto):
    """'1.234,56' -> Decimal; '(1.234,56)', '-1.234,56' e '1.234,56-' -> negativo. Senão None."""
    if not texto:
        return None
    m = _NUMERO.match(texto.strip())
    if not m:
        return None
    try:
        valor = Decimal(m["num"].replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
    return -valor if (m["neg1"] or m["neg2"]) else valor


def _limpar(celula):
    if celula is None:
        return ""
    return re.sub(r"\s+", " ", str(celula)).strip()


def _segmentos_por_linha(page):
    return _segmentos(page.extract_words(x_tolerance=1.5, y_tolerance=2.5, keep_blank_chars=False,
                                         use_text_flow=False, extra_attrs=["size"]))


def _segmentos(palavras):
    """Palavras da página agrupadas em linhas; em cada linha, palavras próximas formam um trecho.

    Devolve [[(x0, x1, texto), ...], ...] de cima para baixo.
    """
    linhas = []
    for w in sorted(palavras, key=lambda w: (round(w["top"]), w["x0"])):
        meio = (w["top"] + w["bottom"]) / 2
        if linhas and abs(linhas[-1]["meio"] - meio) <= max(2.0, w["size"] * 0.35):
            linhas[-1]["palavras"].append(w)
        else:
            linhas.append({"meio": meio, "palavras": [w]})
    resultado = []
    for linha in linhas:
        segmentos = []
        for w in sorted(linha["palavras"], key=lambda w: w["x0"]):
            distancia = max(3.5, w["size"] * 0.75)  # espaço maior que ~3/4 de letra separa colunas
            if segmentos and w["x0"] - segmentos[-1][1] <= distancia:
                x0, _, texto = segmentos[-1]
                segmentos[-1] = (x0, w["x1"], texto + " " + w["text"])
            else:
                segmentos.append((w["x0"], w["x1"], w["text"]))
        resultado.append(segmentos)
    return resultado


def _faixas_de_colunas(linhas, largura_pagina):
    """Colunas = faixas horizontais ocupadas por texto nas linhas com mais de um trecho; os
    vãos verticais vazios ao longo da página separam uma coluna da outra."""
    multiplas = [l for l in linhas if len(l) > 1]
    if not multiplas:
        return []
    # as colunas vêm das linhas com cara de linha de tabela (quantidade típica de trechos);
    # títulos e rodapés com só dois pedaços não apagam os vãos entre colunas
    quantidades = sorted(len(l) for l in multiplas)
    mediana = quantidades[len(quantidades) // 2]
    base = [l for l in multiplas if len(l) >= mediana]
    if len(base) >= 2:
        multiplas = base
    passos = int(largura_pagina) + 2
    cobertura = [0] * passos
    for l in multiplas:
        for x0, x1, _ in l:
            if x1 - x0 > largura_pagina * 0.45:  # títulos e textos corridos não definem colunas
                continue
            for x in range(max(0, int(x0)), min(passos, int(x1) + 1)):
                cobertura[x] += 1
    # ignora poucas linhas fora do padrão (títulos, totais longos): ~5%, e ao menos 1 em tabelas maiores
    tolerancia = max(1 if len(multiplas) >= 8 else 0, len(multiplas) // 20)
    faixas, inicio = [], None
    for x, c in enumerate(cobertura + [0]):
        if c > tolerancia and inicio is None:
            inicio = x
        elif c <= tolerancia and inicio is not None:
            faixas.append((inicio, x))
            inicio = None
    return faixas


def _linhas_por_texto(page):
    """Todo o texto da página em linhas e colunas pelo alinhamento das palavras."""
    return _linhas_de_segmentos(_segmentos_por_linha(page), page.width)


def _linhas_de_palavras(palavras, largura):
    """Palavras lidas por OCR (já em pontos) -> linhas e colunas, como num PDF com texto."""
    return _linhas_de_segmentos(_segmentos(palavras), largura)


def _linhas_de_segmentos(linhas, largura):
    faixas = _faixas_de_colunas(linhas, largura)
    if len(faixas) < 2:
        return [[" ".join(t for _, _, t in l)] for l in linhas]

    def coluna(x):
        for i, (a, b) in enumerate(faixas):
            if a <= x <= b:
                return i
        return min(range(len(faixas)), key=lambda i: min(abs(x - faixas[i][0]), abs(x - faixas[i][1])))

    tabela = []
    for l in linhas:
        celulas = [""] * len(faixas)
        for x0, x1, texto in l:
            # linha com um só trecho (título, observação): vale onde o texto começa;
            # nas demais, o centro do trecho (valores costumam ser alinhados à direita)
            i = coluna(x0 if len(l) == 1 else (x0 + x1) / 2)
            celulas[i] = (celulas[i] + " " + texto).strip()
        tabela.append(celulas)
    return tabela


def _linhas_por_tabelas(page):
    linhas = []
    for tabela in page.extract_tables():
        if linhas:
            linhas.append([])  # linha em branco entre tabelas da mesma página
        linhas.extend(tabela)
    return linhas


def _precisa_ocr(page):
    """Página escaneada: quase nenhum caractere de texto, mas tem imagem."""
    return len(page.chars) < 15 and bool(page.images)


class _ContadorOCR:
    """Conta as páginas lidas por OCR numa conversão e aplica o limite."""

    def __init__(self):
        self.paginas = 0

    def linhas(self, conteudo_pdf, indice, nome=""):
        from . import ocr
        if not ocr.disponivel():
            raise ErroPDF((f"“{nome}”: " if nome else "") + "o arquivo é escaneado (imagem) e o reconhecimento de "
                          "texto (OCR) não está disponível no servidor.")
        self.paginas += 1
        if self.paginas > ocr.MAX_PAGINAS_OCR:
            raise ErroPDF(f"Há mais de {ocr.MAX_PAGINAS_OCR} páginas escaneadas (imagem) para ler por OCR, que é "
                          "lento. Divida os arquivos e converta por partes.")
        try:
            if indice is None:
                palavras, largura = ocr.palavras_da_imagem(conteudo_pdf)
            else:
                palavras, largura = ocr.palavras_da_pagina_pdf(conteudo_pdf, indice)
        except ocr.ErroOCR as e:
            raise ErroPDF((f"“{nome}”: " if nome else "") + str(e)) from e
        return _linhas_de_palavras(palavras, largura)


AVISO_OCR = ("Atenção: parte deste arquivo era imagem (escaneado/foto) e foi lida por reconhecimento de texto "
             "(OCR). Confira os valores com o documento original.")


def _sem_colunas_vazias(linhas):
    """Remove linhas vazias e colunas que ficaram vazias em todas as linhas."""
    linhas = [[_limpar(c) for c in l] for l in linhas]
    linhas = [l for l in linhas if any(l)]
    if not linhas:
        return []
    largura = max(len(l) for l in linhas)
    linhas = [l + [""] * (largura - len(l)) for l in linhas]
    usadas = [i for i in range(largura) if any(l[i] for l in linhas)]
    return [[l[i] for i in usadas] for l in linhas]


def _abrir_pdf(conteudo):
    """Abre o PDF no pdfplumber; se a estrutura estiver danificada (comum em PDFs gerados por alguns
    bancos), regrava o arquivo com o pdfium e tenta de novo."""
    import pdfplumber
    try:
        pdf = pdfplumber.open(BytesIO(conteudo))
        pdf.pages  # noqa: B018 - força a leitura da estrutura
        return pdf
    except Exception:
        import pypdfium2
        doc = pypdfium2.PdfDocument(conteudo)
        try:
            buf = BytesIO()
            doc.save(buf)
        finally:
            doc.close()
        return pdfplumber.open(BytesIO(buf.getvalue()))


def converter(conteudo, modo="auto", aba_por_pagina=False, converter_numeros=True, info=None):
    """PDF (bytes) -> (planilha .xlsx em bytes, nº de páginas, nº de linhas).

    No modo "auto", extrato mensal do Itaú vira a planilha organizada de app.extrato_itau
    (resumo conferido com o banco, extrato classificado e investimentos).
    Páginas escaneadas são lidas por OCR; `info["ocr"]` recebe quantas foram."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    try:
        pdf = _abrir_pdf(conteudo)
        paginas = pdf.pages
        total = len(paginas)
    except Exception as e:  # PDF inválido, corrompido ou protegido por senha
        raise ErroPDF("Não foi possível ler o arquivo. Confira se é um PDF válido e sem senha.") from e
    if total > MAX_PAGINAS:
        pdf.close()
        raise ErroPDF(f"O PDF tem {total} páginas; o limite é {MAX_PAGINAS}. Divida o arquivo e converta por partes.")

    if modo == "auto" and paginas and all(_precisa_ocr(p) for p in paginas):
        pdf.close()
        extratos, nao_reconhecidos, n = extratos_de_fotos([("arquivo.pdf", conteudo)])
        if extratos and not nao_reconhecidos:
            from .extrato_planilha import juntar, planilha
            if info is not None:
                info["ocr"] = n
            contas = {}
            for ex in extratos:
                contas.setdefault((ex.banco, ex.agencia, ex.conta), []).append(ex)
            if len(contas) == 1:
                ex = juntar(extratos)
                return planilha(ex), total, len(ex.movimentos)
        pdf = _abrir_pdf(conteudo)
        paginas = pdf.pages
    if modo == "auto":
        from . import (extrato_bb, extrato_bmp, extrato_bradesco, extrato_c6, extrato_caixa, extrato_itau,
                       extrato_itau_conta, extrato_itau_periodo, extrato_nubank, extrato_safra, extrato_santander)
        from .extrato_planilha import planilha
        leitor = None
        for reconhece, ler in ((extrato_itau.e_extrato_itau, extrato_itau.ler),
                               (extrato_itau_periodo.e_extrato_itau_periodo, extrato_itau_periodo.ler),
                               (extrato_itau_conta.e_extrato_itau_conta, extrato_itau_conta.ler),
                               (extrato_bradesco.e_extrato_bradesco, extrato_bradesco.ler),
                               (extrato_santander.e_extrato_santander, extrato_santander.ler),
                               (extrato_caixa.e_extrato_caixa, extrato_caixa.ler),
                               (extrato_bb.e_extrato_bb, extrato_bb.ler),
                               (extrato_c6.e_extrato_c6, extrato_c6.ler),
                               (extrato_nubank.e_extrato_nubank, extrato_nubank.ler),
                               (extrato_safra.e_extrato_safra, extrato_safra.ler),
                               (extrato_bmp.e_extrato_bmp, extrato_bmp.ler)):
            try:
                if reconhece(pdf):
                    leitor = ler
                    break
            except Exception:
                pass
        if leitor:
            try:
                ex = leitor(pdf)
            finally:
                pdf.close()
            if ex.movimentos:
                return planilha(ex), total, len(ex.movimentos)
            pdf = _abrir_pdf(conteudo)
            paginas = pdf.pages
    extrair = _linhas_por_tabelas if modo == "tabelas" else _linhas_por_texto
    wb = Workbook()
    ws = wb.active
    ws.title = "Página 1" if aba_por_pagina else "PDF"
    total_linhas = 0
    larguras = {}
    contador = _ContadorOCR()
    try:
        for n, page in enumerate(paginas, start=1):
            if aba_por_pagina and n > 1:
                ws = wb.create_sheet(f"Página {n}")
            if _precisa_ocr(page):
                linhas = _sem_colunas_vazias(contador.linhas(conteudo, n - 1))
            else:
                linhas = _sem_colunas_vazias(extrair(page))
            if not aba_por_pagina and linhas and ws.max_row > 1:
                ws.append([])
            for linha in linhas:
                valores = []
                for c in linha:
                    v = numero_br(c) if converter_numeros else None
                    valores.append(v if v is not None else c)
                ws.append(valores)
                r = ws.max_row
                for i, v in enumerate(valores, start=1):
                    if isinstance(v, Decimal):
                        ws.cell(r, i).number_format = "#,##0.00;-#,##0.00"
                    larguras[(ws.title, i)] = max(larguras.get((ws.title, i), 0), len(str(v)))
                total_linhas += 1
            page.flush_cache()
    finally:
        pdf.close()
    if info is not None:
        info["ocr"] = contador.paginas
    if total_linhas == 0:
        raise ErroPDF("Nenhum texto encontrado no PDF. Se escolheu “Somente tabelas”, tente “Layout da página”.")
    if contador.paginas:
        _marcar_ocr(wb.worksheets[0])
    from openpyxl.utils import get_column_letter
    for (aba, col), w in larguras.items():
        wb[aba].column_dimensions[get_column_letter(col)].width = min(max(w + 2, 8), 60)
    for planilha in wb.worksheets:
        planilha.freeze_panes = None
        if planilha.max_row == 1 and planilha.cell(1, 1).value is None:
            planilha.cell(1, 1, "(página sem texto)").font = Font(italic=True, color="888888")
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue(), total, total_linhas


def _todo_escaneado(conteudo):
    try:
        pdf = _abrir_pdf(conteudo)
        try:
            return bool(pdf.pages) and all(_precisa_ocr(p) for p in pdf.pages)
        finally:
            pdf.close()
    except Exception:
        return False


def _marcar_ocr(ws):
    from openpyxl.styles import Font, PatternFill
    ws.insert_rows(1)
    ws.cell(1, 1, AVISO_OCR).font = Font(bold=True, color="9C5700")
    ws.cell(1, 1).fill = PatternFill("solid", fgColor="FFEB9C")


def _imagens_para_extrato(arquivos):
    """[(nome, bytes)] -> [(nome, PIL.Image)] das fotos e páginas de PDF escaneado (candidatas a
    extrato bancário lido por OCR), na ordem enviada."""
    from PIL import Image
    from .ocr import e_imagem
    paginas = []
    for nome, conteudo in arquivos:
        if e_imagem(conteudo):
            try:
                img = Image.open(BytesIO(conteudo))
                img.load()
            except Exception:
                continue
            paginas.append((nome, img))
        elif conteudo.startswith(b"%PDF"):
            try:
                pdf = _abrir_pdf(conteudo)
                escaneado = bool(pdf.pages) and all(_precisa_ocr(p) for p in pdf.pages)
                pdf.close()
            except Exception:
                continue
            if escaneado:
                import pypdfium2
                doc = pypdfium2.PdfDocument(conteudo)
                try:
                    for i in range(len(doc)):
                        paginas.append((nome, doc[i].render(scale=200 / 72).to_pil()))
                finally:
                    doc.close()
    return paginas


def extratos_de_fotos(arquivos):
    """Extratos bancários fotografados/escaneados (hoje: Extrato Consolidado Inteligente do Santander).
    Devolve ([Extrato], nomes dos arquivos com alguma página não reconhecida, nº de páginas lidas)."""
    from . import extrato_foto_santander, ocr
    paginas = _imagens_para_extrato(arquivos)
    if not paginas or not ocr.disponivel():
        return [], [nome for nome, _ in arquivos], 0
    if len(paginas) > extrato_foto_santander.MAX_PAGINAS:
        raise ErroPDF(f"Envie no máximo {extrato_foto_santander.MAX_PAGINAS} fotos/páginas escaneadas de extrato por "
                      "vez: a leitura por OCR é demorada. Divida e converta por partes.")
    try:
        extratos, sobras = extrato_foto_santander.ler_imagens([img for _, img in paginas])
    except ocr.ErroOCR as e:
        raise ErroPDF(str(e)) from e
    nao_reconhecidos = list(dict.fromkeys(paginas[i][0] for i in sobras))
    # agência e nome nem sempre são lidos em todas as fotos: completa pelos outros meses da mesma conta
    for ex in extratos:
        for outro in extratos:
            if outro.conta == ex.conta:
                ex.agencia = ex.agencia or outro.agencia
                ex.empresa = ex.empresa or outro.empresa
    return extratos, nao_reconhecidos, len(paginas)


def converter_imagem(conteudo, converter_numeros=True, info=None):
    """Foto/imagem (JPG, PNG…) -> (planilha .xlsx em bytes, 1, nº de linhas), lida por OCR.
    Foto de extrato reconhecido sai organizada (Resumo e Extrato conferidos com o banco)."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    from .extrato_planilha import juntar, planilha
    extratos, _, _ = extratos_de_fotos([("imagem", conteudo)])
    if extratos:
        if info is not None:
            info["ocr"] = 1
        ex = juntar(extratos)
        return planilha(ex), 1, len(ex.movimentos)
    linhas = _sem_colunas_vazias(_ContadorOCR().linhas(conteudo, None))
    if info is not None:
        info["ocr"] = 1
    if not linhas:
        raise ErroPDF("Nenhum texto encontrado na imagem. Tente uma foto mais nítida, de frente e bem iluminada.")
    wb = Workbook()
    ws = wb.active
    ws.title = "Imagem"
    larguras = {}
    for linha in linhas:
        valores = []
        for c in linha:
            v = numero_br(c) if converter_numeros else None
            valores.append(v if v is not None else c)
        ws.append(valores)
        for i, v in enumerate(valores, start=1):
            if isinstance(v, Decimal):
                ws.cell(ws.max_row, i).number_format = "#,##0.00;-#,##0.00"
            larguras[i] = max(larguras.get(i, 0), len(str(v)))
    for col, w in larguras.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 8), 60)
    _marcar_ocr(ws)
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue(), 1, len(linhas)


# ---------------------------------------------------------------- extratos em planilha (Stone)

def e_planilha(conteudo):
    """.xlsx (zip) ou .xls antigo (OLE)."""
    return conteudo[:2] == b"PK" or conteudo[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _linhas_planilha(conteudo):
    if conteudo[:2] == b"PK":
        from openpyxl import load_workbook
        ws = load_workbook(BytesIO(conteudo), data_only=True).worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    import xlrd
    sh = xlrd.open_workbook(file_contents=conteudo).sheet_by_index(0)
    return [sh.row_values(i) for i in range(sh.nrows)]


def converter_planilha(conteudo):
    """Extrato exportado em planilha (hoje: Stone) -> (planilha organizada, linhas lidas, movimentos)."""
    from . import extrato_stone
    from .extrato_planilha import planilha
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            linhas = _linhas_planilha(conteudo)
    except Exception as e:
        raise ErroPDF("Não foi possível ler a planilha. Confira se é um arquivo Excel válido.") from e
    if not extrato_stone.e_extrato_stone(linhas):
        raise ErroPDF("Planilha não reconhecida. Por enquanto, em Excel, só o extrato da Stone é organizado "
                      "automaticamente; os demais extratos devem ser enviados em PDF.")
    ex = extrato_stone.ler(linhas)
    if not ex.movimentos:
        raise ErroPDF("Nenhuma movimentação encontrada no extrato.")
    return planilha(ex), len(linhas) - 1, len(ex.movimentos)


# ---------------------------------------------------------------- vários arquivos numa planilha só

MAX_ARQUIVOS = 30


def _leitores_pdf():
    from . import (extrato_bb, extrato_bmp, extrato_bradesco, extrato_c6, extrato_caixa, extrato_itau,
                   extrato_itau_conta, extrato_itau_periodo, extrato_nubank, extrato_safra, extrato_santander)
    return ((extrato_itau.e_extrato_itau, extrato_itau.ler),
            (extrato_itau_periodo.e_extrato_itau_periodo, extrato_itau_periodo.ler),
            (extrato_itau_conta.e_extrato_itau_conta, extrato_itau_conta.ler),
            (extrato_bradesco.e_extrato_bradesco, extrato_bradesco.ler),
            (extrato_santander.e_extrato_santander, extrato_santander.ler),
            (extrato_caixa.e_extrato_caixa, extrato_caixa.ler),
            (extrato_bb.e_extrato_bb, extrato_bb.ler),
            (extrato_c6.e_extrato_c6, extrato_c6.ler),
            (extrato_nubank.e_extrato_nubank, extrato_nubank.ler),
            (extrato_safra.e_extrato_safra, extrato_safra.ler),
            (extrato_bmp.e_extrato_bmp, extrato_bmp.ler))


def _abrir_validando(conteudo, nome):
    try:
        pdf = _abrir_pdf(conteudo)
        total = len(pdf.pages)
    except Exception as e:
        raise ErroPDF(f"“{nome}”: não foi possível ler o arquivo. Confira se é um PDF válido e sem senha.") from e
    if total > MAX_PAGINAS:
        pdf.close()
        raise ErroPDF(f"“{nome}” tem {total} páginas; o limite é {MAX_PAGINAS}.")
    return pdf


def _extrato_do_arquivo(nome, conteudo):
    """Extrato reconhecido (PDF dos bancos ou planilha da Stone) ou None."""
    if e_planilha(conteudo):
        from . import extrato_stone
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                linhas = _linhas_planilha(conteudo)
        except Exception as e:
            raise ErroPDF(f"“{nome}”: não foi possível ler a planilha.") from e
        if not extrato_stone.e_extrato_stone(linhas):
            raise ErroPDF(f"“{nome}”: planilha não reconhecida (em Excel, só o extrato da Stone é organizado).")
        ex = extrato_stone.ler(linhas)
        return ex if ex.movimentos else None
    pdf = _abrir_validando(conteudo, nome)
    try:
        for reconhece, ler in _leitores_pdf():
            try:
                if reconhece(pdf):
                    ex = ler(pdf)
                    return ex if ex.movimentos else None
            except Exception:
                continue
        return None
    finally:
        pdf.close()


def _linhas_do_pdf(nome, conteudo, modo, converter_numeros, contador):
    from .ocr import e_imagem
    if e_imagem(conteudo):
        brutas = [contador.linhas(conteudo, None, nome)]
        return _numeros(brutas, converter_numeros)
    extrair = _linhas_por_tabelas if modo == "tabelas" else _linhas_por_texto
    pdf = _abrir_validando(conteudo, nome)
    brutas = []
    try:
        for i, page in enumerate(pdf.pages):
            brutas.append(contador.linhas(conteudo, i, nome) if _precisa_ocr(page) else extrair(page))
            page.flush_cache()
    finally:
        pdf.close()
    return _numeros(brutas, converter_numeros)


def _numeros(paginas, converter_numeros):
    linhas = []
    for pagina in paginas:
        for linha in _sem_colunas_vazias(pagina):
            valores = []
            for c in linha:
                v = numero_br(c) if converter_numeros else None
                valores.append(v if v is not None else c)
            linhas.append(valores)
    return linhas


def converter_varios(arquivos, modo="auto", converter_numeros=True, aba_por_arquivo=False, info=None):
    """[(nome, bytes)] -> (planilha .xlsx única em bytes, nº de arquivos, nº de linhas/lançamentos).

    Extratos da mesma conta (ex.: vários meses) viram um extrato só, com o Confere de ponta a ponta;
    contas diferentes ficam em abas próprias. Os demais PDFs vão para uma aba única (com a coluna
    "Arquivo") ou uma aba por arquivo."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    from .extrato_planilha import juntar, planilha

    if len(arquivos) > MAX_ARQUIVOS:
        raise ErroPDF(f"Envie no máximo {MAX_ARQUIVOS} arquivos de uma vez.")
    n_arquivos = len(arquivos)
    from .ocr import e_imagem
    contas, genericos = {}, []
    contador = _ContadorOCR()
    fotos_lidas = 0
    if modo == "auto":  # fotos/escaneados de extrato: lidos juntos (um mês pode ocupar várias fotos)
        extratos_foto, nao_reconhecidos, fotos_lidas = extratos_de_fotos(arquivos)
        if extratos_foto:
            for ex in extratos_foto:
                contas.setdefault((ex.banco, ex.agencia, ex.conta), []).append(ex)
            lidos = {nome for nome, c in arquivos if (e_imagem(c) or c.startswith(b"%PDF"))} - set(nao_reconhecidos)
            lidos = {nome for nome, c in arquivos if nome in lidos and (e_imagem(c) or _todo_escaneado(c))}
            arquivos = [(nome, c) for nome, c in arquivos if nome not in lidos]
        else:
            fotos_lidas = 0
    for nome, conteudo in arquivos:
        ex = (_extrato_do_arquivo(nome, conteudo)
              if (modo == "auto" and not e_imagem(conteudo)) or e_planilha(conteudo) else None)
        if ex is not None:
            contas.setdefault((ex.banco, ex.agencia, ex.conta), []).append(ex)
        else:
            antes = contador.paginas
            linhas = _linhas_do_pdf(nome, conteudo, modo, converter_numeros, contador)
            genericos.append((nome + (" (lido por OCR)" if contador.paginas > antes else ""), linhas))
    if info is not None:
        info["ocr"] = contador.paginas + fotos_lidas

    extratos = [juntar(lista) for lista in contas.values()]
    if len(extratos) == 1 and not genericos:
        return planilha(extratos[0]), n_arquivos, len(extratos[0].movimentos)

    wb = Workbook()
    padrao = wb.active
    usados = set()

    def unico(base, limite=31):
        base = "".join(c for c in base if c not in '[]:*?/\\')[:limite].strip() or "Arquivo"
        nome, n = base, 2
        while nome.casefold() in usados:
            nome = f"{base[:limite - len(str(n)) - 1]} {n}"
            n += 1
        usados.add(nome.casefold())
        return nome

    total = 0
    for ex in extratos:
        sufixo = " " + unico(f"{ex.banco} {ex.conta}".strip(), 14)
        planilha(ex, wb=wb, sufixo=sufixo)
        total += len(ex.movimentos)

    def escrever(ws, linhas, com_arquivo=None):
        larguras = {}
        for linha in linhas:
            valores = ([com_arquivo] if com_arquivo is not None else []) + linha
            ws.append(valores)
            r = ws.max_row
            for i, v in enumerate(valores, start=1):
                if isinstance(v, Decimal):
                    ws.cell(r, i).number_format = "#,##0.00;-#,##0.00"
                larguras[i] = max(larguras.get(i, 0), len(str(v if v is not None else "")))
        return larguras

    if genericos:
        if aba_por_arquivo:
            for nome, linhas in genericos:
                ws = wb.create_sheet(unico(nome.replace(" (lido por OCR)", "").rsplit(".", 1)[0]))
                larg = escrever(ws, linhas) if linhas else {}
                if not linhas:
                    ws.cell(1, 1, "(arquivo sem texto)").font = Font(italic=True, color="888888")
                elif nome.endswith(" (lido por OCR)"):
                    _marcar_ocr(ws)
                for col, w in larg.items():
                    ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 8), 60)
                total += len(linhas)
        else:
            ws = wb.create_sheet(unico("PDFs unificados"), 0)
            ws.append(["Arquivo"])
            ws.cell(1, 1).font = Font(bold=True)
            larg = {}
            for nome, linhas in genericos:
                for col, w in escrever(ws, linhas, com_arquivo=nome).items():
                    larg[col] = max(larg.get(col, 0), w)
                total += len(linhas)
            for col, w in larg.items():
                ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 8), 60)
            ws.freeze_panes = "B2"
            if contador.paginas:
                _marcar_ocr(ws)
                ws.freeze_panes = "B3"
    wb.remove(padrao)
    if total == 0:
        raise ErroPDF("Nenhum texto encontrado nos arquivos.")
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue(), n_arquivos, total

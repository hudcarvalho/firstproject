"""Reconhecimento de texto (OCR) gratuito com o Tesseract instalado no servidor.

Usado no conversor de PDF em Excel para PDFs escaneados (páginas sem texto) e fotos/imagens
(JPG, PNG…). Nada sai do servidor e não há cobrança: o Tesseract roda localmente, em português.
Devolve as palavras com a posição na página, no mesmo formato que o pdfplumber usa, para a montagem
de linhas e colunas ser a mesma dos PDFs com texto.
"""
import csv
import os
import shutil
import subprocess
import tempfile
from io import BytesIO

DPI = 300            # resolução usada para "fotografar" a página do PDF antes do OCR
LARGURA_A4 = 595.0   # largura de uma folha A4 em pontos: as imagens são trazidas para essa escala
MAX_PAGINAS_OCR = 25  # OCR é lento (alguns segundos por página): limite por conversão
TEMPO_LIMITE = 120   # segundos por página
CONFIANCA_MINIMA = 20  # palavras com confiança muito baixa costumam ser sujeira da digitalização

EXTENSOES_IMAGEM = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")


class ErroOCR(Exception):
    """Falha ao reconhecer o texto da imagem."""


def disponivel():
    return shutil.which("tesseract") is not None


def _idioma():
    """Português quando instalado (acentos e ç corretos); senão, o padrão do Tesseract."""
    try:
        r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30)
        langs = set((r.stdout + r.stderr).split())
    except Exception:
        return None
    if "por" in langs:
        return "por+eng" if "eng" in langs else "por"
    return None


_IDIOMA = []


def idioma():
    if not _IDIOMA:
        _IDIOMA.append(_idioma())
    return _IDIOMA[0]


def e_imagem(conteudo):
    """JPG, PNG, TIFF, BMP ou WEBP (pelos primeiros bytes do arquivo)."""
    return (conteudo[:3] == b"\xff\xd8\xff" or conteudo[:8] == b"\x89PNG\r\n\x1a\n"
            or conteudo[:4] in (b"II*\x00", b"MM\x00*") or conteudo[:2] == b"BM"
            or (conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP"))


def _preparar(imagem):
    """Tons de cinza e tamanho adequado: fotos pequenas são ampliadas, enormes são reduzidas."""
    from PIL import ImageOps
    imagem = ImageOps.exif_transpose(imagem)  # foto de celular deitada fica em pé
    imagem = imagem.convert("L")
    maior = max(imagem.size)
    if maior < 1800:
        f = 1800 / maior
        imagem = imagem.resize((round(imagem.width * f), round(imagem.height * f)))
    elif maior > 5000:
        f = 5000 / maior
        imagem = imagem.resize((round(imagem.width * f), round(imagem.height * f)))
    return imagem


def palavras(imagem, escala):
    """Imagem (PIL) -> palavras [{text, x0, x1, top, bottom, size}] em pontos (pixels / escala)."""
    if not disponivel():
        raise ErroOCR("O reconhecimento de texto (Tesseract) não está instalado no servidor.")
    with tempfile.TemporaryDirectory() as pasta:
        caminho = os.path.join(pasta, "pagina.png")
        imagem.save(caminho)
        comando = ["tesseract", caminho, "stdout", "--psm", "6"]
        if idioma():
            comando += ["-l", idioma()]
        comando += ["tsv"]
        try:
            r = subprocess.run(comando, capture_output=True, timeout=TEMPO_LIMITE,
                               env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        except subprocess.TimeoutExpired as e:
            raise ErroOCR("A leitura da imagem demorou demais. Tente uma imagem menor ou mais nítida.") from e
    if r.returncode != 0:
        raise ErroOCR("Não foi possível ler a imagem: " + r.stderr.decode("utf-8", "replace").strip()[:200])
    return ler_tsv(r.stdout.decode("utf-8", "replace"), escala)


def ler_tsv(texto, escala):
    """Saída TSV do Tesseract -> palavras no formato do pdfplumber."""
    resultado = []
    for linha in csv.DictReader(texto.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE):
        palavra = (linha.get("text") or "").strip()
        if linha.get("level") != "5" or not palavra:
            continue
        try:
            conf = float(linha["conf"])
            x, y, w, h = (int(linha[k]) for k in ("left", "top", "width", "height"))
        except (TypeError, ValueError, KeyError):
            continue
        if conf < CONFIANCA_MINIMA and not any(c.isdigit() for c in palavra):
            continue
        chave = tuple(linha.get(k) for k in ("page_num", "block_num", "par_num", "line_num"))
        resultado.append({"text": palavra, "x0": x / escala, "x1": (x + w) / escala,
                          "top": y / escala, "bottom": (y + h) / escala, "size": max(h / escala, 1.0),
                          "_linha": chave})
    # folha um pouco torta: as palavras da mesma linha (segundo o Tesseract) ficam com a mesma altura,
    # para a montagem das linhas não separar a descrição dos valores
    por_linha = {}
    for p in resultado:
        por_linha.setdefault(p.pop("_linha"), []).append(p)
    for grupo in por_linha.values():
        topo = sorted(p["top"] for p in grupo)[len(grupo) // 2]
        base = sorted(p["bottom"] for p in grupo)[len(grupo) // 2]
        for p in grupo:
            p["top"], p["bottom"] = topo, base
    return resultado


def palavras_da_pagina_pdf(conteudo_pdf, indice):
    """Página (0, 1, …) de um PDF escaneado -> (palavras em pontos, largura da página em pontos)."""
    import pypdfium2
    doc = pypdfium2.PdfDocument(conteudo_pdf)
    try:
        pagina = doc[indice]
        largura = pagina.get_width()
        imagem = pagina.render(scale=DPI / 72).to_pil()
    finally:
        doc.close()
    imagem = imagem.convert("L")
    return palavras(imagem, imagem.width / largura), largura


def palavras_da_imagem(conteudo):
    """Foto ou imagem (bytes) -> (palavras, largura) numa escala de folha A4."""
    from PIL import Image, UnidentifiedImageError
    try:
        imagem = Image.open(BytesIO(conteudo))
        imagem.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ErroOCR("Não foi possível abrir a imagem. Confira se é um JPG ou PNG válido.") from e
    imagem = _preparar(imagem)
    return palavras(imagem, imagem.width / LARGURA_A4), LARGURA_A4

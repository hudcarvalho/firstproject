"""Leitura de recibos de entrega (DEFIS, ECD, ECF e IBGE) para a aba Obrigações.

O nome do arquivo é ignorado: tipo, CNPJ e data da entrega vêm do conteúdo.
- DEFIS: "Declaração de Informações Socioeconômicas e Fiscais (DEFIS)" → "Data e Horário da
  Transmissão da Declaração".
- ECD / ECF (Sped): "RECIBO DE ENTREGA DE ESCRITURAÇÃO CONTÁBIL DIGITAL" / "... FISCAL DIGITAL"
  → "Escrituração recebida via Internet ... em dd/mm/aaaa às hh:mm:ss".
- IBGE: "Comprovante de Entrega de Pesquisa" (economicasnet) → "Data:" e "CNPJ:". Quando a página
  foi impressa sem texto (letras gravadas como desenho), cada letra é reconhecida comparando o
  desenho com um gabarito tirado do próprio modelo de comprovante (app/ibge_glifos.json).
"""
import ctypes
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

from .competencia import so_digitos

TIPOS = {"defis": "DEFIS", "ecd": "ECD", "ecf": "ECF", "ibge": "IBGE"}
MAX_ARQUIVOS = 500
MAX_PDF = 20 * 1024 * 1024  # por arquivo dentro do .zip
MAX_TOTAL = 300 * 1024 * 1024  # descompactado

_CNPJ = re.compile(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b")
_DATA = r"(\d{2}/\d{2}/\d{4})"


@dataclass
class Recibo:
    arquivo: str
    tipo: str | None = None
    cnpj: str | None = None
    data: date | None = None
    erro: str | None = None


def _data(texto):
    d, m, a = (int(x) for x in texto.split("/"))
    try:
        return date(a, m, d)
    except ValueError:
        return None


def ler_texto(texto):
    """(tipo, cnpj só dígitos, data) a partir do texto do recibo, ou None se não reconhecer."""
    t = re.sub(r"[ \t]+", " ", texto or "")
    sem_acento = t.upper()
    tipo = data = None
    if "DEFIS" in sem_acento and "RECIBO DE ENTREGA" in sem_acento:
        tipo = "defis"
        m = re.search(r"Transmiss.o da Declara..o\s*\n?\s*" + _DATA, t, flags=re.I)
        data = m and m[1]
    elif re.search(r"RECIBO DE ENTREGA DE ESCRITURA..O (CONT.BIL|FISCAL) DIGITAL", sem_acento):
        tipo = "ecd" if re.search(r"ESCRITURA..O CONT.BIL DIGITAL", sem_acento) else "ecf"
        m = re.search(r"\bem " + _DATA + r" .s \d{2}:\d{2}", t)
        data = m and m[1]
    elif "COMPROVANTE DE ENTREGA DE PESQUISA" in sem_acento:
        tipo = "ibge"
        m = re.search(r"Data:\s*" + _DATA, t)
        data = m and m[1]
    if not tipo:
        return None
    m = re.search(r"CNPJ[^\n]*\n?[^\d]*" + _CNPJ.pattern, t) if tipo != "ibge" else re.search(r"CNPJ:\s*" + _CNPJ.pattern, t)
    m = m or _CNPJ.search(t)
    return tipo, so_digitos(m[1]) if m else None, _data(data) if data else None


# ------------------------------------------------------------------ comprovante sem texto (IBGE)

_GABARITO = None


def _gabarito():
    global _GABARITO
    if _GABARITO is None:
        _GABARITO = json.loads((Path(__file__).with_name("ibge_glifos.json")).read_text())
    return _GABARITO


def _glifos_da_pagina(pagina):
    """Desenhos (paths) pequenos da página, um por letra, com posição e pontos."""
    import pypdfium2.raw as R

    altura = pagina.get_height()
    glifos = []
    for o in pagina.get_objects():
        if o.type != R.FPDF_PAGEOBJ_PATH:
            continue
        esq, base, dir_, topo = o.get_bounds()
        if topo - base >= 15 or dir_ - esq >= 20:  # bordas, linhas e caixas
            continue
        pontos = []
        for i in range(R.FPDFPath_CountSegments(o.raw)):
            seg = R.FPDFPath_GetPathSegment(o.raw, i)
            x, y = ctypes.c_float(), ctypes.c_float()
            R.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
            pontos.append((x.value, y.value))
        glifos.append({"l": esq, "r": dir_, "top": altura - topo, "bot": altura - base, "pontos": pontos})
    return glifos


def _linhas_de_glifos(glifos):
    linhas = []
    for g in sorted(glifos, key=lambda g: g["top"]):
        meio = (g["top"] + g["bot"]) / 2
        for linha in linhas:
            if linha["top"] - 1 <= meio <= linha["bot"] + 1:
                linha["g"].append(g)
                linha["top"], linha["bot"] = min(linha["top"], g["top"]), max(linha["bot"], g["bot"])
                break
        else:
            linhas.append({"top": g["top"], "bot": g["bot"], "g": [g]})
    for linha in linhas:
        linha["g"].sort(key=lambda g: g["l"])
    return sorted(linhas, key=lambda linha: linha["top"])


def _assinatura(glifo):
    """Pontos do desenho normalizados pelo tamanho (independe da posição e da escala)."""
    xs = [p[0] for p in glifo["pontos"]]
    ys = [p[1] for p in glifo["pontos"]]
    escala = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
    pts = []
    for x, y in glifo["pontos"]:
        pts += [round((x - min(xs)) / escala, 3), round((y - min(ys)) / escala, 3)]
    return len(glifo["pontos"]), pts


def _reconhecer(glifo):
    n, pts = _assinatura(glifo)
    melhor, distancia = "?", 0.06
    for letra, modelo in _gabarito().get(str(n), []):
        d = sum(abs(a - b) for a, b in zip(pts, modelo)) / len(pts)
        if d < distancia:
            melhor, distancia = letra, d
    return melhor


def texto_por_desenho(pagina):
    """Texto de uma página sem texto, reconhecendo as letras desenhadas (só o modelo do IBGE)."""
    linhas = []
    for linha in _linhas_de_glifos(_glifos_da_pagina(pagina)):
        partes, anterior = [], None
        for g in linha["g"]:
            if anterior is not None and g["l"] - anterior["r"] > 2.3:
                partes.append(" ")
            partes.append(_reconhecer(g))
            anterior = g
        linhas.append("".join(partes))
    return "\n".join(linhas)


# ------------------------------------------------------------------ arquivos

def ler_pdf(nome, conteudo):
    from .pdf_excel import _abrir_pdf

    rec = Recibo(nome)
    try:
        pdf = _abrir_pdf(conteudo)
        try:
            texto = "\n".join((p.extract_text() or "") for p in pdf.pages[:3])
        finally:
            pdf.close()
        lido = ler_texto(texto)
        if lido is None and len(texto.strip()) < 20:
            import pypdfium2
            doc = pypdfium2.PdfDocument(conteudo)
            try:
                lido = ler_texto(texto_por_desenho(doc[0]))
            finally:
                doc.close()
    except Exception:
        rec.erro = "não foi possível abrir o PDF"
        return rec
    if lido is None:
        rec.erro = "recibo não reconhecido (DEFIS, ECD, ECF ou IBGE)"
        return rec
    rec.tipo, rec.cnpj, rec.data = lido
    if not rec.cnpj:
        rec.erro = "CNPJ não encontrado no recibo"
    elif not rec.data:
        rec.erro = "data da entrega não encontrada no recibo"
    return rec


def arquivos_enviados(arquivos):
    """[(nome, bytes)] dos PDFs enviados, abrindo os .zip (com subpastas). Ignora o resto."""
    saida, total = [], 0
    for arq in arquivos:
        conteudo = arq.read()
        nome = arq.filename or "arquivo"
        if conteudo[:2] == b"PK":
            try:
                with zipfile.ZipFile(BytesIO(conteudo)) as z:
                    for info in z.infolist():
                        if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                            continue
                        if Path(info.filename).name.startswith(("._", "~")):
                            continue  # lixo do macOS / temporários
                        if info.file_size > MAX_PDF or total + info.file_size > MAX_TOTAL:
                            continue
                        total += info.file_size
                        saida.append((Path(info.filename).name, z.read(info)))
                        if len(saida) >= MAX_ARQUIVOS:
                            return saida
            except zipfile.BadZipFile:
                saida.append((nome, b""))
        elif conteudo.startswith(b"%PDF") or nome.lower().endswith(".pdf"):
            saida.append((nome, conteudo))
        if len(saida) >= MAX_ARQUIVOS:
            break
    return saida

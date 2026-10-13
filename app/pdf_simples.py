"""Gerador de PDF simples (texto, linhas e faixas), sem dependências externas.

Usa as fontes padrão Helvetica e Helvetica-Bold do PDF com codificação WinAnsi (cp1252),
que cobre os acentos do português. As larguras dos caracteres (métricas AFM da Adobe, em
milésimos do tamanho da fonte) permitem alinhar valores à direita.
"""
from datetime import datetime

A4 = (595.28, 841.89)

# Larguras por código cp1252 (0 a 255).
LARGURAS = {
    False: (
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556,
        556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722,
        722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667,
        944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222,
        222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260,
        334, 584, 350, 556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611,
        350, 350, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 350, 500, 667, 278,
        333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333,
        333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667,
        1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584,
        778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556,
        556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500,
        556, 500,
    ),
    True: (
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556,
        556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722,
        667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
        667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278,
        556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389,
        584, 350, 556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
        350, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 350, 500, 667, 278, 333,
        556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333,
        611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000,
        722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722,
        722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278,
        278, 278, 278, 611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
    ),
}


# Caracteres fora do cp1252 trocados por equivalentes (ex.: sinal de menos → hífen).
_TROCAS = str.maketrans({"\u2212": "-", "\u00a0": " "})


def _cp1252(s):
    return str(s).translate(_TROCAS).encode("cp1252", errors="replace")


def _texto_pdf(s):
    b = _cp1252(s)
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def largura(s, tamanho, negrito=False):
    tabela = LARGURAS[negrito]
    return sum(tabela[c] for c in _cp1252(s)) * tamanho / 1000


class Documento:
    """Páginas A4 com coordenadas a partir do canto superior esquerdo (y cresce para baixo)."""

    def __init__(self, titulo="", tamanho=A4):
        self.titulo = titulo
        self.largura_pagina, self.altura_pagina = tamanho
        self.paginas = []
        self.nova_pagina()

    def nova_pagina(self):
        self.paginas.append([])

    @property
    def _atual(self):
        return self.paginas[-1]

    def texto(self, x, y, s, tamanho=9, negrito=False, alinhar="esquerda", cinza=0):
        if s is None or s == "":
            return
        if alinhar == "direita":
            x -= largura(s, tamanho, negrito)
        elif alinhar == "centro":
            x -= largura(s, tamanho, negrito) / 2
        fonte = "F2" if negrito else "F1"
        yp = self.altura_pagina - y
        self._atual.append(b"%.3f g BT /%s %.2f Tf %.2f %.2f Td (%s) Tj ET" % (
            cinza, fonte.encode(), tamanho, x, yp, _texto_pdf(s)))

    def linha(self, x1, y1, x2, y2, espessura=0.5, cinza=0.6):
        h = self.altura_pagina
        self._atual.append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (
            cinza, espessura, x1, h - y1, x2, h - y2))

    def faixa(self, x, y, largura_, altura, cinza=0.93):
        """Retângulo preenchido; (x, y) é o canto superior esquerdo."""
        self._atual.append(b"%.3f g %.2f %.2f %.2f %.2f re f" % (
            cinza, x, self.altura_pagina - y - altura, largura_, altura))

    def gerar(self):
        objetos = []

        def novo(conteudo):
            objetos.append(conteudo)
            return len(objetos)

        catalogo = novo(None)
        raiz_paginas = novo(None)
        f1 = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        ids = []
        for comandos in self.paginas:
            fluxo = b"\n".join(comandos)
            conteudo = novo(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(fluxo), fluxo))
            ids.append(novo(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>" % (
                    raiz_paginas, self.largura_pagina, self.altura_pagina, f1, f2, conteudo)))
        objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % raiz_paginas
        objetos[raiz_paginas - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % i for i in ids), len(ids))
        info = novo(b"<< /Title (%s) /Producer (Controle de Rotina) /CreationDate (D:%s) >>" % (
            _texto_pdf(self.titulo), datetime.now().strftime("%Y%m%d%H%M%S").encode()))

        saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posicoes = []
        for i, obj in enumerate(objetos, start=1):
            posicoes.append(len(saida))
            saida += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
        inicio_xref = len(saida)
        saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
        for p in posicoes:
            saida += b"%010d 00000 n \n" % p
        saida += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objetos) + 1, catalogo, info, inicio_xref)
        return bytes(saida)

"""Planilha de lançamentos (Data | conta débito | conta crédito | Lançamento | Valor | Participante)
-> arquivo TXT de importação, uma linha por lançamento:

    sequência,data,débito,crédito,valor,código,histórico,,participante

Ex.: 1,02/01/2026,571,858,22.84,1006,IOF,,0
O valor sai sem sinal (negativo vira positivo), sem milhar e com ponto decimal (700 · 22.84 · 2658); vírgula no histórico
vira ponto (a vírgula separa os campos); participante vazio vira 0; linhas terminam em CRLF (padrão Windows dos sistemas contábeis).
"""
import re
import warnings
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from .pdf_excel import numero_br

CODIGO_PADRAO = "1006"


class ErroPlanilha(Exception):
    pass


def _linhas(conteudo):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if conteudo[:2] == b"PK":
            from openpyxl import load_workbook
            ws = load_workbook(BytesIO(conteudo), data_only=True, read_only=True).worksheets[0]
            return [list(r) for r in ws.iter_rows(values_only=True)]
        import xlrd
        livro = xlrd.open_workbook(file_contents=conteudo)
        sh = livro.sheet_by_index(0)
        linhas = []
        for i in range(sh.nrows):
            linha = []
            for c in sh.row(i):
                if c.ctype == xlrd.XL_CELL_DATE:
                    linha.append(xlrd.xldate_as_datetime(c.value, livro.datemode))
                elif c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    linha.append(None)
                else:
                    linha.append(c.value)
            linhas.append(linha)
        return linhas


def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def _data(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    t = _texto(v)
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?: .*)?", t)
    if m:
        return f"{int(m[1]):02d}/{int(m[2]):02d}/{m[3]}"
    return None


def _decimal(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return Decimal(str(v))
    t = _texto(v).replace("R$", "").strip()
    d = numero_br(t)
    if d is None:
        try:
            d = Decimal(t)
        except InvalidOperation:
            return None
    return d


def formatar_valor(d):
    """Decimal -> '22.84', '700', '2658', '22.8' (sem milhar, ponto decimal, sem zeros à direita)."""
    d = abs(d).quantize(Decimal("0.01"))
    t = f"{d:f}"
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def _colunas(linhas):
    """Acha o cabeçalho (célula "Data") e as colunas; sem cabeçalho, usa A a F."""
    for i, linha in enumerate(linhas[:30]):
        nomes = [_texto(c).lower() for c in linha]
        if "data" in nomes:
            d = nomes.index("data")
            def achar(prefixo, padrao):
                return next((j for j, n in enumerate(nomes) if n.startswith(prefixo)), padrao)
            return i + 1, {"data": d, "debito": d + 1, "credito": d + 2, "historico": achar("lan", d + 3),
                           "valor": achar("valor", d + 4), "participante": achar("partic", d + 5)}
    return 0, {"data": 0, "debito": 1, "credito": 2, "historico": 3, "valor": 4, "participante": 5}


def converter(conteudo, codigo=CODIGO_PADRAO):
    """Planilha (.xlsx/.xls em bytes) -> (TXT em bytes, nº de lançamentos)."""
    try:
        linhas = _linhas(conteudo)
    except Exception as e:
        raise ErroPlanilha("Não foi possível ler a planilha. Confira se é um arquivo Excel válido.") from e
    inicio, col = _colunas(linhas)
    codigo = _texto(codigo) or CODIGO_PADRAO
    saida, erros = [], []
    for n, linha in enumerate(linhas[inicio:], start=inicio + 1):
        def cel(nome):
            j = col[nome]
            return linha[j] if j < len(linha) else None
        data = _data(cel("data"))
        if not data:
            if any(_texto(c) for c in linha) and _texto(cel("valor")) and _texto(cel("historico")):
                erros.append(f"linha {n}: data inválida ({_texto(cel('data')) or 'vazia'})")
            continue
        valor = _decimal(cel("valor"))
        if valor is None:
            erros.append(f"linha {n}: valor inválido ({_texto(cel('valor')) or 'vazio'})")
            continue
        # a vírgula separa os campos do TXT: no histórico, vira ponto
        historico = _texto(cel("historico")).replace(",", ".")
        participante = _texto(cel("participante")) or "0"
        saida.append(",".join([str(len(saida) + 1), data, _texto(cel("debito")), _texto(cel("credito")),
                               formatar_valor(valor), codigo, historico, "", participante]))
    if erros:
        mais = f" (e mais {len(erros) - 5})" if len(erros) > 5 else ""
        raise ErroPlanilha("Corrija a planilha: " + "; ".join(erros[:5]) + mais + ".")
    if not saida:
        raise ErroPlanilha("Nenhum lançamento encontrado. A planilha precisa ter as colunas Data, conta débito, "
                           "conta crédito, Lançamento, Valor e Participante.")
    texto = "".join(l + "\r\n" for l in saida)
    return texto.encode("cp1252", errors="replace"), len(saida)

"""Extrato Consolidado Inteligente do Santander a partir de fotos ou PDF escaneado (OCR).

Cada página é lida três vezes pelo Tesseract: o texto (datas e históricos) e duas leituras só de
números nas colunas de valores. Os lançamentos são montados pela posição (o valor fica na altura
da primeira linha do histórico) e conferidos com o saldo do fim do dia e com o resumo do banco:
quando a conta não fecha, o sistema procura a troca de dígito típica do OCR (1↔4, 5↔8…) que faz o
saldo bater e corrige, deixando a célula amarela com um comentário para conferência.

As páginas de cada mês são agrupadas pelo resumo ("Saldo de Conta Corrente em …") e pelo mês do
cabeçalho; meses seguidos da mesma conta viram um extrato só (extrato_planilha.juntar).
"""
import re
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from statistics import median

from . import ocr
from .extrato_planilha import NOMES_MES, Extrato, Movimento, sem_acento
from .extrato_santander import _separar, _tipo

MESES = {sem_acento(m): i + 1 for i, m in enumerate(NOMES_MES)}
_MES_ANO = re.compile(r"(" + "|".join(MESES) + r")\s*/\s*(\d{4})")
# trocas mais comuns do OCR em algarismos
CONFUSAO = {"0": "896", "1": "47", "2": "7", "3": "85", "4": "19", "5": "683", "6": "58", "7": "12",
            "8": "6503", "9": "84"}


def _num(texto, sem_virgula=False):
    """'1.234,56-' / '14,153,28' / '0,00.' -> (Decimal positivo, termina com '-'). Com `sem_virgula`
    (coluna de valores), '266384' ou '1.22115' — vírgula pequena que o OCR perdeu — viram 2.663,84 e
    1.221,15: os valores do extrato sempre têm centavos."""
    t = texto.strip("“”\"'|!:;_~ ")
    neg = t.rstrip(".,").endswith("-")
    nucleo = t.strip("-.,")
    m = re.fullmatch(r"(\d[\d.,]*)[.,](\d{2})", nucleo)
    if not m and sem_virgula and re.fullmatch(r"\d{1,3}(?:\.\d{3})+\d{2}|\d{4,8}", nucleo):
        digitos = nucleo.replace(".", "")
        m = re.fullmatch(r"(\d+)(\d{2})", digitos)
    if not m:
        return None
    inteiro = re.sub(r"\D", "", m[1])
    if len(inteiro) > 9:
        return None
    return Decimal(inteiro + "." + m[2]), neg


def _br(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _meio(w):
    return (w["top"] + w["bottom"]) / 2


def _linhas(palavras, tolerancia):
    """Agrupa palavras em linhas pela altura (centro), da mais alta para a mais baixa."""
    linhas = []
    for w in sorted(palavras, key=_meio):
        m = _meio(w)
        if linhas and abs(linhas[-1]["y"] - m) <= tolerancia:
            linhas[-1]["ws"].append(w)
            linhas[-1]["y"] = median(_meio(p) for p in linhas[-1]["ws"])
        else:
            linhas.append({"y": m, "ws": [w]})
    for l in linhas:
        l["ws"].sort(key=lambda w: w["x0"])
        l["texto"] = " ".join(w["text"] for w in l["ws"])
        l["sem"] = sem_acento(l["texto"])
    return linhas


def _juntar_partidos(nums, distancia=45):
    """'10.193,' + '35-' lidos separados na mesma linha viram um número só."""
    nums = sorted(nums, key=lambda w: (round(_meio(w) / 10), w["x0"]))
    saida = []
    for w in nums:
        if (saida and abs(_meio(saida[-1]) - _meio(w)) < 12 and 0 <= w["x0"] - saida[-1]["x1"] < distancia
                and saida[-1]["text"].rstrip("-").endswith((",", ".")) and _num(saida[-1]["text"]) is None):
            p = saida[-1]
            saida[-1] = {**p, "text": p["text"] + w["text"], "x1": w["x1"],
                         "top": min(p["top"], w["top"]), "bottom": max(p["bottom"], w["bottom"])}
        else:
            saida.append(dict(w))
    return saida


# ---------------------------------------------------------------- leitura de uma página

def ler_pagina(imagem):
    """Imagem PIL da página -> dados da página (ou None se não for este extrato)."""
    img, angulo = ocr.preparar_foto(imagem)
    img_num, _ = ocr.preparar_foto(imagem, fino=True, angulo=angulo)
    largura, altura = img.size
    texto = [w for w in ocr.tsv(img, 6) if not _sujeira(w)]
    inclinacao = _inclinacao(texto, largura)
    _endireitar(texto, inclinacao)
    # segunda leitura do texto (modo esparso) cobre linhas que o modo de bloco pulou
    esparso = [w for w in ocr.tsv(img, 11) if not _sujeira(w)]
    _endireitar(esparso, inclinacao)
    for w in esparso:
        if not any(min(w["x1"], t["x1"]) - max(w["x0"], t["x0"]) > 0 and abs(_meio(w) - _meio(t)) < 12 for t in texto):
            texto.append(dict(w, linha=("esp",) + w["linha"]))
    altura_letra = median([w["bottom"] - w["top"] for w in texto if w["text"].isalpha() and len(w["text"]) > 3]
                          or [20])
    tol = altura_letra * 0.75

    # cabeçalho da movimentação: "Créditos" e "Débitos" lado a lado, na metade direita
    def letras(w):
        return re.sub(r"[^A-Z]", "", sem_acento(w["text"]).upper())

    def tem_cabecalho(ws):
        return any("BITO" in letras(w) and w["x0"] > largura * 0.45 for w in ws) or any(
            "DOCUMENT" in letras(w) for w in ws)


    # o OCR erra o cabeçalho com frequência ("jCrêditos", "DGbitOS"): basta um pedaço da palavra
    cred = [w for w in texto if ("REDIT" in letras(w) or letras(w).startswith("CREDI")) and w["x0"] > largura * 0.45]
    deb = [w for w in texto if "BITO" in letras(w) and w not in cred and w["x0"] > largura * 0.45]
    par = [(c, d) for c in cred for d in deb if abs(_meio(c) - _meio(d)) < altura_letra * 2 and d["x0"] > c["x1"]]
    doc = [w for w in texto if "DOCUMENT" in letras(w) and w["x0"] > largura * 0.3]
    descr = [w for w in texto if letras(w).startswith("DESCRI") and w["x0"] < largura * 0.3]
    c = d = None
    if par:
        c, d = min(par, key=lambda p: _meio(p[0]))
        topo_tabela = max(c["bottom"], d["bottom"])
    elif deb:
        d = min(deb, key=_meio)
        topo_tabela = d["bottom"]
    elif doc or descr:  # cabeçalho dos valores não lido: usa "Nº Documento" / "Descrição"
        topo_tabela = max(w["bottom"] for w in (doc or descr)[:1]) + altura_letra * 1.5
    else:
        return None
    doc = [w for w in doc if abs(_meio(w) - topo_tabela) < altura_letra * 6]
    descr = [w for w in descr if abs(_meio(w) - topo_tabela) < altura_letra * 6]
    lim_hist = (min(w["x0"] for w in doc) - 15) if doc else largura * 0.5
    lim_data = (descr[0]["x0"] - 12) if descr else largura * 0.075

    linhas = _linhas(texto, tol)
    fim_tabela = altura
    for l in linhas:
        if l["y"] > topo_tabela and any(k in l["sem"] for k in ("SALDOS POR", "SE SUA EMPRESA", "DESCONSIDERE",
                                                                  "DEBITO AUTOMATICO EM", "VALORES DEDUZIDOS")):
            fim_tabela = min(fim_tabela, l["y"] - tol)

    # três leituras dos valores (só números na faixa dos valores + números lidos no texto)
    x_faixa = int(max(0, lim_hist + 40))

    def deslocar(ws):
        return [dict(w, x0=w["x0"] + x_faixa, x1=w["x1"] + x_faixa) for w in ws]

    leituras = []
    for imagem_n in (img_num, img):
        faixa = imagem_n.crop((x_faixa, 0, largura, altura))
        for psm in (11, 6):
            ws = deslocar(ocr.tsv(faixa, psm, numeros=True))
            _endireitar(ws, inclinacao)
            leituras.append(_juntar_partidos(ws))
    # a coluna de valores em pedaços: o OCR da faixa inteira às vezes pula linhas de fundo cinza
    pedacos, passo = [], 480
    for y0 in range(max(0, int(topo_tabela) - 40), int(min(altura, fim_tabela + 40)), passo - 80):
        y1 = min(altura, y0 + passo)
        ws = ocr.tsv(img_num.crop((x_faixa, y0, largura, y1)), 11, numeros=True)
        for w in ws:
            w.update(x0=w["x0"] + x_faixa, x1=w["x1"] + x_faixa, top=w["top"] + y0, bottom=w["bottom"] + y0)
        _endireitar(ws, inclinacao)
        pedacos += [w for w in ws if not any(abs(_meio(w) - _meio(p)) < 8 and abs(w["x1"] - p["x1"]) < 20 for p in pedacos)]
    leituras.append(_juntar_partidos(pedacos))
    leituras.append(_juntar_partidos([w for w in texto if w["x0"] >= x_faixa]))
    valores = _votar(leituras, altura_letra)

    # colunas: pelo cabeçalho; se não foi lido, pelos próprios valores (débitos terminam com "-")
    if d is not None:
        col_deb = (d["x0"] + d["x1"]) / 2
    else:
        negativos = [v["xc"] for v in valores if v["neg"] and v["y"] > topo_tabela]
        if not negativos:
            return None
        col_deb = median(negativos)
    col_cred = (c["x0"] + c["x1"]) / 2 if c is not None else col_deb - largura * 0.09
    saldos_cab = [w for w in texto if letras(w).startswith("SALDO") and w["x0"] > col_deb + 30
                  and abs(_meio(w) - topo_tabela) < altura_letra * 6]
    col_saldo = (min(w["x0"] for w in saldos_cab) + 70) if saldos_cab else col_deb + largura * 0.165

    textao = sem_acento(" ".join(l["texto"] for l in linhas))
    if not any(k in textao for k in ("SANTANDER", "CONTAMAX", "CONTA CORRENTE EM", "CONSOLIDADO")):
        return None
    pagina = {"altura_letra": altura_letra, "linhas": linhas, "mes": None, "resumo": None, "itens": [],
              "agencia": "", "conta": "", "empresa": "", "anos": []}
    # mês do cabeçalho ("Resumo - janeiro/2026", "EXTRATO CONSOLIDADO INTELIGENTE janeiro/2026"); o
    # histórico pode citar outro mês ("TARIFA MENSALIDADE ... FEVEREIRO / 2026")
    m = _MES_ANO.search(sem_acento(" ".join(l["texto"] for l in linhas if l["y"] < topo_tabela - tol)))
    if m:
        pagina["mes"] = (MESES[m[1]], int(m[2]))
    pagina["anos"] = [int(a) for a in re.findall(r"\b\d{2}/\d{2}/(20\d{2})\b|/\s*(20\d{2})\b", textao) for a in a if a]

    # resumo (acima da movimentação): valores na ordem em que aparecem
    rotulos = [l for l in linhas if "CONTA CORRENTE EM" in l["sem"] and l["y"] < topo_tabela]
    if rotulos:
        ini = rotulos[0]["y"] - altura_letra * 3
        fim_res = max(l["y"] for l in linhas if l["y"] < topo_tabela - altura_letra * 4
                      and ("TOTAL EM" in l["sem"] or "LIMITE" in l["sem"] or "DISPONIVEL" in l["sem"]
                           or "CONTA CORRENTE EM" in l["sem"])) + altura_letra * 2
        res = sorted((v for v in valores if ini <= v["y"] <= fim_res and v["xc"] < col_saldo - 50
                      and v["xc"] > largura * 0.45), key=lambda v: v["y"])
        datas = re.findall(r"CONTA CORRENTE EM\s*(\d{2})\s*/?\s*(\d{2})", " ".join(l["sem"] for l in rotulos))
        pagina["resumo"] = {"valores": res, "datas": [(int(d_), int(m_)) for d_, m_ in datas]}
        _cadastro(pagina, linhas, texto)

    # movimentação
    tab = [v for v in valores if topo_tabela < v["y"] < fim_tabela and v["xc"] > col_cred - largura * 0.06]
    movs, saldos = [], []
    for v in tab:
        dist = {"c": abs(v["xc"] - col_cred), "d": abs(v["xc"] - col_deb), "s": abs(v["xc"] - col_saldo)}
        col = min(dist, key=dist.get)
        if col == "s":
            saldos.append(v)
        else:
            v["credito"] = col == "c" if not v["neg"] or col == "d" else False
            movs.append(v)
    hist = []
    for l in linhas:
        if not (topo_tabela + tol < l["y"] < fim_tabela):
            continue
        palavras = [w for w in l["ws"] if w["x1"] < lim_hist + 25]
        if not palavras:
            continue
        data = None
        if palavras and palavras[0]["x1"] < lim_data + 30:
            dm = re.fullmatch(r"[^\d]*(\d{2})\s*/?\s*(\d{2})[^\d]*",
                              palavras[0]["text"].translate(str.maketrans("DOoQlI|SB", "000011158")))
            if dm and 1 <= int(dm[1]) <= 31 and 1 <= int(dm[2]) <= 12:
                data = (int(dm[1]), int(dm[2]))
            if dm or len(palavras[0]["text"]) <= 3 and not palavras[0]["text"].isalpha():
                palavras = palavras[1:]
        palavras = [w for w in palavras if not _ruido_hist(w)]
        # "SALDO EM 31/01" grudado no fim da linha de cima ("APLICACAO CONTAMAX SALDOEM3IO!")
        corte = next((k for k, w in enumerate(palavras) if re.match(r"S?A?LDO(EM|$)", sem_acento(w["text"]))
                      and (k + 1 < len(palavras) and sem_acento(palavras[k + 1]["text"]).startswith("EM")
                           or "LDOEM" in sem_acento(w["text"]))), None)
        if corte:
            hist.append({"y": l["y"] + 0.01, "texto": " ".join(w["text"] for w in palavras[corte:]), "data": None,
                         "doc": "", "saldo_em": True})
            palavras = palavras[:corte]
        texto_l = " ".join(w["text"] for w in palavras)
        texto_l = re.sub(r"^[^A-Za-z0-9]+", "", texto_l).strip()
        docs = [w["text"] for w in l["ws"] if lim_hist - 5 <= w["x0"] < x_faixa + 120 and re.fullmatch(r"\d{4,}", w["text"])]
        if texto_l or data:
            hist.append({"y": l["y"], "texto": texto_l, "data": data, "doc": docs[0] if docs else "",
                         "saldo_em": bool(re.match(r"\W*S?A?LDO\s*EM", sem_acento(texto_l)))})
    hist.sort(key=lambda h: h["y"])
    pagina["itens"] = _montar(movs, saldos, hist, altura_letra)
    pagina["fim"] = fim_tabela < altura
    return pagina


def _ruido_hist(w):
    """No histórico (em maiúsculas), palavras minúsculas ou curtinhas com pouca confiança são sujeira."""
    t = w["text"]
    if re.fullmatch(r"[\W_]+", t):
        return True
    if any(c.islower() for c in t) and w["conf"] < 75:
        return True
    return len(t) <= 2 and w["conf"] < 70 and t.upper() not in ("DE", "EM", "DA", "DO", "E", "A", "S/A")


PALAVRAS_INICIO = ("TARIFA", "RESGATE", "APLICACAO", "PAGAMENTO", "PGTO", "DEBITO", "TED", "PIX", "DOC",
                   "TRANSFERENCIA", "DEPOSITO", "JUROS", "IOF", "SALDO", "CREDITO", "ESTORNO", "COMPRA", "SAQUE")


def _limpar_hist(texto):
    """Tira sujeira do começo ("E APLICACAO…", "A PMES SIRESGATE…") e do fim do histórico."""
    palavras = texto.split()
    for k, p in enumerate(palavras[:4]):
        letras = re.sub(r"[^A-Z]", "", sem_acento(p))
        achou = next((c for c in PALAVRAS_INICIO if c in letras), None)
        if achou:
            if not letras.startswith(achou):  # "SIRESGATE" -> "RESGATE"
                palavras[k] = p[sem_acento(p).find(achou):] if achou in sem_acento(p) else p
            palavras = palavras[k:]
            break
    while palavras and (len(re.sub(r"[^A-Za-z0-9]", "", palavras[-1])) <= 2 or re.search(r"[)(\]\[;:]", palavras[-1])):
        palavras.pop()
    return " ".join(palavras)


def _tipo_foto(hist, credito):
    h = sem_acento(hist)
    if h.startswith("DEBITO AUT"):
        return "Débito automático"
    if h.startswith("RESGATE CDB") or h.startswith("RESGATE CDBRDB"):
        return "Resgate de CDB"
    if h.startswith("APLICACAO CDB"):
        return "Aplicação em CDB"
    return _tipo(hist, credito)


def _sujeira(w):
    """Pedacinhos lidos em manchas, carimbos e marcas d'água."""
    t = w["text"]
    if re.fullmatch(r"[\W_]+", t):
        return True
    return w["conf"] < 45 and len(t) <= 3 and not (t.isupper() or t.isdigit())


def _inclinacao(texto, largura):
    """Inclinação das linhas (dy/dx) em função da altura na página: fotos têm perspectiva, então a
    inclinação no alto da folha pode ser diferente da do pé. Medida nas linhas de texto longas."""
    grupos = {}
    for w in texto:
        grupos.setdefault(w["linha"], []).append(w)
    pontos = []
    for ws in grupos.values():
        ws = [w for w in ws if w["conf"] > 50 and len(w["text"]) > 1]
        if len(ws) < 3:
            continue
        xs = [(w["x0"] + w["x1"]) / 2 for w in ws]
        ys = [_meio(w) for w in ws]
        if max(xs) - min(xs) < largura * 0.2:
            continue
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        if abs(b) < 0.12:
            pontos.append((my, b, max(xs) - min(xs)))
    if not pontos:
        return lambda y: 0.0
    if len(pontos) < 6:
        k = median(b for _, b, _ in pontos)
        return lambda y: k
    # reta b(y) por mínimos quadrados ponderados pelo comprimento da linha, sem os pontos fora da curva
    def ajustar(pts):
        sw = sum(p[2] for p in pts)
        my = sum(p[0] * p[2] for p in pts) / sw
        mb = sum(p[1] * p[2] for p in pts) / sw
        syy = sum(p[2] * (p[0] - my) ** 2 for p in pts)
        a1 = sum(p[2] * (p[0] - my) * (p[1] - mb) for p in pts) / syy if syy else 0.0
        return mb - a1 * my, a1
    a0, a1 = ajustar(pontos)
    erros = sorted(abs(b - (a0 + a1 * y)) for y, b, _ in pontos)
    limite = erros[int(len(erros) * 0.8)] if len(erros) > 5 else max(erros)
    bons = [p for p in pontos if abs(p[1] - (a0 + a1 * p[0])) <= limite]
    if len(bons) >= 4:
        a0, a1 = ajustar(bons)
    return lambda y: a0 + a1 * y


def _endireitar(palavras, inclinacao):
    """Corrige a altura de cada palavra pela inclinação, como se a foto estivesse reta."""
    for w in palavras:
        delta = inclinacao(_meio(w)) * (w["x0"] + w["x1"]) / 2
        w["top"] -= delta
        w["bottom"] -= delta


def _cadastro(pagina, linhas, texto):
    """Agência, conta e nome da empresa (bloco acima do resumo)."""
    for w in texto:
        m = re.fullmatch(r"(\d{2})[.,](\d{6})-(\d)", w["text"].strip(".,;"))
        if m:
            pagina["conta"] = f"{m[1]}.{m[2]}-{m[3]}"
            ag = [p for p in texto if re.fullmatch(r"\d{4}", p["text"]) and p["x1"] < w["x0"]
                  and 0 <= _meio(p) - _meio(w) + 15 < 60]
            if ag:
                pagina["agencia"] = ag[0]["text"]
            break
    nome = [w for w in texto if sem_acento(w["text"]).startswith("NOME")]
    agencia = [w for w in texto if sem_acento(w["text"]).startswith("AGENCIA")]
    if nome and agencia and agencia[0]["top"] > nome[0]["bottom"]:
        ws = [w for w in texto if nome[0]["bottom"] - 4 < _meio(w) < agencia[0]["top"] and w is not nome[0]]
        pagina["empresa"] = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))


def _votar(leituras, altura_letra):
    """Junta as três leituras dos valores: a mesma posição vira um valor, com a leitura mais votada
    e as demais guardadas como alternativas (usadas para corrigir quando o saldo não bate)."""
    pontos = []
    for i, ws in enumerate(leituras):
        for w in ws:
            n = _num(w["text"], sem_virgula=i < len(leituras) - 1)
            if n is None:
                continue
            x, y = w["x1"], _meio(w)  # valores alinhados à direita
            for p in pontos:
                sobrepoe = min(p["x1"], w["x1"]) - max(p["x0"], w["x0"]) > altura_letra
                if sobrepoe and abs(p["y"] - y) < altura_letra * 0.8 and i not in p["por"]:
                    p["por"][i] = n
                    p["xcs"].append((w["x0"] + w["x1"]) / 2)
                    break
            else:
                pontos.append({"x": x, "y": y, "x0": w["x0"], "x1": w["x1"], "xcs": [(w["x0"] + w["x1"]) / 2],
                               "por": {i: n}})
    valores = []
    for p in pontos:
        lidos = list(p["por"].values())
        votos = {}
        for v, neg in lidos:
            votos[v] = votos.get(v, 0) + 1
        # empate: a 1ª leitura (só números, modo esparso) costuma ser a melhor
        preferido = p["por"].get(0, lidos[0])[0]
        escolhido = max(votos, key=lambda v: (votos[v], v == preferido))
        if len(lidos) == 1 and escolhido < 1:
            continue  # um "0,0x" isolado lido só numa passada costuma ser sujeira
        negativos = sum(1 for _, n in lidos if n)
        valores.append({"x": p["x"], "xc": median(p["xcs"]), "y": p["y"], "valor": escolhido,
                        "neg": negativos * 2 > len(lidos),
                        "alternativas": sorted({v for v, _ in lidos} - {escolhido}), "votos": votos[escolhido],
                        "leituras": len(lidos)})
    return valores


def _montar(movs, saldos, hist, altura_letra):
    """Liga cada valor (crédito/débito) à linha do histórico onde o lançamento começa: as linhas são
    percorridas em ordem e cada valor fica com uma linha diferente, a de menor distância; linhas que
    sobram são continuação do histórico do lançamento anterior."""
    movs.sort(key=lambda v: v["y"])
    linhas = [h for h in hist if not h["saldo_em"]]
    # deslocamento típico entre o valor e a linha do histórico (o valor costuma ficar um pouco acima)
    difs = []
    for v in movs:
        abaixo = [h["y"] - v["y"] for h in linhas if -altura_letra < h["y"] - v["y"] < altura_letra * 2.5]
        if abaixo:
            difs.append(min(abaixo, key=abs))
    desloc = median(difs) if difs else 0
    n, m = len(movs), len(linhas)
    INF = float("inf")
    pena = altura_letra * 3  # valor sem linha própria
    # custo[i][j]: melhor custo usando os i primeiros valores e as j primeiras linhas
    custo = [[INF] * (m + 1) for _ in range(n + 1)]
    volta = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        custo[0][j] = 0
    for i in range(1, n + 1):
        for j in range(0, m + 1):
            melhores = []
            if j > 0:
                melhores.append((custo[i][j - 1], "pula"))
                d = abs(linhas[j - 1]["y"] - (movs[i - 1]["y"] + desloc))
                melhores.append((custo[i - 1][j - 1] + d, "liga"))
            melhores.append((custo[i - 1][j] + pena, "sem"))
            custo[i][j], volta[i][j] = min(melhores, key=lambda x: x[0])
    i, j, ligacao = n, m, {}
    while i > 0:
        acao = volta[i][j]
        if acao == "pula":
            j -= 1
        elif acao == "liga":
            ligacao[i - 1] = j - 1
            i, j = i - 1, j - 1
        else:
            ligacao[i - 1] = None
            i -= 1

    itens = []
    inicio_de = {lj: vi for vi, lj in ligacao.items() if lj is not None}
    atual = None
    continuacao_inicial = []
    for j, h in enumerate(linhas):
        if j in inicio_de and movs[inicio_de[j]]["leituras"] == 1 and not re.search(r"[A-Z]{4,}", h["texto"]):
            inicio_de.pop(j)  # valor lido uma vez só numa linha sem texto de verdade: sujeira
        if j in inicio_de:
            v = movs[inicio_de[j]]
            atual = {"tipo": "mov", "y": v["y"], "data": h["data"], "hist": [h["texto"]], "doc": h["doc"],
                     "valor": v["valor"], "credito": v["credito"], "alternativas": v["alternativas"],
                     "votos": v["votos"], "duvida": v["votos"] < 2 and v["leituras"] > 1}
            itens.append(atual)
        elif atual is not None:
            atual["hist"].append(h["texto"])
            if h["doc"] and not atual["doc"]:
                atual["doc"] = h["doc"]
            if h["data"] and not atual["data"]:
                atual["data"] = h["data"]
        else:
            continuacao_inicial.append(h)
    for vi, lj in ligacao.items():
        if lj is None and movs[vi]["leituras"] > 1:
            v = movs[vi]
            itens.append({"tipo": "mov", "y": v["y"], "data": None, "hist": ["(histórico não lido)"], "doc": "",
                          "valor": v["valor"], "credito": v["credito"], "alternativas": v["alternativas"],
                          "votos": v["votos"], "duvida": True})
    # data na linha de cima (ex.: data impressa na 2ª linha do histórico, lida acima do valor)
    for h in hist:
        if h["saldo_em"]:
            itens.append({"tipo": "saldo_em", "y": h["y"] - desloc, "texto": h["texto"], "valor": None})
    itens.sort(key=lambda it: it["y"])
    for s in sorted(saldos, key=lambda v: v["y"]):
        # o mais próximo; quase empatado, o de baixo (o saldo é o do fim do dia)
        alvo = min(itens, key=lambda it: (abs(it["y"] - s["y"]) - (altura_letra * 0.3 if it["y"] > s["y"] else 0)),
                   default=None)
        # o saldo do dia fica na linha do valor do último lançamento; longe disso (ex.: o saldo da linha
        # "SALDO EM ..." não lida) é ignorado
        if alvo is None or abs(alvo["y"] - s["y"]) > altura_letra * (2.5 if alvo["tipo"] == "saldo_em" else 1.2):
            continue
        if alvo["tipo"] == "saldo_em":
            alvo["valor"], alvo["alternativas_saldo"] = s["valor"], s["alternativas"]
            alvo["votos"] = s["votos"]
        else:
            alvo.setdefault("saldos", []).append(s)
    return {"continuacao": [h["texto"] for h in continuacao_inicial if h["texto"]], "itens": itens}


# ---------------------------------------------------------------- páginas -> extratos

def e_pagina_do_extrato(pagina):
    return pagina is not None and (pagina["itens"]["itens"] or pagina["resumo"])


def _mes_da_pagina(p):
    if p["mes"]:
        return p["mes"]
    if p["resumo"] and p["resumo"]["datas"]:
        d, m = p["resumo"]["datas"][-1]
        return (m, None)
    meses = [it["data"][1] for it in p["itens"]["itens"] if it["tipo"] == "mov" and it["data"]]
    if meses:
        return (max(set(meses), key=meses.count), None)
    return None


def montar_extratos(paginas):
    """Páginas lidas (na ordem enviada) -> [Extrato] (um por mês)."""
    grupos = []
    for p in paginas:
        mes = _mes_da_pagina(p)
        alvo = None
        if not p["resumo"]:
            for g in grupos:  # continuação do mesmo mês (mesmo se as fotos vierem fora de ordem)
                if mes and g["mes"] and g["mes"][0] == mes[0]:
                    alvo = g
            if alvo is None and grupos and not mes:
                alvo = grupos[-1]
        if alvo is None:
            for g in grupos:
                if p["resumo"] and not g["tem_resumo"] and mes and g["mes"] and g["mes"][0] == mes[0]:
                    alvo = g
        if alvo is None:
            alvo = {"mes": mes, "paginas": [], "tem_resumo": False}
            grupos.append(alvo)
        if p["resumo"]:
            alvo["paginas"].insert(0, p)
            alvo["tem_resumo"] = True
        else:
            alvo["paginas"].append(p)
        if mes and (not alvo["mes"] or not alvo["mes"][1]):
            alvo["mes"] = mes
    anos = [a for p in paginas for a in p["anos"]] + [g["mes"][1] for g in grupos if g["mes"] and g["mes"][1]]
    ano_padrao = max(set(anos), key=anos.count) if anos else date.today().year
    return [_extrato(g, ano_padrao) for g in grupos]


def _extrato(grupo, ano_padrao):
    mes, ano = grupo["mes"] if grupo["mes"] else (None, None)
    ano = ano or ano_padrao
    ex = Extrato(banco="Santander", rotulo_saldo_banco="Saldo banco fim do dia (R$)",
                 origem_resumo="no resumo do extrato (lido por OCR)",
                 nota_saldo="lido de foto/escaneado por OCR: confira as células amarelas")
    for p in grupo["paginas"]:
        ex.agencia = ex.agencia or p["agencia"]
        ex.conta = ex.conta or p["conta"]
        ex.empresa = ex.empresa or p["empresa"]
    resumo = next((p["resumo"] for p in grupo["paginas"] if p["resumo"]), None)
    itens = []
    for p in grupo["paginas"]:
        cont = p["itens"]["continuacao"]
        if cont and itens:
            ult = next((it for it in reversed(itens) if it["tipo"] == "mov"), None)
            if ult:
                ult["hist"].extend(cont)
        itens.extend(p["itens"]["itens"])

    def data_de(dm):
        d, m = dm
        a = ano - 1 if mes and m > mes else ano
        try:
            return date(a, m, d)
        except ValueError:
            return None

    if mes:
        ex.inicio = date(ano, mes, 1)
        ex.fim = (date(ano + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1))
    abertura = fechamento = None
    saldos_em = [it for it in itens if it["tipo"] == "saldo_em"]
    if saldos_em:
        primeiro_mov = next((k for k, it in enumerate(itens) if it["tipo"] == "mov"), len(itens))
        for it in saldos_em:
            if itens.index(it) < primeiro_mov:
                abertura = it["valor"]
            else:
                fechamento = it["valor"]
    # resumo: 1º valor = saldo anterior, 2º = total de créditos, os 5 últimos = saldo final,
    # investimentos, disponível, limite e total; o total de débitos fica no meio
    res_ini = res_fim = tot_c = tot_d = None
    if resumo and len(resumo["valores"]) >= 7:
        vs = [v["valor"] for v in resumo["valores"]]
        res_ini, tot_c, res_fim = vs[0], vs[1], vs[-5]
        meio = vs[2:-5]
        esperado = res_ini + tot_c - res_fim
        tot_d = esperado if esperado in meio or not meio else _total_debitos(tot_c, meio, esperado)
    ex.saldo_anterior = res_ini if res_ini is not None else abertura
    ex.saldo_final = res_fim if res_fim is not None else fechamento
    ex.total_entradas, ex.total_saidas = tot_c, tot_d
    if ex.inicio:
        ex.data_saldo_anterior = ex.inicio - timedelta(days=1)

    movimentos, ultima_data = [], None
    for it in itens:
        if it["tipo"] != "mov":
            continue
        d = data_de(it["data"]) if it["data"] else None
        if d is None or (mes and d.month != mes and d.month != (mes - 2) % 12 + 1):
            d = ultima_data or ex.inicio or date(ano, mes or 1, 1)
        ultima_data = d
        completo = _limpar_hist(re.sub(r"\s+", " ", " ".join(it["hist"])).strip()) or "(histórico não lido)"
        hist, fav = _separar(completo)
        valor = it["valor"]
        mov = Movimento(d, hist, valor if it["credito"] else None, None if it["credito"] else valor,
                        favorecido=fav, documento=it["doc"])
        mov.tipo = _tipo_foto(hist, it["credito"])
        mov._alternativas = it["alternativas"]
        mov._votos = it.get("votos", 1)
        mov._saldos = it.get("saldos", [])
        if it["duvida"]:
            mov.aviso = "Leitura incerta do OCR" + (
                f" (lido também: {', '.join(_br(a) for a in it['alternativas'])})." if it["alternativas"] else ".")
        movimentos.append(mov)
    # saldo do fim do dia: impresso na linha do último lançamento do dia
    for mov in movimentos:
        if mov._saldos:
            s = mov._saldos[-1]
            mov.saldo_banco = s["valor"]
            mov._alt_saldo = s["alternativas"]
            mov._votos_saldo = s["votos"]
    ex.movimentos = movimentos
    completo = fechamento is not None or any(p.get("fim") for p in grupo["paginas"])
    if not completo:
        ex.nota_saldo += "; atenção: não foi encontrado o fim do extrato deste mês — falta alguma foto/página?"
    _corrigir(ex, abertura, fechamento if completo else None, usar_saldo_final=completo)
    if completo:
        _corrigir_totais(ex)
        if (ex.total_entradas == sum((m.entrada or 0) for m in movimentos)
                and ex.total_saidas == sum((m.saida or 0) for m in movimentos)):
            for m in movimentos:  # tudo fechou, inclusive os totais do resumo: as dúvidas se resolveram
                if m.aviso.startswith("Leitura incerta"):
                    m.aviso = ""
    if hasattr(ex, "_falhas"):
        del ex._falhas
    for mov in movimentos:
        for atributo in ("_alternativas", "_saldos", "_alt_saldo", "_votos", "_votos_saldo"):
            if hasattr(mov, atributo):
                delattr(mov, atributo)
    return ex


def _corrigir_totais(ex):
    """Dois valores errados no mesmo dia podem se anular (crédito e débito com o mesmo erro). O total
    de créditos e de débitos do resumo pega esse caso: procura, no mesmo dia, um crédito e um débito
    cuja troca de dígito acerta os dois totais ao mesmo tempo."""
    if ex.total_entradas is None or ex.total_saidas is None:
        return
    dc = ex.total_entradas - sum((m.entrada or 0) for m in ex.movimentos)
    dd = ex.total_saidas - sum((m.saida or 0) for m in ex.movimentos)
    falhas = getattr(ex, "_falhas", [])
    if len(falhas) == 1 and (dc or dd):
        # um dia não fechou e os totais também não: a correção tem de acertar as duas coisas
        trecho, dif, _ = falhas[0]
        sols = []
        for k, m in enumerate(trecho):
            atual = m.entrada if m.entrada is not None else m.saida
            for v, custo in _candidatos(atual, m._alternativas, getattr(m, "_votos", 1)).items():
                delta = v - atual
                if m.entrada is not None and delta == dc and dd == 0 and delta == dif:
                    sols.append((custo, k, v))
                if m.saida is not None and delta == dd and dc == 0 and -delta == dif:
                    sols.append((custo, k, v))
        sols.sort()
        if sols and (len(sols) == 1 or sols[1][0] - sols[0][0] >= 1.0):
            _, k, v = sols[0]
            m = trecho[k]
            antigo = m.entrada if m.entrada is not None else m.saida
            if m.entrada is not None:
                m.entrada = v
            else:
                m.saida = v
            m.aviso = (f"OCR leu {_br(antigo)}; corrigido para {_br(v)} para fechar o saldo do dia e o total do "
                       "resumo do banco. Confira com o extrato.")
            for outro in trecho:
                if outro is not m and outro.aviso.startswith("O saldo deste dia"):
                    outro.aviso = ""
            return
    if dc == 0 and dd == 0 or dc != dd:
        return
    solucoes = []
    for i, a in enumerate(ex.movimentos):
        if a.entrada is None:
            continue
        ca = _candidatos(a.entrada, a._alternativas, getattr(a, "_votos", 1))
        for j, b in enumerate(ex.movimentos):
            if b.saida is None or b.data != a.data:
                continue
            cb = _candidatos(b.saida, b._alternativas, getattr(b, "_votos", 1))
            for va, custo_a in ca.items():
                if va - a.entrada == dc and b.saida + dc in cb:
                    solucoes.append((custo_a + cb[b.saida + dc], i, va, j, b.saida + dc))
    if not solucoes:
        return
    solucoes.sort()
    if len(solucoes) > 1 and solucoes[1][0] - solucoes[0][0] < 1.0:
        return
    _, i, va, j, vb = solucoes[0]
    for m, novo in ((ex.movimentos[i], va), (ex.movimentos[j], vb)):
        antigo = m.entrada if m.entrada is not None else m.saida
        if m.entrada is not None:
            m.entrada = novo
        else:
            m.saida = novo
        m.aviso = (f"OCR leu {_br(antigo)}; corrigido para {_br(novo)} para fechar com o total de créditos e "
                   "débitos do resumo do banco. Confira com o extrato.")


def _total_debitos(tot_c, meio, esperado):
    """Total de débitos entre os valores do resumo: o que vem depois do detalhamento dos créditos."""
    for k in range(len(meio)):
        if sum(meio[:k], Decimal(0)) in (0, tot_c) and (k == len(meio) - 1 or sum(meio[k + 1:], Decimal(0)) == meio[k]):
            return meio[k]
    return esperado


def _variantes(v, trocas):
    """Valores com `trocas` algarismos trocados pelos parecidos (1↔4, 5↔8…)."""
    s = f"{v:.2f}".replace(".", "")
    saida = set()
    for posicoes in combinations(range(len(s)), trocas):
        opcoes = [[]]
        for i in posicoes:
            opcoes = [o + [(i, c)] for o in opcoes for c in CONFUSAO.get(s[i], "")]
        for o in opcoes:
            t = list(s)
            for i, c in o:
                t[i] = c
            t = "".join(t).lstrip("0") or "0"
            saida.add(Decimal(t[:-2] + "." + t[-2:]) if len(t) > 2 else Decimal("0." + t.zfill(2)))
    saida.discard(v)
    return saida


def _corrigir(ex, abertura, fechamento, usar_saldo_final=True):
    """Confere cada trecho entre saldos impressos pelo banco; se não fechar, procura a leitura
    alternativa ou a troca de dígito que faz fechar (só aplica quando a solução é única)."""
    movs = ex.movimentos
    pontos = [k for k, m in enumerate(movs) if m.saldo_banco is not None]
    final = (ex.saldo_final if ex.saldo_final is not None else fechamento) if usar_saldo_final else None
    if final is not None and (not pontos or pontos[-1] != len(movs) - 1):
        pontos.append(len(movs) - 1)
    saldo = ex.saldo_anterior if ex.saldo_anterior is not None else abertura
    if saldo is None or not movs:
        return
    ex._falhas = []
    inicio = 0
    for p in pontos:
        alvo = movs[p].saldo_banco if movs[p].saldo_banco is not None else final
        trecho = movs[inicio:p + 1]
        calc = saldo + sum((m.entrada or 0) - (m.saida or 0) for m in trecho)
        if calc != alvo:
            _consertar_trecho(trecho, alvo - calc, movs[p])
            calc = saldo + sum((m.entrada or 0) - (m.saida or 0) for m in trecho)
            alvo = movs[p].saldo_banco if movs[p].saldo_banco is not None else alvo
        if calc != alvo:  # não fechou: marca os valores do dia para conferência
            ex._falhas.append((trecho, alvo - calc, movs[p]))
            for m in trecho:
                if not m.aviso or m.aviso.startswith("Leitura incerta"):
                    m.aviso = (f"O saldo deste dia não fechou com o banco (diferença de {_br(alvo - calc)}). "
                               "Confira os valores do dia: pode haver valor mal lido ou lançamento que o OCR não leu.")
        # cada trecho é conferido sozinho: o próximo parte do saldo impresso pelo banco
        saldo = movs[p].saldo_banco if movs[p].saldo_banco is not None else alvo
        inicio = p + 1


def _candidatos(atual, alternativas, votos):
    """Valores possíveis e o "custo" de cada um: outra leitura do OCR custa pouco; trocar dígito
    parecido custa mais, e mais ainda se as leituras concordavam no valor atual."""
    c = {atual: 0.0}
    for a in alternativas:
        c[a] = min(c.get(a, 9), 1.0)
    extra = 1.5 * max(votos - 1, 0)
    for base, custo_base in list(c.items()):
        b = f"{base:.2f}"
        for v in _variantes(base, 1):
            t = f"{v:.2f}"
            troca = [(x, y) for x, y in zip(b.rjust(len(t)), t.rjust(len(b)))if x != y]
            # o OCR lê "1" como "4" com frequência; o contrário é raro
            custo = 0.7 if troca == [("4", "1")] else 2.0
            custo += custo_base + (extra if base == atual else 0)
            if custo < c.get(v, 9):
                c[v] = custo
    return c


def _consertar_trecho(trecho, diferenca, ponto):
    """Procura a correção de menor custo (no máximo dois valores mudados) que faz o trecho fechar com
    o saldo impresso; só aplica se ela for claramente melhor que a segunda opção."""
    itens = []
    for m in trecho:
        atual = m.entrada if m.entrada is not None else m.saida
        itens.append(("mov", m, atual, 1 if m.entrada is not None else -1,
                      _candidatos(atual, m._alternativas, getattr(m, "_votos", 1))))
    if ponto.saldo_banco is not None:
        itens.append(("saldo", ponto, ponto.saldo_banco, -1,
                      _candidatos(ponto.saldo_banco, getattr(ponto, "_alt_saldo", []), getattr(ponto, "_votos_saldo", 1))))
    solucoes = []  # (custo, ((índice, valor), ...))
    deltas = []
    for k, (tipo, obj, atual, sinal, cands) in enumerate(itens):
        mapa = {}
        for v, custo in cands.items():
            if v != atual:
                d = (v - atual) * sinal
                if custo < mapa.get(d, (9, None))[0]:
                    mapa[d] = (custo, v)
        if tipo == "mov" and atual:  # lido na coluna errada (crédito ↔ débito)
            d = -2 * atual * sinal
            if 2.5 < mapa.get(d, (9, None))[0]:
                mapa[d] = (2.5, "inverte")
        deltas.append(mapa)
    for k, mapa in enumerate(deltas):
        if diferenca in mapa:
            custo, v = mapa[diferenca]
            solucoes.append((custo, ((k, v),)))
    for k1 in range(len(itens)):
        for d1, (c1, v1) in deltas[k1].items():
            for k2 in range(k1 + 1, len(itens)):
                falta = diferenca - d1
                if falta in deltas[k2]:
                    c2, v2 = deltas[k2][falta]
                    solucoes.append((c1 + c2 + 0.5, ((k1, v1), (k2, v2))))
    if not solucoes:
        return
    solucoes.sort(key=lambda s: s[0])
    melhor = solucoes[0]
    if len(solucoes) > 1 and solucoes[1][0] - melhor[0] < 1.0 and solucoes[1][1] != melhor[1]:
        return  # duas correções quase igualmente prováveis: não chuta, fica o "DIVERGE" para conferência
    if melhor[0] > 4.5:
        return
    for k, v in melhor[1]:
        tipo, obj, atual, _, _ = itens[k]
        if tipo == "saldo":
            obj.aviso = (obj.aviso + " " if obj.aviso else "") + (
                f"Saldo do banco lido pelo OCR como {_br(atual)}; corrigido para {_br(v)}.")
            obj.saldo_banco = v
        elif v == "inverte":
            obj.entrada, obj.saida = obj.saida, obj.entrada
            obj.tipo = _tipo_foto(obj.historico, obj.entrada is not None)
            obj.aviso = ("Valor lido na coluna errada pelo OCR; trocado entre entrada e saída para o saldo do dia "
                         "fechar com o banco. Confira com o extrato.")
        else:
            if obj.entrada is not None:
                obj.entrada = v
            else:
                obj.saida = v
            obj.aviso = (f"OCR leu {_br(atual)}; corrigido para {_br(v)} para o saldo do dia fechar com o banco. "
                         "Confira com o extrato.")


MAX_PAGINAS = 12  # cada página leva ~15 s (várias leituras do OCR)


def ler_imagens(imagens):
    """[PIL.Image] (páginas na ordem enviada) -> ([Extrato], índices das páginas não reconhecidas)."""
    paginas, sobras = [], []
    for i, img in enumerate(imagens):
        p = ler_pagina(img)
        if e_pagina_do_extrato(p):
            paginas.append(p)
        else:
            sobras.append(i)
    return (montar_extratos(paginas) if paginas else []), sobras

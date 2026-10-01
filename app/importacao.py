"""Importação de clientes a partir de planilha (.xls, .xlsx ou .csv).

Fluxo: `ler_planilha` → `analisar` (gera a prévia, sem gravar nada) → `aplicar` (grava).
Colunas reconhecidas pelo cabeçalho: Código, Nome/Razão social, CNPJ, Regime/Tributação,
Responsável e Observações. As demais são ignoradas.
"""
import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .competencia import cnpj_valido, so_digitos
from .models import Empresa, GrupoEconomico, Modulo, RegimeTributario, Responsavel, db

EXTENSOES = {".xls", ".xlsx", ".csv"}

REGIME_A_DEFINIR = "A definir"
REGIME_REAL_TRIMESTRAL = "Lucro Real Trimestral"

# Nome normalizado do cabeçalho -> campo
CABECALHOS = {
    "codigo": "codigo", "cod": "codigo", "cod.": "codigo",
    "nome": "nome", "razao social": "nome", "razao": "nome", "empresa": "nome", "cliente": "nome",
    "cnpj": "cnpj", "cnpj/cpf": "cnpj", "documento": "cnpj",
    "regime": "regime", "tributacao": "regime", "regime tributario": "regime",
    "responsavel": "responsavel",
    "grupo economico": "grupo", "grupo": "grupo", "grupo empresarial": "grupo",
    "observacoes": "observacoes", "observacao": "observacoes", "obs": "observacoes", "obs.": "observacoes",
}


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower()


def _limpar(valor):
    """Texto da célula sem espaços duplicados/invisíveis; números inteiros sem '.0'."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor if valor is not None else "")).strip()


# ---------------------------------------------------------------- Leitura

def _abas_xls(conteudo):
    import xlrd
    livro = xlrd.open_workbook(file_contents=conteudo)
    return {s.name: [s.row_values(r) for r in range(s.nrows)] for s in livro.sheets()}


def _abas_xlsx(conteudo):
    import openpyxl
    livro = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    return {ws.title: [list(linha) for linha in ws.iter_rows(values_only=True)] for ws in livro.worksheets}


def _abas_csv(conteudo):
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t")
    except csv.Error:
        dialeto = csv.excel
    return {"CSV": list(csv.reader(io.StringIO(texto), dialeto))}


def ler_abas(conteudo, extensao):
    leitores = {".xls": _abas_xls, ".xlsx": _abas_xlsx, ".csv": _abas_csv}
    return leitores[extensao](conteudo)


def _mapa_colunas(linha):
    mapa = {}
    for i, celula in enumerate(linha):
        campo = CABECALHOS.get(_normalizar(celula))
        if campo and campo not in mapa:
            mapa[campo] = i
    return mapa


def localizar_tabela(linhas):
    """Procura a linha de cabeçalho nas primeiras linhas. Retorna (índice, mapa) ou None."""
    for i, linha in enumerate(linhas[:10]):
        mapa = _mapa_colunas(linha)
        if {"nome", "cnpj"} <= mapa.keys():
            return i, mapa
    return None


def abas_validas(abas):
    """Abas com cabeçalho reconhecido, das mais completas para as menos."""
    validas = []
    for nome, linhas in abas.items():
        achado = localizar_tabela(linhas)
        if achado:
            validas.append((len(achado[1]), nome))
    return [nome for _, nome in sorted(validas, key=lambda x: -x[0])]


def extrair_linhas(linhas):
    """Lista de dicts (com o número da linha na planilha) a partir da aba."""
    inicio, mapa = localizar_tabela(linhas)
    registros = []
    for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
        reg = {campo: _limpar(linha[i]) if i < len(linha) else "" for campo, i in mapa.items()}
        if any(reg.values()):
            reg["linha"] = n
            registros.append(reg)
    return registros, set(mapa)


# ---------------------------------------------------------------- Interpretação

def interpretar_regime(texto):
    """Nome do regime do sistema a partir do texto da planilha, ou None se não der para saber.

    Quando há mudança de regime ("SIMPLES/ PRESUMIDO EM 2026"), vale o último citado.
    """
    t = _normalizar(texto).upper()
    if not t:
        return None
    if "SEM FINS" in t or "IMUNE" in t or "ISENT" in t:
        return "Imune/Isenta"
    if re.search(r"\bMEI\b", t):
        return "MEI"
    citados = re.findall(r"SIMPLES|PRESUMIDO|REAL(?:\s+TRIMESTRAL)?", t)
    if not citados:
        return None
    ultimo = citados[-1]
    if ultimo.startswith("REAL"):
        return REGIME_REAL_TRIMESTRAL if "TRIMESTRAL" in ultimo else "Lucro Real"
    return {"SIMPLES": "Simples Nacional", "PRESUMIDO": "Lucro Presumido"}[ultimo]


def _regime_direto(texto, regime):
    """True se o texto da planilha corresponde diretamente ao regime (sem ambiguidade)."""
    if regime is None:
        return False
    t = _normalizar(texto)
    diretos = {"simples": "Simples Nacional", "simples nacional": "Simples Nacional",
               "presumido": "Lucro Presumido", "lucro presumido": "Lucro Presumido",
               "real": "Lucro Real", "lucro real": "Lucro Real",
               "real trimestral": REGIME_REAL_TRIMESTRAL, "mei": "MEI"}
    return diretos.get(t) == regime


# Textos usados na planilha para "ainda sem responsável definido".
RESPONSAVEL_PROVISORIO = {"novo", "nova", "-", "?", "a definir", "definir"}


def interpretar_responsavel(texto):
    """(nome do responsável, texto original se havia mais de um)."""
    if _normalizar(texto) in RESPONSAVEL_PROVISORIO:
        return None, None
    partes = [p.strip() for p in re.split(r"[/;,]| e ", texto or "") if p.strip()]
    if not partes:
        return None, None
    return partes[0].title(), (texto if len(partes) > 1 else None)


@dataclass
class LinhaPrevia:
    linha: int
    codigo: str
    nome: str
    cnpj: str
    regime_original: str
    regime: str | None
    responsavel: str | None
    observacoes: str
    situacao: str  # "nova" | "existente" | "erro"
    avisos: list = field(default_factory=list)
    erro: str | None = None
    empresa_id: int | None = None
    grupo: str | None = None
    grupo_atual: str | None = None  # grupo que a empresa já tem no sistema

    @property
    def cnpj_formatado(self):
        c = self.cnpj
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else c


@dataclass
class Previa:
    linhas: list
    colunas: set
    regimes_novos: list
    responsaveis_novos: list
    grupos_novos: list = field(default_factory=list)

    def contagem(self):
        return Counter(l.situacao for l in self.linhas)

    def por_situacao(self, situacao):
        return [l for l in self.linhas if l.situacao == situacao]

    def com_avisos(self):
        return [l for l in self.linhas if l.avisos and l.situacao != "erro"]

    def grupos(self):
        """Counter grupo -> nº de empresas (linhas válidas com grupo)."""
        return Counter(l.grupo for l in self.linhas if l.situacao != "erro" and l.grupo)

    def grupos_a_alterar(self):
        """Empresas já cadastradas cujo grupo será definido/alterado pela planilha."""
        return [l for l in self.linhas if l.situacao == "existente" and l.grupo
                and (l.grupo_atual or "").casefold() != l.grupo.casefold()]

    def regimes(self):
        return Counter(l.regime or REGIME_A_DEFINIR for l in self.linhas if l.situacao != "erro")


def analisar(registros, colunas):
    """Monta a prévia da importação sem alterar o banco."""
    existentes = {e.cnpj: e for e in Empresa.query}
    regimes_cadastrados = {r.nome for r in RegimeTributario.query}
    responsaveis_cadastrados = {_normalizar(r.nome) for r in Responsavel.query}
    codigos = Counter(r.get("codigo") for r in registros if r.get("codigo"))
    vistos = set()
    linhas = []

    for reg in registros:
        cnpj = so_digitos(reg.get("cnpj"))
        texto_regime = reg.get("regime", "")
        regime = interpretar_regime(texto_regime)
        texto_resp = reg.get("responsavel", "")
        responsavel, resp_multiplo = interpretar_responsavel(texto_resp)

        notas = []
        avisos = []
        if texto_regime and not _regime_direto(texto_regime, regime):
            notas.append(f"Regime na planilha: {texto_regime}")
            avisos.append(f"Regime “{texto_regime}” → {regime or REGIME_A_DEFINIR}")
        elif not texto_regime and "regime" in colunas:
            avisos.append(f"Sem regime → {REGIME_A_DEFINIR}")
        if texto_resp and responsavel is None:
            notas.append(f"Responsável na planilha: {texto_resp}")
            avisos.append(f"Responsável “{texto_resp}” → sem responsável")
        if resp_multiplo:
            notas.append(f"Responsável na planilha: {resp_multiplo}")
            avisos.append(f"Mais de um responsável; usado {responsavel}")
        if reg.get("codigo") and codigos[reg["codigo"]] > 1:
            avisos.append(f"Código {reg['codigo']} repetido na planilha")
        observacoes = "\n".join([reg.get("observacoes", "")] + notas).strip()

        item = LinhaPrevia(
            linha=reg["linha"], codigo=reg.get("codigo", ""), nome=reg.get("nome", ""),
            cnpj=cnpj, regime_original=texto_regime, regime=regime, responsavel=responsavel,
            observacoes=observacoes, situacao="nova", avisos=avisos,
            grupo=" ".join(reg.get("grupo", "").split()) or None,
        )
        if not item.nome:
            item.situacao, item.erro = "erro", "Nome em branco"
        elif not cnpj:
            item.situacao, item.erro = "erro", "CNPJ em branco"
        elif not cnpj_valido(cnpj):
            item.situacao, item.erro = "erro", f"CNPJ inválido ({reg.get('cnpj')})"
        elif cnpj in vistos:
            item.situacao, item.erro = "erro", "CNPJ repetido na planilha"
        elif cnpj in existentes:
            item.situacao, item.empresa_id = "existente", existentes[cnpj].id
            item.grupo_atual = existentes[cnpj].grupo.nome if existentes[cnpj].grupo else None
        vistos.add(cnpj)
        linhas.append(item)

    validas = [l for l in linhas if l.situacao != "erro"]
    regimes_novos = sorted({l.regime or REGIME_A_DEFINIR for l in validas} - regimes_cadastrados)
    responsaveis_novos = sorted({l.responsavel for l in validas if l.responsavel
                                 and _normalizar(l.responsavel) not in responsaveis_cadastrados})
    grupos_cadastrados = {g.nome.casefold() for g in GrupoEconomico.query}
    grupos_novos = sorted({l.grupo for l in validas if l.grupo
                           and l.grupo.casefold() not in grupos_cadastrados}, key=str.casefold)
    return Previa(linhas, colunas, regimes_novos, responsaveis_novos, grupos_novos)


# ---------------------------------------------------------------- Gravação

def _obter_regime(nome, cache):
    if nome not in cache:
        regime = RegimeTributario(nome=nome, ativo=True)
        if nome == REGIME_REAL_TRIMESTRAL:
            regime.descricao = "Criado na importação (mesmas obrigações do Lucro Real)"
            base = cache.get("Lucro Real")
            if base:
                regime.obrigacoes = list(base.obrigacoes)
        elif nome == REGIME_A_DEFINIR:
            regime.descricao = "Empresas importadas sem tributação identificada — reclassifique"
        else:
            regime.descricao = "Criado na importação"
        db.session.add(regime)
        cache[nome] = regime
    return cache[nome]


def _obter_responsavel(nome, cache):
    chave = _normalizar(nome)
    if chave not in cache:
        cache[chave] = Responsavel(nome=nome, ativo=True)
        db.session.add(cache[chave])
    return cache[chave]


MODOS_EXISTENTES = ("ignorar", "grupo", "tudo")


def aplicar(previa, modulo, modo_existentes="ignorar", criar_novas=True):
    """Grava a prévia. Retorna um Counter com o resultado.

    modo_existentes (empresas cujo CNPJ já está cadastrado):
      "ignorar" — não altera; "grupo" — só o grupo econômico; "tudo" — todos os dados.
    criar_novas: cadastrar as empresas cujo CNPJ ainda não existe.
    """
    regimes = {r.nome: r for r in RegimeTributario.query}
    responsaveis = {_normalizar(r.nome): r for r in Responsavel.query}
    grupos = {g.nome.casefold(): g for g in GrupoEconomico.query}
    resultado = Counter()
    with db.session.no_autoflush:
        for item in previa.linhas:
            if item.situacao == "nova" and not criar_novas:
                resultado["novas_puladas"] += 1
                continue
            _gravar_linha(item, modulo, modo_existentes, regimes, responsaveis, grupos, resultado)
    db.session.flush()
    GrupoEconomico.remover_vazios()
    db.session.commit()
    return resultado


def _gravar_linha(item, modulo, modo, regimes, responsaveis, grupos, resultado):
    if item.situacao == "erro":
        resultado["erros"] += 1
        return
    if item.situacao == "existente":
        empresa = db.session.get(Empresa, item.empresa_id)
        if modo == "grupo":
            if item.grupo and (empresa.grupo is None
                               or empresa.grupo.nome.casefold() != item.grupo.casefold()):
                empresa.grupo = GrupoEconomico.obter(item.grupo, grupos)
                resultado["grupos"] += 1
            else:
                resultado["ignoradas"] += 1
            return
        if modo != "tudo":
            resultado["ignoradas"] += 1
            return
        resultado["atualizadas"] += 1
    else:
        empresa = Empresa(cnpj=item.cnpj, ativo=True)
        db.session.add(empresa)
        resultado["criadas"] += 1
    empresa.codigo = item.codigo or empresa.codigo
    empresa.razao_social = item.nome
    empresa.regime = _obter_regime(item.regime or REGIME_A_DEFINIR, regimes)
    if item.observacoes:
        empresa.observacoes = item.observacoes
    if item.grupo:
        empresa.grupo = GrupoEconomico.obter(item.grupo, grupos)
    if item.responsavel and modulo is not None:
        empresa.controle(modulo, criar=True).responsavel = _obter_responsavel(
            item.responsavel, responsaveis)


def modulo_padrao():
    return Modulo.query.filter_by(codigo="contabil", ativo=True).first() or next(
        iter(Modulo.ativos()), None)

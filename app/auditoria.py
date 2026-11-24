"""Histórico de alterações: grava quem criou, alterou ou apagou cada registro.

Funciona sozinho a cada gravação no banco (evento after_flush do SQLAlchemy), então vale para
todas as telas. Só o dono do sistema (Usuario.dono) vê o histórico.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from . import models as m
from .competencia import fmt_valor

# tipo de registro → (rótulo, {campo: rótulo})
RASTREADOS = {
    m.Empresa: ("Cadastro da empresa", {
        "codigo": "Código", "razao_social": "Razão social", "nome_fantasia": "Nome fantasia", "cnpj": "CNPJ",
        "inscricao_estadual": "Inscrição estadual", "inscricao_municipal": "Inscrição municipal",
        "email": "E-mail", "telefone": "Telefone", "regime_id": "Tributação", "grupo_id": "Grupo econômico",
        "observacoes": "Observações", "ativo": "Ativa"}),
    m.EmpresaModulo: ("Rotina da empresa", {
        "modulo_id": "Módulo", "responsavel_id": "Responsável", "concluido_ate": "Escriturada/concluída até",
        "situacao": "Situação"}),
    m.Socio: ("Sócio", {"nome": "Nome", "documento": "CPF/CNPJ", "percentual": "Quotas (%)", "ativo": "Ativo"}),
    m.DistribuicaoLucro: ("Distribuição de lucros", {"socio_id": "Sócio", "ano": "Ano", "mes": "Mês",
                                                     "valor": "Valor"}),
    m.ObrigacaoAnual: ("Obrigações (DEFIS/ECD/ECF/IBGE)", {
        "ano": "Ano", "defis": "DEFIS", "ecd": "ECD", "ecf": "ECF", "ibge": "IBGE", "observacao": "Observação"}),
    m.LalurApuracao: ("LALUR – apuração", {
        "ano": "Ano", "periodo": "Período", "lucro_antes": "Lucro antes do IRPJ/CSLL",
        "compensar": "Compensar prejuízos", "aliquota_csll": "Alíquota CSLL", "irpj_deduzir": "IRPJ a deduzir",
        "csll_deduzir": "CSLL a deduzir", "observacao": "Observação", "quotas": "Quotas"}),
    m.LalurLancamento: ("LALUR – adição/exclusão", {"tipo": "Tipo", "tributo": "Tributo", "descricao": "Descrição",
                                                    "valor": "Valor"}),
    m.LalurSaldoInicial: ("LALUR – saldos de abertura", {"prejuizo_fiscal": "Prejuízo fiscal",
                                                         "base_negativa": "Base negativa"}),
    m.LalurQuotaEnvio: ("Quota enviada ao cliente", {"numero": "Quota", "enviado_em": "Enviada em"}),
    m.Entrega: ("Cumprimento de obrigação", {"obrigacao_id": "Obrigação", "competencia": "Competência",
                                             "data_entrega": "Data", "observacao": "Observação"}),
    m.Usuario: ("Usuário", {"nome": "Nome", "email": "E-mail", "senha_hash": "Senha", "admin": "Administrador",
                            "ativo": "Ativo", "responsavel_id": "Responsável vinculado"}),
    m.Responsavel: ("Responsável", {"nome": "Nome", "email": "E-mail", "ativo": "Ativo"}),
    m.RegimeTributario: ("Regime tributário", {"nome": "Nome", "descricao": "Descrição", "ativo": "Ativo"}),
    m.GrupoEconomico: ("Grupo econômico", {"nome": "Nome"}),
    m.Obrigacao: ("Obrigação (parametrização)", {"nome": "Nome", "periodicidade": "Periodicidade",
                                                 "ativo": "Ativa"}),
    m.Modulo: ("Módulo", {"nome": "Nome", "ativo": "Ativo", "rotulo_controle": "Rótulo"}),
}
_REFERENCIAS = {"regime_id": m.RegimeTributario, "grupo_id": m.GrupoEconomico, "responsavel_id": m.Responsavel,
                "modulo_id": m.Modulo, "obrigacao_id": m.Obrigacao, "socio_id": m.Socio}
_OCULTOS = {"dono"}  # nunca aparece no histórico


def _formatar(sessao, campo, valor):
    if campo == "senha_hash":
        return "(oculta)"
    if valor is None or valor == "":
        return "—"
    if campo in _REFERENCIAS:
        with sessao.no_autoflush:
            ref = sessao.get(_REFERENCIAS[campo], valor)
        return getattr(ref, "nome", None) or f"#{valor}"
    if campo in ("concluido_ate", "competencia") and isinstance(valor, date):
        return f"{valor:%m/%Y}"
    if isinstance(valor, datetime):
        return f"{valor:%d/%m/%Y %H:%M}"
    if isinstance(valor, date):
        return f"{valor:%d/%m/%Y}"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, Decimal):
        return fmt_valor(valor)
    if campo == "periodo":
        return "Anual" if valor == 0 else f"{valor}º trimestre"
    texto = str(valor)
    return texto if len(texto) <= 300 else texto[:300] + "…"


def _empresa_do(obj):
    if isinstance(obj, m.Empresa):
        return obj
    for caminho in ("empresa", "apuracao.empresa", "socio.empresa"):
        alvo = obj
        for parte in caminho.split("."):
            alvo = getattr(alvo, parte, None)
            if alvo is None:
                break
        if isinstance(alvo, m.Empresa):
            return alvo
    return None


def _usuario():
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user.is_authenticated:
            return current_user.id, current_user.nome
    except Exception:  # noqa: BLE001 - sem usuário identificado
        pass
    return None, "sistema"


def _linha(sessao, obj, acao, rotulos):
    insp = inspect(obj)
    detalhes = []
    for attr in insp.mapper.column_attrs:
        campo = attr.key
        if campo == "id" or campo in _OCULTOS:
            continue
        rotulo = rotulos.get(campo, campo.replace("_", " ").capitalize())
        hist = insp.attrs[campo].history
        if acao == "alterou":
            if not hist.has_changes():
                continue
            antes = hist.deleted[0] if hist.deleted else None
            depois = hist.added[0] if hist.added else None
            a, d = _formatar(sessao, campo, antes), _formatar(sessao, campo, depois)
            if campo == "senha_hash":
                detalhes.append("Senha: alterada")
            elif a != d:
                detalhes.append(f"{rotulo}: {a} → {d}")
        else:
            valor = getattr(obj, campo, None)
            if campo in rotulos and valor not in (None, "") and campo != "senha_hash":
                detalhes.append(f"{rotulo}: {_formatar(sessao, campo, valor)}")
    return detalhes


def _ao_gravar(sessao, _contexto):
    usuario_id, usuario_nome = _usuario()
    agora = datetime.now().replace(microsecond=0)
    linhas = []
    for objetos, acao in ((sessao.new, "criou"), (sessao.dirty, "alterou"), (sessao.deleted, "apagou")):
        for obj in list(objetos):
            info = RASTREADOS.get(type(obj))
            if info is None:
                continue
            if acao == "alterou" and not sessao.is_modified(obj, include_collections=False):
                continue
            detalhes = _linha(sessao, obj, acao, info[1])
            if acao == "alterou" and not detalhes:
                continue
            empresa = _empresa_do(obj)
            linhas.append({
                "quando": agora, "usuario_id": usuario_id, "usuario_nome": usuario_nome, "acao": acao,
                "tipo": info[0], "objeto_id": getattr(obj, "id", None),
                "empresa_id": empresa.id if empresa is not None else None,
                "empresa_nome": empresa.razao_social if empresa is not None else None,
                "detalhes": "\n".join(detalhes) or None,
            })
    if linhas:
        sessao.connection().execute(m.RegistroAlteracao.__table__.insert(), linhas)


def registrar_entrada(usuario):
    """Login com sucesso também entra no histórico."""
    m.db.session.execute(m.RegistroAlteracao.__table__.insert(), [{
        "quando": datetime.now().replace(microsecond=0), "usuario_id": usuario.id, "usuario_nome": usuario.nome,
        "acao": "entrou", "tipo": "Acesso ao sistema", "objeto_id": None, "empresa_id": None,
        "empresa_nome": None, "detalhes": None}])
    m.db.session.commit()


def ativar():
    if not event.contains(Session, "after_flush", _ao_gravar):
        event.listen(Session, "after_flush", _ao_gravar)

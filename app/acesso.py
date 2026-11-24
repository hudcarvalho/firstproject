"""Quem vê quais empresas.

Administradores veem e alteram tudo. Os demais usuários veem só as empresas em que o
Responsável ligado ao seu usuário (Cadastros → Usuários) está em algum módulo (ex.: Resp.
Contábil). Usuário sem Responsável ligado não vê nenhuma empresa.
"""
from flask import abort, g, has_request_context
from flask_login import current_user

from .models import Empresa, EmpresaModulo, db


def acesso_total():
    return bool(getattr(current_user, "is_authenticated", False) and current_user.admin)


def ids_permitidos():
    """None = todas (administrador); senão o conjunto de ids das empresas do usuário."""
    if not has_request_context() or acesso_total():  # fora de uma tela (comandos, testes): sem restrição
        return None
    if "empresas_permitidas" not in g:
        resp = getattr(current_user, "responsavel_id", None)
        ids = set()
        if resp:
            ids = {i for (i,) in db.session.query(EmpresaModulo.empresa_id).filter_by(responsavel_id=resp)}
        g.empresas_permitidas = ids
    return g.empresas_permitidas


def filtrar(consulta, coluna=None):
    """Restringe uma consulta às empresas do usuário (coluna = Empresa.id ou um empresa_id)."""
    ids = ids_permitidos()
    if ids is None:
        return consulta
    return consulta.filter((coluna if coluna is not None else Empresa.id).in_(ids or [0]))


def pode(empresa_id):
    ids = ids_permitidos()
    return ids is None or empresa_id in ids


def exigir(empresa):
    """Empresa de outro responsável: responde como se não existisse."""
    if empresa is None or not pode(empresa.id):
        abort(404)
    return empresa

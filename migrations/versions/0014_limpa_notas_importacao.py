"""Apaga das observações as linhas que a importação de planilha escrevia sozinha
("Responsável na planilha: …" e "Regime na planilha: …")

Revision ID: 0014_limpa_notas_importacao
Revises: 0013_historico_alteracoes
Create Date: 2026-11-25 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0014_limpa_notas_importacao'
down_revision = '0013_historico_alteracoes'
branch_labels = None
depends_on = None

PREFIXOS = ("Responsável na planilha:", "Regime na planilha:")


def limpar(texto):
    linhas = [l for l in (texto or "").splitlines() if not l.strip().startswith(PREFIXOS)]
    return "\n".join(linhas).strip() or None


def upgrade():
    conexao = op.get_bind()
    empresa = sa.table('empresa', sa.column('id', sa.Integer), sa.column('observacoes', sa.Text))
    for id_, obs in conexao.execute(sa.select(empresa.c.id, empresa.c.observacoes)
                                    .where(empresa.c.observacoes.like('%na planilha:%'))).all():
        novo = limpar(obs)
        if novo != obs:
            conexao.execute(empresa.update().where(empresa.c.id == id_).values(observacoes=novo))


def downgrade():
    pass  # as anotações apagadas não voltam

"""Tributação opcional: empresas "A definir" ficam em branco e o regime "A definir" é apagado

Revision ID: 0015_tributacao_em_branco
Revises: 0014_limpa_notas_importacao
Create Date: 2026-11-26 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0015_tributacao_em_branco'
down_revision = '0014_limpa_notas_importacao'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('empresa') as batch:
        batch.alter_column('regime_id', existing_type=sa.Integer(), nullable=True)
    conexao = op.get_bind()
    regime = sa.table('regime_tributario', sa.column('id', sa.Integer), sa.column('nome', sa.String))
    ids = [i for (i,) in conexao.execute(sa.select(regime.c.id).where(regime.c.nome == 'A definir'))]
    if ids:
        empresa = sa.table('empresa', sa.column('regime_id', sa.Integer))
        ligacao = sa.table('regime_obrigacao', sa.column('regime_id', sa.Integer))
        conexao.execute(empresa.update().where(empresa.c.regime_id.in_(ids)).values(regime_id=None))
        conexao.execute(ligacao.delete().where(ligacao.c.regime_id.in_(ids)))
        conexao.execute(regime.delete().where(regime.c.id.in_(ids)))


def downgrade():
    conexao = op.get_bind()
    regime = sa.table('regime_tributario', sa.column('id', sa.Integer), sa.column('nome', sa.String),
                      sa.column('descricao', sa.String), sa.column('ativo', sa.Boolean))
    conexao.execute(regime.insert().values(nome='A definir', descricao='Empresas sem tributação', ativo=True))
    rid = conexao.execute(sa.select(regime.c.id).where(regime.c.nome == 'A definir')).scalar()
    empresa = sa.table('empresa', sa.column('regime_id', sa.Integer))
    conexao.execute(empresa.update().where(empresa.c.regime_id.is_(None)).values(regime_id=rid))
    with op.batch_alter_table('empresa') as batch:
        batch.alter_column('regime_id', existing_type=sa.Integer(), nullable=False)

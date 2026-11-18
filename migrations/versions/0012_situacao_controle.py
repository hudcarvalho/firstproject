"""Situação do controle por módulo: sem movimento, ex-cliente ou encerrada (substitui sem_movimento)

Revision ID: 0012_situacao_controle
Revises: 0011_lalur_quotas
Create Date: 2026-11-18 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0012_situacao_controle'
down_revision = '0011_lalur_quotas'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('empresa_modulo') as batch:
        batch.add_column(sa.Column('situacao', sa.String(length=20), nullable=True))
    op.execute("UPDATE empresa_modulo SET situacao = 'sem_movimento' WHERE sem_movimento")
    with op.batch_alter_table('empresa_modulo') as batch:
        batch.drop_column('sem_movimento')


def downgrade():
    with op.batch_alter_table('empresa_modulo') as batch:
        batch.add_column(sa.Column('sem_movimento', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE empresa_modulo SET sem_movimento = TRUE WHERE situacao = 'sem_movimento'")
    with op.batch_alter_table('empresa_modulo') as batch:
        batch.drop_column('situacao')

"""empresa sem movimento (por módulo)

Revision ID: 0008_sem_movimento
Revises: 0007_obrigacoes_imposto
Create Date: 2026-10-02 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0008_sem_movimento'
down_revision = '0007_obrigacoes_imposto'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('empresa_modulo', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sem_movimento', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('empresa_modulo', schema=None) as batch_op:
        batch_op.drop_column('sem_movimento')

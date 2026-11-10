"""Aba Obrigações: datas de DEFIS, ECD, ECF e IBGE por empresa e ano

Revision ID: 0010_obrigacao_anual
Revises: 0009_lalur
Create Date: 2026-11-10 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0010_obrigacao_anual'
down_revision = '0009_lalur'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'obrigacao_anual',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('ano', sa.Integer(), nullable=False),
        sa.Column('defis', sa.Date(), nullable=True),
        sa.Column('ecd', sa.Date(), nullable=True),
        sa.Column('ecf', sa.Date(), nullable=True),
        sa.Column('ibge', sa.Date(), nullable=True),
        sa.Column('observacao', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id'], name=op.f('fk_obrigacao_anual_empresa_id_empresa')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_obrigacao_anual')),
        sa.UniqueConstraint('empresa_id', 'ano', name=op.f('uq_obrigacao_anual_empresa_id_ano')),
    )


def downgrade():
    op.drop_table('obrigacao_anual')

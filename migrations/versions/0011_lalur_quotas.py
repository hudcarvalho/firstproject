"""LALUR: número de quotas do IRPJ/CSLL e envio de cada quota ao cliente

Revision ID: 0011_lalur_quotas
Revises: 0010_obrigacao_anual
Create Date: 2026-11-17 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0011_lalur_quotas'
down_revision = '0010_obrigacao_anual'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('lalur_apuracao') as batch:
        batch.add_column(sa.Column('quotas', sa.Integer(), nullable=True))
    op.create_table(
        'lalur_quota_envio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('apuracao_id', sa.Integer(), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('enviado_em', sa.Date(), nullable=False),
        sa.Column('enviado_por', sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(['apuracao_id'], ['lalur_apuracao.id'],
                                name=op.f('fk_lalur_quota_envio_apuracao_id_lalur_apuracao')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lalur_quota_envio')),
        sa.UniqueConstraint('apuracao_id', 'numero', name=op.f('uq_lalur_quota_envio_apuracao_id_numero')),
    )


def downgrade():
    op.drop_table('lalur_quota_envio')
    with op.batch_alter_table('lalur_apuracao') as batch:
        batch.drop_column('quotas')

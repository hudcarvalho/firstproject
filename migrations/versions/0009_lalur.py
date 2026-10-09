"""LALUR: apurações, adições/exclusões e saldos de abertura

Revision ID: 0009_lalur
Revises: 0008_sem_movimento
Create Date: 2026-10-09 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0009_lalur'
down_revision = '0008_sem_movimento'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lalur_saldo_inicial',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('prejuizo_fiscal', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('base_negativa', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id'], name=op.f('fk_lalur_saldo_inicial_empresa_id_empresa')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lalur_saldo_inicial')),
        sa.UniqueConstraint('empresa_id', name=op.f('uq_lalur_saldo_inicial_empresa_id')),
    )
    op.create_table(
        'lalur_apuracao',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('ano', sa.Integer(), nullable=False),
        sa.Column('periodo', sa.Integer(), nullable=False),
        sa.Column('lucro_antes', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('compensar', sa.Boolean(), nullable=False),
        sa.Column('aliquota_csll', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('irpj_deduzir', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('csll_deduzir', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id'], name=op.f('fk_lalur_apuracao_empresa_id_empresa')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lalur_apuracao')),
        sa.UniqueConstraint('empresa_id', 'ano', 'periodo', name=op.f('uq_lalur_apuracao_empresa_id_ano_periodo')),
    )
    with op.batch_alter_table('lalur_apuracao', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lalur_apuracao_empresa_id'), ['empresa_id'], unique=False)
    op.create_table(
        'lalur_lancamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('apuracao_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=10), nullable=False),
        sa.Column('tributo', sa.String(length=5), nullable=False),
        sa.Column('descricao', sa.String(length=200), nullable=False),
        sa.Column('valor', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['apuracao_id'], ['lalur_apuracao.id'], name=op.f('fk_lalur_lancamento_apuracao_id_lalur_apuracao')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lalur_lancamento')),
    )
    with op.batch_alter_table('lalur_lancamento', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lalur_lancamento_apuracao_id'), ['apuracao_id'], unique=False)


def downgrade():
    with op.batch_alter_table('lalur_lancamento', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lalur_lancamento_apuracao_id'))
    op.drop_table('lalur_lancamento')
    with op.batch_alter_table('lalur_apuracao', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lalur_apuracao_empresa_id'))
    op.drop_table('lalur_apuracao')
    op.drop_table('lalur_saldo_inicial')

"""Dono do sistema e histórico de alterações

Revision ID: 0013_historico_alteracoes
Revises: 0012_situacao_controle
Create Date: 2026-11-24 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0013_historico_alteracoes'
down_revision = '0012_situacao_controle'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('usuario') as batch:
        batch.add_column(sa.Column('dono', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'registro_alteracao',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quando', sa.DateTime(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('usuario_nome', sa.String(length=120), nullable=True),
        sa.Column('acao', sa.String(length=20), nullable=False),
        sa.Column('tipo', sa.String(length=60), nullable=False),
        sa.Column('objeto_id', sa.Integer(), nullable=True),
        sa.Column('empresa_id', sa.Integer(), nullable=True),
        sa.Column('empresa_nome', sa.String(length=200), nullable=True),
        sa.Column('detalhes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_registro_alteracao')),
    )
    op.create_index(op.f('ix_registro_alteracao_quando'), 'registro_alteracao', ['quando'])
    op.create_index(op.f('ix_registro_alteracao_usuario_id'), 'registro_alteracao', ['usuario_id'])
    op.create_index(op.f('ix_registro_alteracao_empresa_id'), 'registro_alteracao', ['empresa_id'])


def downgrade():
    op.drop_table('registro_alteracao')
    with op.batch_alter_table('usuario') as batch:
        batch.drop_column('dono')

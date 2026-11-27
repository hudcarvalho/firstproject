"""Alertas pessoais (cada usuário vê só os seus)

Revision ID: 0017_alertas
Revises: 0016_historico_horario_brasilia
Create Date: 2026-11-27 15:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0017_alertas'
down_revision = '0016_historico_horario_brasilia'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'alerta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('texto', sa.String(length=500), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.Column('concluido_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id'], name=op.f('fk_alerta_empresa_id_empresa')),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], name=op.f('fk_alerta_usuario_id_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_alerta')),
    )
    op.create_index(op.f('ix_alerta_usuario_id'), 'alerta', ['usuario_id'])


def downgrade():
    op.drop_table('alerta')

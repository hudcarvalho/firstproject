"""Horário opcional nos alertas pessoais

Revision ID: 0018_alerta_hora
Revises: 0017_alertas
Create Date: 2026-11-27 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '0018_alerta_hora'
down_revision = '0017_alertas'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alerta') as batch_op:
        batch_op.add_column(sa.Column('hora', sa.Time(), nullable=True))


def downgrade():
    with op.batch_alter_table('alerta') as batch_op:
        batch_op.drop_column('hora')

"""Histórico de alterações: registros gravados em UTC (horário do servidor) passam para o horário
de Brasília (−3 h). A partir daqui o sistema todo grava no horário de Brasília.

Revision ID: 0016_historico_horario_brasilia
Revises: 0015_tributacao_em_branco
Create Date: 2026-11-27 12:00:00

"""
from datetime import timedelta

from alembic import op
import sqlalchemy as sa


revision = '0016_historico_horario_brasilia'
down_revision = '0015_tributacao_em_branco'
branch_labels = None
depends_on = None

TABELA = sa.table('registro_alteracao', sa.column('id', sa.Integer), sa.column('quando', sa.DateTime))


def _deslocar(horas):
    conexao = op.get_bind()
    for id_, quando in conexao.execute(sa.select(TABELA.c.id, TABELA.c.quando)).all():
        if quando is not None:
            conexao.execute(TABELA.update().where(TABELA.c.id == id_).values(quando=quando + timedelta(hours=horas)))


def upgrade():
    _deslocar(-3)


def downgrade():
    _deslocar(3)

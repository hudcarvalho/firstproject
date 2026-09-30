from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.models import db


def test_migracoes_correspondem_aos_modelos(app):
    """Falha se app/models.py mudou sem gerar a migração correspondente."""
    with app.app_context(), db.engine.connect() as conn:
        diferencas = compare_metadata(MigrationContext.configure(conn), db.metadata)
    assert diferencas == []

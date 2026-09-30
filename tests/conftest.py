import pytest

from app import create_app
from app.models import Usuario, db

SENHA = "senha-segura-123"


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False})
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def criar_usuario(app, email, admin=True, nome="Usuário"):
    with app.app_context():
        u = Usuario(nome=nome, email=email, admin=admin, ativo=True)
        u.definir_senha(SENHA)
        db.session.add(u)
        db.session.commit()


def entrar(client, email, senha=SENHA):
    return client.post("/login", data={"email": email, "senha": senha})


@pytest.fixture
def anonimo(app):
    return app.test_client()


@pytest.fixture
def client(app):
    """Cliente autenticado como administrador."""
    criar_usuario(app, "admin@escritorio.com", admin=True, nome="Admin")
    c = app.test_client()
    assert entrar(c, "admin@escritorio.com").status_code == 302
    return c

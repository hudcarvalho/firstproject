import hashlib
import os
import secrets

from flask import Flask, url_for
from flask_migrate import Migrate, stamp, upgrade
from sqlalchemy import inspect
from werkzeug.middleware.proxy_fix import ProxyFix

from .competencia import fmt_competencia, fmt_documento, fmt_valor, input_competencia
from .models import ESFERAS, PERIODICIDADES, Modulo, db

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
# Revisão equivalente ao esquema que a versão sem migrações (com módulos, sem login) criava.
REVISAO_BASE = "0001_esquema_inicial"


def _secret_key(instance_path):
    """SECRET_KEY do ambiente ou, se ausente, uma chave aleatória guardada em instance/."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    caminho = os.path.join(instance_path, "secret_key")
    if not os.path.exists(caminho):
        with open(caminho, "w") as f:
            f.write(secrets.token_hex(32))
    with open(caminho) as f:
        return f.read().strip()


def _database_url(instance_path):
    url = os.environ.get("DATABASE_URL") or "sqlite:///" + os.path.join(instance_path, "controle.db")
    # Provedores costumam fornecer "postgres://"; o SQLAlchemy usa o driver psycopg 3.
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo):]
    return url


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    cookie_seguro = os.environ.get("COOKIE_SECURE") == "1"
    app.config.update(
        SECRET_KEY=_secret_key(app.instance_path),
        SQLALCHEMY_DATABASE_URI=_database_url(app.instance_path),
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # uploads (importação de planilhas)
        SESSION_COOKIE_SECURE=cookie_seguro,
        REMEMBER_COOKIE_SECURE=cookie_seguro,
    )
    if config:
        app.config.update(config)

    if os.environ.get("PROXY_FIX") == "1":  # atrás de proxy HTTPS (Render, Railway, nginx…)
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    Migrate(app, db, directory=MIGRATIONS_DIR, render_as_batch=True)

    from .auth import init_auth
    init_auth(app)

    app.jinja_env.filters["competencia"] = fmt_competencia
    app.jinja_env.filters["input_competencia"] = input_competencia
    app.jinja_env.filters["documento"] = fmt_documento
    app.jinja_env.filters["valor"] = fmt_valor
    app.jinja_env.filters["data_br"] = lambda d: d.strftime("%d/%m/%Y") if d else "—"
    app.jinja_env.globals.update(PERIODICIDADES=PERIODICIDADES, ESFERAS=ESFERAS)

    @app.context_processor
    def modulos_no_menu():
        return {"modulos_ativos": Modulo.ativos()}

    # Endereço dos arquivos estáticos com a "impressão digital" do conteúdo (?v=...), para o
    # navegador baixar de novo sempre que o arquivo mudar em vez de usar a cópia em cache.
    versoes = {}

    def estatico(arquivo):
        if arquivo not in versoes or app.debug:
            caminho = os.path.join(app.static_folder, arquivo)
            with open(caminho, "rb") as f:
                versoes[arquivo] = hashlib.md5(f.read()).hexdigest()[:10]
        return url_for("static", filename=arquivo, v=versoes[arquivo])

    app.jinja_env.globals["estatico"] = estatico

    from .routes import bp
    app.register_blueprint(bp)

    from .distribuicao import bp as bp_distribuicao
    app.register_blueprint(bp_distribuicao)

    from .cli import registrar_comandos
    registrar_comandos(app)

    # Para rodar "flask db ..." sem mexer no banco antes.
    if os.environ.get("CONTROLE_SKIP_DB_INIT") != "1":
        with app.app_context():
            preparar_banco()

    return app


def preparar_banco():
    """Cria/atualiza o banco pelas migrações e carrega os dados iniciais."""
    insp = inspect(db.engine)
    if insp.has_table("empresa"):
        colunas = {c["name"] for c in insp.get_columns("empresa")}
        if "escriturada_ate" in colunas:
            raise RuntimeError(
                "Banco criado pela primeira versão (sem módulos). "
                "Apague instance/controle.db e inicie novamente."
            )
        if not insp.has_table("alembic_version"):
            # Banco criado antes das migrações: aproveita os dados existentes.
            revisao = "0002_usuarios" if insp.has_table("usuario") else REVISAO_BASE
            stamp(directory=MIGRATIONS_DIR, revision=revisao)
    upgrade(directory=MIGRATIONS_DIR)

    from .seed import seed
    seed()

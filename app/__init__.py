import os

from flask import Flask

from .competencia import fmt_competencia, input_competencia
from sqlalchemy import inspect

from .models import ESFERAS, PERIODICIDADES, Modulo, db


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-troque-em-producao"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "controle.db")
        ),
    )
    if config:
        app.config.update(config)

    db.init_app(app)

    app.jinja_env.filters["competencia"] = fmt_competencia
    app.jinja_env.filters["input_competencia"] = input_competencia
    app.jinja_env.filters["data_br"] = lambda d: d.strftime("%d/%m/%Y") if d else "—"
    app.jinja_env.globals.update(PERIODICIDADES=PERIODICIDADES, ESFERAS=ESFERAS)

    @app.context_processor
    def modulos_no_menu():
        return {"modulos_ativos": Modulo.ativos()}

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        colunas = {c["name"] for c in inspect(db.engine).get_columns("empresa")} \
            if inspect(db.engine).has_table("empresa") else set()
        if "escriturada_ate" in colunas:
            raise RuntimeError(
                "Banco criado pela versão anterior (sem módulos). "
                "Apague instance/controle.db e inicie novamente."
            )
        db.create_all()
        from .seed import seed
        seed()

    return app

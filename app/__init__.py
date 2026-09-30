import os

from flask import Flask

from .competencia import fmt_competencia, input_competencia
from .models import ESFERAS, PERIODICIDADES, db


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

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()
        from .seed import seed
        seed()

    return app

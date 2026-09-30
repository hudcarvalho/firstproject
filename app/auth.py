"""Login, primeiro acesso, troca de senha e cadastro de usuários.

Todas as telas exigem login, exceto as listadas em ENDPOINTS_PUBLICOS. Parametrização e
cadastros gerais exigem usuário administrador (ENDPOINTS_ADMIN).
"""
import time
from collections import defaultdict
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFProtect

from .models import Responsavel, Usuario, db

bp = Blueprint("auth", __name__)
login_manager = LoginManager()
csrf = CSRFProtect()

ENDPOINTS_PUBLICOS = {"auth.login", "auth.primeiro_acesso", "auth.saude", "static"}
ENDPOINTS_ADMIN = {
    "main.obrigacao_form", "main.regimes_lista", "main.regime_form",
    "main.responsaveis_lista", "main.responsavel_form", "main.modulos_lista", "main.modulo_form",
    "auth.usuarios_lista", "auth.usuario_form",
}
ENDPOINTS_ADMIN_SO_POST = {"main.matriz"}  # qualquer um vê; só admin salva

# Proteção simples contra tentativa e erro de senha (por e-mail, em memória).
MAX_TENTATIVAS = 5
JANELA_BLOQUEIO = 10 * 60
_falhas = defaultdict(list)


def init_auth(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Entre com seu usuário para continuar."
    login_manager.login_message_category = "info"
    csrf.init_app(app)
    app.register_blueprint(bp)

    @app.before_request
    def exigir_login():
        ep = request.endpoint
        if ep in ENDPOINTS_PUBLICOS or ep is None:
            return None
        if Usuario.query.first() is None:
            return redirect(url_for("auth.primeiro_acesso"))
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        precisa_admin = ep in ENDPOINTS_ADMIN or (
            ep in ENDPOINTS_ADMIN_SO_POST and request.method == "POST")
        if precisa_admin and not current_user.admin:
            abort(403)
        return None

    @app.errorhandler(403)
    def proibido(_):
        return render_template("erro.html", titulo="Acesso restrito",
                               mensagem="Esta tela é exclusiva de administradores."), 403

    @app.errorhandler(404)
    def nao_encontrado(_):
        return render_template("erro.html", titulo="Página não encontrada",
                               mensagem="O endereço acessado não existe."), 404


@login_manager.user_loader
def carregar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


def _destino_seguro(url):
    """Só aceita redirecionar para caminhos do próprio sistema."""
    if not url:
        return None
    partes = urlsplit(url)
    if partes.scheme or partes.netloc or not url.startswith("/") or url.startswith("//"):
        return None
    return url


def _bloqueado(email):
    agora = time.time()
    _falhas[email] = [t for t in _falhas[email] if agora - t < JANELA_BLOQUEIO]
    return len(_falhas[email]) >= MAX_TENTATIVAS


def _validar_senha(senha, confirmacao):
    if len(senha or "") < Usuario.SENHA_MINIMA:
        return f"A senha deve ter pelo menos {Usuario.SENHA_MINIMA} caracteres."
    if senha != confirmacao:
        return "A confirmação não confere com a senha."
    return None


# ---------------------------------------------------------------- Login / logout

@bp.route("/saude")
def saude():
    """Verificação de funcionamento usada pela hospedagem."""
    return "ok"


@bp.route("/login", methods=["GET", "POST"])
def login():
    if Usuario.query.first() is None:
        return redirect(url_for("auth.primeiro_acesso"))
    if current_user.is_authenticated:
        return redirect(url_for("main.inicio"))
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        if _bloqueado(email):
            flash("Muitas tentativas. Aguarde alguns minutos e tente novamente.", "danger")
        else:
            usuario = Usuario.query.filter_by(email=email).first()
            if usuario and usuario.ativo and usuario.confere_senha(senha):
                _falhas.pop(email, None)
                login_user(usuario, remember=request.form.get("lembrar") == "on")
                return redirect(_destino_seguro(request.args.get("next")) or url_for("main.inicio"))
            _falhas[email].append(time.time())
            flash("E-mail ou senha incorretos.", "danger")
    return render_template("auth/login.html", email=email)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Cria o primeiro administrador. Só funciona enquanto não houver nenhum usuário."""
    if Usuario.query.first() is not None:
        return redirect(url_for("auth.login"))
    f = request.form
    if request.method == "POST":
        nome, email = f.get("nome", "").strip(), f.get("email", "").strip().lower()
        erro = None if nome and "@" in email else "Informe nome e um e-mail válido."
        erro = erro or _validar_senha(f.get("senha"), f.get("confirmacao"))
        if erro:
            flash(erro, "danger")
        else:
            usuario = Usuario(nome=nome, email=email, admin=True, ativo=True)
            usuario.definir_senha(f["senha"])
            db.session.add(usuario)
            db.session.commit()
            login_user(usuario)
            flash("Administrador criado. Bem-vindo!", "success")
            return redirect(url_for("main.inicio"))
    return render_template("auth/primeiro_acesso.html", form=f)


@bp.route("/minha-senha", methods=["GET", "POST"])
@login_required
def minha_senha():
    if request.method == "POST":
        f = request.form
        if not current_user.confere_senha(f.get("atual", "")):
            flash("Senha atual incorreta.", "danger")
        elif erro := _validar_senha(f.get("nova"), f.get("confirmacao")):
            flash(erro, "danger")
        else:
            current_user.definir_senha(f["nova"])
            db.session.commit()
            flash("Senha alterada.", "success")
            return redirect(url_for("main.inicio"))
    return render_template("auth/minha_senha.html")


# ---------------------------------------------------------------- Usuários (admin)

@bp.route("/usuarios")
def usuarios_lista():
    return render_template("auth/usuarios_lista.html",
                           usuarios=Usuario.query.order_by(Usuario.nome).all())


@bp.route("/usuarios/novo", methods=["GET", "POST"], defaults={"id": None})
@bp.route("/usuarios/<int:id>/editar", methods=["GET", "POST"])
def usuario_form(id):
    usuario = db.session.get(Usuario, id) if id else Usuario(ativo=True, admin=False)
    if usuario is None:
        abort(404)
    responsaveis = Responsavel.query.filter_by(ativo=True).order_by(Responsavel.nome).all()
    if request.method == "POST":
        f = request.form
        nome, email = f.get("nome", "").strip(), f.get("email", "").strip().lower()
        admin, ativo = f.get("admin") == "on", f.get("ativo") == "on"
        existente = Usuario.query.filter_by(email=email).first()
        erros = []
        if not nome or "@" not in email:
            erros.append("Informe nome e um e-mail válido.")
        elif existente and existente.id != usuario.id:
            erros.append("Já existe um usuário com esse e-mail.")
        if not id or f.get("senha"):
            if erro := _validar_senha(f.get("senha"), f.get("confirmacao")):
                erros.append(erro)
        if usuario.id == current_user.id and (not admin or not ativo):
            erros.append("Você não pode remover o próprio acesso de administrador.")
        if erros:
            for e in erros:
                flash(e, "danger")
        else:
            usuario.nome, usuario.email, usuario.admin, usuario.ativo = nome, email, admin, ativo
            usuario.responsavel_id = int(f["responsavel_id"]) if f.get("responsavel_id") else None
            if f.get("senha"):
                usuario.definir_senha(f["senha"])
            if not id:
                db.session.add(usuario)
            db.session.commit()
            flash("Usuário salvo.", "success")
            return redirect(url_for("auth.usuarios_lista"))
    return render_template("auth/usuario_form.html", usuario=usuario, responsaveis=responsaveis)

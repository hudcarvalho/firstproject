"""Comandos de manutenção: `flask --app run <comando>`."""
import click

from .models import Usuario, db


def registrar_comandos(app):
    @app.cli.command("criar-admin")
    @click.option("--nome", prompt="Nome")
    @click.option("--email", prompt="E-mail")
    @click.password_option("--senha", prompt="Senha")
    def criar_admin(nome, email, senha):
        """Cria um usuário administrador."""
        email = email.strip().lower()
        if Usuario.query.filter_by(email=email).first():
            raise click.ClickException("Já existe um usuário com esse e-mail.")
        if len(senha) < Usuario.SENHA_MINIMA:
            raise click.ClickException(f"A senha deve ter pelo menos {Usuario.SENHA_MINIMA} caracteres.")
        usuario = Usuario(nome=nome.strip(), email=email, admin=True, ativo=True)
        usuario.definir_senha(senha)
        db.session.add(usuario)
        db.session.commit()
        click.echo(f"Administrador {email} criado.")

    @app.cli.command("redefinir-senha")
    @click.argument("email")
    @click.password_option("--senha", prompt="Nova senha")
    def redefinir_senha(email, senha):
        """Redefine a senha de um usuário (e o reativa)."""
        usuario = Usuario.query.filter_by(email=email.strip().lower()).first()
        if usuario is None:
            raise click.ClickException("Usuário não encontrado.")
        if len(senha) < Usuario.SENHA_MINIMA:
            raise click.ClickException(f"A senha deve ter pelo menos {Usuario.SENHA_MINIMA} caracteres.")
        usuario.definir_senha(senha)
        usuario.ativo = True
        db.session.commit()
        click.echo(f"Senha de {usuario.email} redefinida.")

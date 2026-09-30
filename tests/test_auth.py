from app.models import Usuario, db
from tests.conftest import SENHA, criar_usuario, entrar


def test_sem_usuarios_vai_para_primeiro_acesso(anonimo):
    r = anonimo.get("/contabil/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/primeiro-acesso")
    assert anonimo.get("/login").headers["Location"].endswith("/primeiro-acesso")


def test_primeiro_acesso_cria_admin_e_depois_fecha(anonimo, app):
    r = anonimo.post("/primeiro-acesso", data={"nome": "Hudson", "email": "Hud@Escritorio.com",
                                               "senha": SENHA, "confirmacao": SENHA})
    assert r.status_code == 302
    with app.app_context():
        u = Usuario.query.one()
        assert u.admin and u.email == "hud@escritorio.com" and u.senha_hash != SENHA
    assert anonimo.get("/contabil/").status_code == 200  # já entra logado
    assert anonimo.get("/primeiro-acesso").status_code == 302


def test_primeiro_acesso_valida_senha(anonimo, app):
    r = anonimo.post("/primeiro-acesso", data={"nome": "X", "email": "x@x.com",
                                               "senha": "curta", "confirmacao": "curta"})
    assert "pelo menos 8" in r.get_data(as_text=True)
    with app.app_context():
        assert Usuario.query.count() == 0


def test_login_obrigatorio_e_logout(anonimo, app):
    criar_usuario(app, "ana@x.com", admin=False)
    r = anonimo.get("/contabil/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert "incorretos" in entrar(anonimo, "ana@x.com", "errada").get_data(as_text=True)
    assert entrar(anonimo, "ana@x.com").status_code == 302
    assert anonimo.get("/contabil/").status_code == 200
    anonimo.post("/logout")
    assert anonimo.get("/contabil/").status_code == 302


def test_usuario_inativo_nao_entra(anonimo, app):
    criar_usuario(app, "ana@x.com", admin=False)
    with app.app_context():
        Usuario.query.one().ativo = False
        db.session.commit()
    assert entrar(anonimo, "ana@x.com").status_code == 200


def test_bloqueio_por_tentativas(anonimo, app):
    criar_usuario(app, "bloq@x.com")
    for _ in range(5):
        entrar(anonimo, "bloq@x.com", "errada")
    r = entrar(anonimo, "bloq@x.com")  # senha certa, mas bloqueado
    assert "Muitas tentativas" in r.get_data(as_text=True)


def test_next_externo_ignorado(anonimo, app):
    criar_usuario(app, "ana@x.com")
    r = anonimo.post("/login?next=https://malicioso.com/", data={"email": "ana@x.com", "senha": SENHA})
    assert "malicioso" not in r.headers["Location"]


def test_usuario_comum_nao_acessa_parametrizacao(anonimo, app):
    criar_usuario(app, "ana@x.com", admin=False)
    entrar(anonimo, "ana@x.com")
    for url in ["/usuarios", "/modulos", "/regimes", "/responsaveis", "/contabil/obrigacoes/nova"]:
        assert anonimo.get(url).status_code == 403, url
    assert anonimo.get("/contabil/matriz").status_code == 200
    assert anonimo.post("/contabil/matriz", data={}).status_code == 403
    html = anonimo.get("/contabil/").get_data(as_text=True)
    assert "Usuários" not in html


def test_admin_cadastra_usuario(client, app):
    r = client.post("/usuarios/novo", data={"nome": "Bia", "email": "bia@x.com", "senha": SENHA,
                                            "confirmacao": SENHA, "ativo": "on"})
    assert r.status_code == 302
    c = app.test_client()
    assert entrar(c, "bia@x.com").status_code == 302


def test_admin_nao_remove_proprio_acesso(client, app):
    with app.app_context():
        uid = Usuario.query.filter_by(email="admin@escritorio.com").one().id
    r = client.post(f"/usuarios/{uid}/editar", data={"nome": "Admin", "email": "admin@escritorio.com", "ativo": "on"})
    assert "próprio acesso" in r.get_data(as_text=True)


def test_trocar_senha(client):
    r = client.post("/minha-senha", data={"atual": SENHA, "nova": "outra-senha-456", "confirmacao": "outra-senha-456"})
    assert r.status_code == 302


def test_csrf_ativo_fora_dos_testes(app):
    app.config["WTF_CSRF_ENABLED"] = True
    criar_usuario(app, "ana@x.com")
    assert entrar(app.test_client(), "ana@x.com").status_code == 400


def test_saude(anonimo):
    assert anonimo.get("/saude").get_data(as_text=True) == "ok"

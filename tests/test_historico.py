"""Histórico de alterações: grava quem fez o quê; só o dono do sistema vê, e os outros nem sabem."""
from app.models import RegistroAlteracao, Usuario, db
from tests.conftest import criar_usuario, entrar
from tests.test_fluxo import CNPJ, _cadastrar, _regime


def _dono(app, email="admin@escritorio.com"):
    r = app.test_cli_runner().invoke(args=["definir-dono", email])
    assert "agora é o dono do sistema" in r.output


def test_registra_quem_alterou_o_que(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        rid = _regime("Lucro Presumido").id
    client.post(f"/empresas/{eid}/editar", data={"razao_social": "ACME Ltda", "cnpj": CNPJ, "regime_id": rid,
                                                "ativo": "on", "concluido_contabil": "2026-09",
                                                "observacoes": "Nova observação"})
    with app.app_context():
        regs = RegistroAlteracao.query.order_by(RegistroAlteracao.id).all()
        criou = [r for r in regs if r.acao == "criou" and r.tipo == "Cadastro da empresa"]
        assert criou and criou[0].usuario_nome == "Admin" and criou[0].empresa_nome == "ACME Ltda"
        alterou = [r for r in regs if r.acao == "alterou"]
        texto = "\n".join(r.detalhes for r in alterou)
        assert "Escriturada/concluída até: 06/2026 → 09/2026" in texto
        assert "Observações: — → Nova observação" in texto
        assert all(r.empresa_id == eid for r in alterou)


def test_so_o_dono_ve_e_ninguem_sabe_que_ele_existe(client, app):
    criar_usuario(app, "outro@escritorio.com", admin=True, nome="Outro admin")
    _dono(app)
    # dono vê o histórico (inclusive as entradas no sistema)
    assert "Histórico de alterações" in client.get("/empresas").get_data(as_text=True)
    outro = app.test_client()
    entrar(outro, "outro@escritorio.com")
    html = client.get("/historico/").get_data(as_text=True)
    assert "Outro admin" in html and "entrou" in html
    assert client.get("/historico/?formato=xlsx").mimetype.endswith("spreadsheetml.sheet")
    # outro administrador: sem link, 404 na tela e nada na lista de usuários
    assert "Histórico de alterações" not in outro.get("/empresas").get_data(as_text=True)
    assert outro.get("/historico/").status_code == 404
    lista = outro.get("/usuarios").get_data(as_text=True).lower()
    assert "dono" not in lista and "histórico" not in lista
    # e não consegue mexer no usuário do dono
    with app.app_context():
        dono_id = Usuario.query.filter_by(dono=True).one().id
    form = outro.get(f"/usuarios/{dono_id}/editar").get_data(as_text=True)
    assert 'name="senha"' not in form and "<fieldset disabled>" in form and ">Salvar</button>" not in form
    # o próprio dono continua podendo trocar a senha no cadastro dele
    assert 'name="senha"' in client.get(f"/usuarios/{dono_id}/editar").get_data(as_text=True)
    outro.post(f"/usuarios/{dono_id}/editar", data={"nome": "Admin", "email": "admin@escritorio.com",
                                                   "ativo": "on", "senha": "outrasenha123",
                                                   "confirmacao": "outrasenha123"})
    with app.app_context():
        u = db.session.get(Usuario, dono_id)
        assert u.admin and u.ativo and u.confere_senha("senha-segura-123")


def test_usuario_comum_nao_ve_historico(client, app):
    criar_usuario(app, "comum@escritorio.com", admin=False)
    c = app.test_client()
    entrar(c, "comum@escritorio.com")
    assert c.get("/historico/").status_code == 404

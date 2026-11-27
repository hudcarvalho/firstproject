"""Alertas pessoais: só quem criou vê, a partir da data escolhida, até concluir."""
from datetime import date, timedelta

from app.models import Alerta, Empresa, RegimeTributario, db
from tests.conftest import criar_usuario, entrar


def test_criar_ver_concluir_e_privacidade(client, app):
    hoje = date.today()
    with app.app_context():
        e = Empresa(codigo="29", razao_social="CHAVEIRO ITALIA LTDA", cnpj="11222333000181",
                    regime=RegimeTributario.query.first())
        db.session.add(e)
        db.session.commit()
        eid = e.id
    assert "🔔 Alertas" in client.get("/empresas").get_data(as_text=True)
    client.post("/alertas/", data={"texto": "Cobrar extrato de outubro", "data": hoje.isoformat(),
                                   "empresa": "29 — CHAVEIRO ITALIA LTDA"})
    client.post("/alertas/", data={"texto": "Revisar balancete", "data": (hoje + timedelta(days=5)).isoformat()})
    with app.app_context():
        alertas = {a.texto: a for a in Alerta.query}
        assert alertas["Cobrar extrato de outubro"].empresa_id == eid
        futuro_id = alertas["Revisar balancete"].id
        hoje_id = alertas["Cobrar extrato de outubro"].id
    # aviso no topo só com o de hoje (o futuro ainda não)
    html = client.get("/empresas").get_data(as_text=True)
    assert 'id="meus-alertas"' in html and "Cobrar extrato de outubro" in html and "Revisar balancete" not in html
    assert "Cobrar extrato de outubro" in client.get(f"/empresas/{eid}").get_data(as_text=True)
    # outra pessoa não vê nem mexe
    criar_usuario(app, "outro@x.com", admin=True)
    c = app.test_client()
    entrar(c, "outro@x.com")
    assert "Cobrar extrato" not in c.get("/empresas").get_data(as_text=True)
    assert "Cobrar extrato" not in c.get("/alertas/").get_data(as_text=True)
    assert c.post(f"/alertas/{hoje_id}/concluir").status_code == 404
    # concluir tira do aviso; adiar muda a data
    client.post(f"/alertas/{hoje_id}/concluir")
    assert 'id="meus-alertas"' not in client.get("/empresas").get_data(as_text=True)
    client.post(f"/alertas/{futuro_id}/adiar", data={"data": hoje.isoformat()})
    assert "Revisar balancete" in client.get("/empresas").get_data(as_text=True)
    client.post(f"/alertas/{futuro_id}/excluir")
    client.post(f"/alertas/{hoje_id}/reabrir")
    with app.app_context():
        assert Alerta.query.count() == 1 and Alerta.query.one().concluido_em is None


def test_validacao(client, app):
    r = client.post("/alertas/", data={"texto": "", "data": ""}, follow_redirects=True)
    assert "Escreva o alerta e escolha a data" in r.get_data(as_text=True)
    r = client.post("/alertas/", data={"texto": "X", "data": date.today().isoformat(), "empresa": "Inexistente"},
                    follow_redirects=True)
    assert "não encontrada" in r.get_data(as_text=True)
    with app.app_context():
        assert Alerta.query.count() == 0

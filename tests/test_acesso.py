"""Usuário comum vê e altera só as empresas do responsável ligado a ele; administrador vê tudo."""
from datetime import date

import pytest

from app.models import (Empresa, LalurApuracao, Modulo, ObrigacaoAnual, RegimeTributario, Responsavel, Socio,
                        Usuario, db)
from tests.conftest import criar_usuario, entrar


@pytest.fixture
def cenario(app, client):
    with app.app_context():
        lr = RegimeTributario.query.filter_by(nome="Lucro Real").one()
        contabil = Modulo.query.filter_by(codigo="contabil").one()
        ana, bia = Responsavel(nome="Ana"), Responsavel(nome="Bia")
        a = Empresa(codigo="1", razao_social="EMPRESA DA ANA", cnpj="11222333000181", regime=lr)
        b = Empresa(codigo="2", razao_social="EMPRESA DA BIA", cnpj="45997418000153", regime=lr)
        db.session.add_all([ana, bia, a, b])
        a.controle(contabil, criar=True).responsavel = ana
        b.controle(contabil, criar=True).responsavel = bia
        db.session.flush()
        for e in (a, b):
            db.session.add(Socio(empresa_id=e.id, nome=f"SOCIO {e.codigo}", documento="5299822472" + e.codigo))
            db.session.add(LalurApuracao(empresa_id=e.id, ano=2020, periodo=1, lucro_antes=300000, compensar=True,
                                         aliquota_csll=9, irpj_deduzir=0, csll_deduzir=0, quotas=1))
            db.session.add(ObrigacaoAnual(empresa_id=e.id, ano=2026, defis=date(2026, 3, 30)))
        db.session.commit()
        criar_usuario(app, "ana@escritorio.com", admin=False, nome="Ana")
        u = Usuario.query.filter_by(email="ana@escritorio.com").one()
        u.responsavel_id = ana.id
        criar_usuario(app, "sem@escritorio.com", admin=False, nome="Sem")
        db.session.commit()
        ids = {"a": a.id, "b": b.id, "ana": ana.id, "bia": bia.id,
               "ap_b": LalurApuracao.query.filter_by(empresa_id=b.id).one().id}
    c = app.test_client()
    assert entrar(c, "ana@escritorio.com").status_code == 302
    return c, ids


def test_lista_e_telas_so_das_proprias_empresas(cenario, client):
    c, ids = cenario
    html = c.get("/empresas").get_data(as_text=True)
    assert "EMPRESA DA ANA" in html and "EMPRESA DA BIA" not in html
    assert "+ Nova empresa" not in html and c.get("/empresas/nova").status_code == 403
    assert c.get(f"/empresas/{ids['a']}").status_code == 200
    for url in (f"/empresas/{ids['b']}", f"/empresas/{ids['b']}/contabil", f"/distribuicao/{ids['b']}",
                f"/distribuicao/{ids['b']}/pdf", f"/lalur/{ids['b']}", f"/lalur/{ids['b']}/2020/1"):
        assert c.get(url).status_code == 404, url
    assert c.post(f"/empresas/{ids['b']}/editar", data={"razao_social": "X"}).status_code == 404
    # o administrador continua vendo tudo
    html = client.get("/empresas").get_data(as_text=True)
    assert "EMPRESA DA ANA" in html and "EMPRESA DA BIA" in html
    assert client.get(f"/empresas/{ids['b']}").status_code == 200


def test_obrigacoes_quotas_e_relatorios(cenario):
    c, ids = cenario
    html = c.get("/obrigacoes/?ano=2026").get_data(as_text=True)
    assert "EMPRESA DA ANA" in html and "EMPRESA DA BIA" not in html
    assert c.post("/obrigacoes/salvar", data={"empresa_id": ids["b"], "ano": 2026, "campo": "ecd",
                                             "valor": "01/06/2026"}).status_code == 404
    html = c.get("/lalur/quotas?ano=2020").get_data(as_text=True)
    assert "EMPRESA DA ANA" in html and "EMPRESA DA BIA" not in html
    assert "1 quota(s) de IRPJ/CSLL para enviar" in c.get("/empresas").get_data(as_text=True)  # só a dela
    assert c.post(f"/lalur/quotas/{ids['ap_b']}/1/envio", data={"enviado": "1"}).status_code == 404
    assert c.post(f"/lalur/quotas/{ids['ap_b']}/definir", data={"quotas": "3"}).status_code == 404
    html = c.get("/distribuicao/?busca=empresa").get_data(as_text=True)
    assert "EMPRESA DA BIA" not in html
    assert "EMPRESA DA BIA" not in c.get("/contabil/").get_data(as_text=True)


def test_usuario_comum_nao_troca_o_responsavel(cenario, app):
    c, ids = cenario
    with app.app_context():
        rid = RegimeTributario.query.filter_by(nome="Lucro Real").one().id
    c.post(f"/empresas/{ids['a']}/editar", data={"razao_social": "EMPRESA DA ANA", "cnpj": "11.222.333/0001-81",
                                                "regime_id": rid, "ativo": "on", "responsavel_contabil": ids["bia"],
                                                "concluido_contabil": "2026-08"})
    with app.app_context():
        ctl = db.session.get(Empresa, ids["a"]).controle(Modulo.query.filter_by(codigo="contabil").one())
        assert ctl.responsavel_id == ids["ana"] and ctl.concluido_ate == date(2026, 8, 1)


def test_usuario_comum_nao_altera_tributacao_nem_ativa(cenario, app):
    c, ids = cenario
    html = c.get(f"/empresas/{ids['a']}").get_data(as_text=True)
    assert 'name="regime_id" disabled' in html and 'name="ativo" id="ativo" checked disabled' in html
    with app.app_context():
        presumido = RegimeTributario.query.filter_by(nome="Lucro Presumido").one().id
    # tenta mudar a tributação e inativar (sem "ativo") enviando direto
    r = c.post(f"/empresas/{ids['a']}/editar", data={"razao_social": "EMPRESA DA ANA", "cnpj": "11.222.333/0001-81",
                                                    "regime_id": presumido, "concluido_contabil": "2026-09"})
    assert r.status_code == 302
    with app.app_context():
        e = db.session.get(Empresa, ids["a"])
        assert e.regime.nome == "Lucro Real" and e.ativo
        assert e.controle(Modulo.query.filter_by(codigo="contabil").one()).concluido_ate == date(2026, 9, 1)


def test_sem_responsavel_vinculado_nao_ve_nada(cenario, app):
    c = app.test_client()
    entrar(c, "sem@escritorio.com")
    html = c.get("/empresas").get_data(as_text=True)
    assert "EMPRESA DA ANA" not in html and "EMPRESA DA BIA" not in html

from datetime import date

from app.competencia import competencia_esperada
from app.models import Empresa, Obrigacao, RegimeTributario, Responsavel, db

CNPJ = "11.222.333/0001-81"


def _regime(nome):
    return RegimeTributario.query.filter_by(nome=nome).one()


def _cadastrar(client, app, regime="Lucro Presumido"):
    with app.app_context():
        db.session.add(Responsavel(nome="Ana"))
        db.session.commit()
        rid, respid = _regime(regime).id, Responsavel.query.one().id
    resp = client.post("/empresas/nova", data={
        "razao_social": "ACME Ltda", "cnpj": CNPJ, "regime_id": rid,
        "responsavel_id": respid, "escriturada_ate": "2026-06", "ativo": "on",
    })
    assert resp.status_code == 302
    with app.app_context():
        return Empresa.query.one().id


def test_seed_e_paginas(client):
    for url in ["/", "/empresas", "/empresas/nova", "/obrigacoes", "/obrigacoes/nova",
                "/regimes", "/regimes/novo", "/regimes/matriz", "/responsaveis", "/responsaveis/novo"]:
        assert client.get(url).status_code == 200, url


def test_cadastro_empresa_e_obrigacoes_do_regime(client, app):
    eid = _cadastrar(client, app)
    html = client.get(f"/empresas/{eid}").get_data(as_text=True)
    assert "ACME Ltda" in html and "11.222.333/0001-81" in html
    assert "Distribuição de Lucros" in html and "IRPJ" in html and "CSLL" in html
    with app.app_context():
        e = db.session.get(Empresa, eid)
        nomes = {o.nome for o in e.obrigacoes_aplicaveis()}
        assert "PGDAS-D / DAS" not in nomes  # obrigação do Simples, não do Presumido
        assert e.escriturada_ate == date(2026, 6, 1)
        assert e.responsavel.nome == "Ana"


def test_cnpj_invalido_e_duplicado(client, app):
    _cadastrar(client, app)
    with app.app_context():
        rid = _regime("Simples Nacional").id
    r = client.post("/empresas/nova", data={"razao_social": "X", "cnpj": "123", "regime_id": rid})
    assert "CNPJ inválido" in r.get_data(as_text=True)
    r = client.post("/empresas/nova", data={"razao_social": "X", "cnpj": CNPJ, "regime_id": rid})
    assert "já cadastrado" in r.get_data(as_text=True)
    with app.app_context():
        assert Empresa.query.count() == 1


def test_edicao_invalida_nao_persiste(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        rid = _regime("Lucro Presumido").id
    r = client.post(f"/empresas/{eid}/editar", data={"razao_social": "Nova", "cnpj": "1", "regime_id": rid})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Empresa, eid).razao_social == "ACME Ltda"


def test_entrega_deixa_obrigacao_em_dia(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        ob = Obrigacao.query.filter_by(nome="Distribuição de Lucros").one()
        obid = ob.id
        esperada = competencia_esperada("mensal", date.today())
        assert _status(eid, obid) == "pendente"
    client.post(f"/empresas/{eid}/entregas", data={"obrigacao_id": obid, "competencia": f"{esperada:%Y-%m}"})
    with app.app_context():
        assert _status(eid, obid) == "em_dia"
    # duplicada não quebra
    r = client.post(f"/empresas/{eid}/entregas", data={"obrigacao_id": obid, "competencia": f"{esperada:%Y-%m}"},
                    follow_redirects=True)
    assert "já estava registrada" in r.get_data(as_text=True)


def _status(eid, obid):
    e = db.session.get(Empresa, eid)
    return next(s["status"] for s in e.situacao_obrigacoes() if s["obrigacao"].id == obid)


def test_ajustes_por_empresa(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        defis = Obrigacao.query.filter_by(nome="DEFIS").one().id
        irpj = Obrigacao.query.filter_by(nome="IRPJ").one().id
    client.post(f"/empresas/{eid}/ajustes", data={"tipo": "incluir", "obrigacao_id": defis})
    client.post(f"/empresas/{eid}/ajustes", data={"tipo": "excluir", "obrigacao_id": irpj})
    with app.app_context():
        nomes = {o.nome for o in db.session.get(Empresa, eid).obrigacoes_aplicaveis()}
        assert "DEFIS" in nomes and "IRPJ" not in nomes


def test_matriz_parametrizacao(client, app):
    with app.app_context():
        mei = _regime("MEI")
        ob = Obrigacao.query.filter_by(nome="Distribuição de Lucros").one()
        vinculos = [f"{r.id}-{o.id}" for r in RegimeTributario.query for o in r.obrigacoes]
        vinculos.append(f"{mei.id}-{ob.id}")
        mei_id = mei.id
    client.post("/regimes/matriz", data={"vinculo": vinculos})
    with app.app_context():
        assert "Distribuição de Lucros" in {o.nome for o in db.session.get(RegimeTributario, mei_id).obrigacoes}


def test_atualizar_escrituracao(client, app):
    eid = _cadastrar(client, app)
    client.post(f"/empresas/{eid}/escrituracao", data={"escriturada_ate": "2026-08"})
    with app.app_context():
        e = db.session.get(Empresa, eid)
        assert e.escriturada_ate == date(2026, 8, 1)
        assert e.meses_escrituracao_atrasada(date(2026, 9, 30)) == 0
        assert e.meses_escrituracao_atrasada(date(2026, 12, 5)) == 3

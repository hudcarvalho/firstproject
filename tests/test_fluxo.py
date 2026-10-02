from datetime import date

from app.competencia import competencia_esperada
from app.models import Empresa, Modulo, Obrigacao, RegimeTributario, Responsavel, db

CNPJ = "11.222.333/0001-81"


def _regime(nome):
    return RegimeTributario.query.filter_by(nome=nome).one()


def _modulo(codigo):
    return Modulo.query.filter_by(codigo=codigo).one()


def _cadastrar(client, app, regime="Lucro Presumido"):
    with app.app_context():
        db.session.add(Responsavel(nome="Ana"))
        db.session.commit()
        rid, respid = _regime(regime).id, Responsavel.query.one().id
    resp = client.post("/empresas/nova", data={
        "razao_social": "ACME Ltda", "cnpj": CNPJ, "regime_id": rid,
        "responsavel_contabil": respid, "concluido_contabil": "2026-06", "ativo": "on",
    })
    assert resp.status_code == 302
    with app.app_context():
        return Empresa.query.one().id


def _ativar(app, codigo):
    with app.app_context():
        _modulo(codigo).ativo = True
        db.session.commit()


def test_modulos_iniciais(app):
    with app.app_context():
        assert [m.codigo for m in Modulo.ativos()] == ["contabil"]
        assert {m.codigo for m in Modulo.query} == {"contabil", "fiscal", "dp", "paralegal"}


def test_paginas(client, app):
    eid = _cadastrar(client, app)
    for url in ["/contabil/", "/empresas", "/empresas/nova", f"/empresas/{eid}/editar",
                f"/empresas/{eid}/contabil", "/contabil/obrigacoes", "/contabil/obrigacoes/nova",
                "/contabil/matriz", "/regimes", "/regimes/novo", "/responsaveis",
                "/responsaveis/novo", "/modulos", "/modulos/1/editar"]:
        assert client.get(url).status_code == 200, url
    assert client.get("/").headers["Location"].endswith("/empresas")


def test_modulo_inativo_fica_oculto(client, app):
    eid = _cadastrar(client, app)
    assert client.get("/fiscal/").status_code == 404
    assert client.get(f"/empresas/{eid}/fiscal").status_code == 404
    assert "PIS/COFINS" not in client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)


def test_cadastro_empresa_e_obrigacoes_do_regime(client, app):
    eid = _cadastrar(client, app)
    html = client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)
    assert "ACME Ltda" in html and "11.222.333/0001-81" in html
    assert "Escriturada até" in html
    with app.app_context():
        e = db.session.get(Empresa, eid)
        nomes = {o.nome for o in e.obrigacoes_aplicaveis(_modulo("contabil"))}
        assert nomes == {"ECD", "ECF"}  # Lucro Presumido: só ECD e ECF (anuais)
        assert "PIS/COFINS" not in nomes  # do módulo Fiscal
        c = e.controle(_modulo("contabil"))
        assert c.concluido_ate == date(2026, 6, 1)
        assert c.responsavel.nome == "Ana"


def test_ativar_modulo_fiscal(client, app):
    eid = _cadastrar(client, app)
    _ativar(app, "fiscal")
    html = client.get(f"/empresas/{eid}/fiscal").get_data(as_text=True)
    assert "PIS/COFINS" in html and "Apurado até" in html
    assert client.get("/fiscal/").status_code == 200
    # responsável próprio por módulo
    with app.app_context():
        db.session.add(Responsavel(nome="Bia"))
        db.session.commit()
        ana, bia = (Responsavel.query.filter_by(nome=n).one().id for n in ("Ana", "Bia"))
        rid = _regime("Lucro Presumido").id
    client.post(f"/empresas/{eid}/editar", data={
        "razao_social": "ACME Ltda", "cnpj": CNPJ, "regime_id": rid, "ativo": "on",
        "responsavel_contabil": ana, "responsavel_fiscal": bia, "concluido_fiscal": "2026-07",
    })
    with app.app_context():
        e = db.session.get(Empresa, eid)
        assert e.controle(_modulo("contabil")).responsavel.nome == "Ana"
        assert e.controle(_modulo("fiscal")).responsavel.nome == "Bia"
        assert e.controle(_modulo("fiscal")).concluido_ate == date(2026, 7, 1)


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
        e = db.session.get(Empresa, eid)
        assert e.razao_social == "ACME Ltda"
        assert e.controle(_modulo("contabil")).responsavel is not None


def _status(eid, obid):
    e = db.session.get(Empresa, eid)
    return next(s["status"] for s in e.situacao_obrigacoes(_modulo("contabil"))
                if s["obrigacao"].id == obid)


def test_entrega_deixa_obrigacao_em_dia(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        obid = Obrigacao.query.filter_by(nome="ECD").one().id
        esperada = competencia_esperada("anual", date.today())
        assert _status(eid, obid) == "pendente"
    url = f"/empresas/{eid}/contabil/entregas"
    client.post(url, data={"obrigacao_id": obid, "competencia": f"{esperada:%Y-%m}"})
    with app.app_context():
        assert _status(eid, obid) == "em_dia"
    r = client.post(url, data={"obrigacao_id": obid, "competencia": f"{esperada:%Y-%m}"},
                    follow_redirects=True)
    assert "já estava registrada" in r.get_data(as_text=True)


def test_entrega_de_obrigacao_de_outro_modulo_e_recusada(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        pis = Obrigacao.query.filter_by(nome="PIS/COFINS").one().id
    r = client.post(f"/empresas/{eid}/contabil/entregas",
                    data={"obrigacao_id": pis, "competencia": "2026-08"}, follow_redirects=True)
    assert "Preencha obrigação" in r.get_data(as_text=True)


def test_sem_excecoes_por_empresa(client, app):
    eid = _cadastrar(client, app)
    html = client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)
    assert "Exceções desta empresa" not in html and "Dispensar" not in html
    with app.app_context():
        defis = Obrigacao.query.filter_by(nome="DEFIS").one().id
    assert client.post(f"/empresas/{eid}/contabil/ajustes",
                       data={"tipo": "incluir", "obrigacao_id": defis}).status_code in (404, 405)
    with app.app_context():
        nomes = {o.nome for o in db.session.get(Empresa, eid).obrigacoes_aplicaveis(_modulo("contabil"))}
        assert nomes == {"ECD", "ECF"}  # só o que a tributação (Lucro Presumido) exige


def test_matriz_preserva_outros_modulos(client, app):
    with app.app_context():
        mei = _regime("MEI")
        dist = Obrigacao.query.filter_by(nome="ECD").one()
        contabil = _modulo("contabil")
        vinculos = [f"{r.id}-{o.id}" for r in RegimeTributario.query
                    for o in r.obrigacoes if o.modulo_id == contabil.id]
        vinculos.append(f"{mei.id}-{dist.id}")
        mei_id = mei.id
        fiscais_antes = sum(len(r.obrigacoes_do_modulo(_modulo("fiscal"))) for r in RegimeTributario.query)
    client.post("/contabil/matriz", data={"vinculo": vinculos})
    with app.app_context():
        nomes_mei = {o.nome for o in db.session.get(RegimeTributario, mei_id).obrigacoes}
        assert "ECD" in nomes_mei and "DAS-MEI" in nomes_mei
        fiscais_depois = sum(len(r.obrigacoes_do_modulo(_modulo("fiscal"))) for r in RegimeTributario.query)
        assert fiscais_antes == fiscais_depois


def test_nova_obrigacao_no_modulo(client, app):
    with app.app_context():
        rid = _regime("Lucro Real").id
    client.post("/contabil/obrigacoes/nova", data={
        "nome": "Balancete mensal", "periodicidade": "mensal", "esfera": "interna",
        "regimes": [rid], "ativo": "on",
    })
    with app.app_context():
        ob = Obrigacao.query.filter_by(nome="Balancete mensal").one()
        assert ob.modulo.codigo == "contabil"
        assert [r.nome for r in ob.regimes] == ["Lucro Real"]


def test_atualizar_escrituracao(client, app):
    eid = _cadastrar(client, app)
    client.post(f"/empresas/{eid}/contabil/controle", data={"concluido_ate": "2026-08"})
    with app.app_context():
        c = db.session.get(Empresa, eid).controle(_modulo("contabil"))
        assert c.concluido_ate == date(2026, 8, 1)
        assert c.meses_atrasados(date(2026, 9, 30)) == 0
        assert c.meses_atrasados(date(2026, 12, 5)) == 3


def test_filtro_sem_responsavel(client, app):
    _cadastrar(client, app)
    html = client.get("/contabil/?responsavel=0").get_data(as_text=True)
    assert "ACME Ltda" not in html


def test_lista_clientes_tem_dados_para_filtros(client, app):
    eid = _cadastrar(client, app)
    with app.app_context():
        e = db.session.get(Empresa, eid)
        e.ativo = False
        db.session.commit()
        resp_id = e.controle(_modulo("contabil")).responsavel_id
        regime_id = e.regime_id
    html = client.get("/empresas").get_data(as_text=True)
    # empresas inativas também vêm na página (o filtro Situação decide se aparecem)
    assert "ACME Ltda" in html and 'data-situacao="inativa"' in html
    assert f'data-respcontabil="{resp_id}"' in html and f'data-regime="{regime_id}"' in html
    assert 'id="f-resp-contabil"' in html and 'id="f-regime"' in html and 'id="f-situacao"' in html
    assert '<option value="todas" selected>' in client.get("/empresas?inativas=1").get_data(as_text=True)


def test_lista_clientes_mostra_escriturada_ate(client, app):
    _cadastrar(client, app)  # escriturada até 06/2026
    html = client.get("/empresas").get_data(as_text=True)
    assert "Escriturada até" in html and "06/2026" in html
    assert 'data-conccontabil="2026-06"' in html and 'id="f-conc-contabil"' in html
    assert ">Situação<" not in html


def test_lista_clientes_ordenavel_por_codigo_e_razao(client, app):
    _cadastrar(client, app)
    html = client.get("/empresas").get_data(as_text=True)
    assert 'data-ordem="codigo"' in html and 'data-ordem="nome"' in html
    assert 'data-razao="ACME Ltda"' in html


def test_arquivos_estaticos_com_versao(client):
    import re
    html = client.get("/empresas").get_data(as_text=True)
    m = re.search(r'href="(/static/app\.css\?v=[0-9a-f]{10})"', html)
    assert m, "app.css deve ter ?v=<hash> para o navegador não usar cópia antiga"
    assert re.search(r'/static/vendor/bootstrap\.bundle\.min\.js\?v=[0-9a-f]{10}', html)
    assert client.get(m.group(1)).status_code == 200


def test_grupo_economico(client, app):
    from app.models import GrupoEconomico
    with app.app_context():
        rid = _regime("Lucro Presumido").id
    base = {"regime_id": rid, "ativo": "on"}
    client.post("/empresas/nova", data={**base, "razao_social": "ALFA", "cnpj": "11.222.333/0001-81", "grupo": "GRUPO  CONFECÇÕES"})
    # mesmo grupo digitado com outra grafia (inclusive acentos minúsculos): reaproveita o existente
    client.post("/empresas/nova", data={**base, "razao_social": "BETA", "cnpj": "11.444.777/0001-61", "grupo": "grupo confecções"})
    client.post("/empresas/nova", data={**base, "razao_social": "GAMA", "cnpj": "45.997.418/0001-53"})
    with app.app_context():
        grupos = GrupoEconomico.query.all()
        assert [g.nome for g in grupos] == ["GRUPO CONFECÇÕES"]
        gid = grupos[0].id
        alfa, beta, gama = (Empresa.query.filter_by(razao_social=n).one() for n in ("ALFA", "BETA", "GAMA"))
        assert alfa.grupo_id == beta.grupo_id == gid and gama.grupo_id is None
        alfa_id, beta_id = alfa.id, beta.id

    html = client.get("/empresas").get_data(as_text=True)
    assert 'id="f-grupo"' in html and f'<option value="{gid}">GRUPO CONFECÇÕES</option>' in html
    assert html.count(f'data-grupo="{gid}"') == 2 and html.count('data-grupo="0"') == 1
    # cabeçalho da empresa mostra o grupo com link para o filtro
    assert f"/empresas?grupo={gid}" in client.get(f"/empresas/{alfa_id}/contabil").get_data(as_text=True)

    # tirar as duas empresas do grupo apaga o grupo que ficou vazio
    for eid, nome, cnpj in ((alfa_id, "ALFA", "11.222.333/0001-81"), (beta_id, "BETA", "11.444.777/0001-61")):
        client.post(f"/empresas/{eid}/editar", data={**base, "razao_social": nome, "cnpj": cnpj, "grupo": ""})
    with app.app_context():
        assert GrupoEconomico.query.count() == 0



def test_obrigacoes_contabeis_por_tributacao(app):
    with app.app_context():
        contabil = _modulo("contabil")
        def nomes(regime):
            return {o.nome for o in _regime(regime).obrigacoes_do_modulo(contabil)}
        assert nomes("Lucro Real") == {"ECD", "ECF", "IRPJ", "CSLL"}
        assert nomes("Lucro Presumido") == {"ECD", "ECF"}
        assert nomes("Simples Nacional") == {"ECD", "DEFIS"}
        per = {o.nome: (o.periodicidade, o.controla_imposto) for o in contabil.obrigacoes}
        assert per["IRPJ"] == ("trimestral", True) and per["CSLL"] == ("trimestral", True)
        assert per["ECD"] == ("anual", False) and per["DEFIS"] == ("anual", False)


def test_registro_irpj_com_imposto(client, app):
    from decimal import Decimal
    from app.models import Entrega
    eid = _cadastrar(client, app, regime="Lucro Real")
    with app.app_context():
        irpj = Obrigacao.query.filter_by(nome="IRPJ").one().id
        ecd = Obrigacao.query.filter_by(nome="ECD").one().id
    url = f"/empresas/{eid}/contabil/entregas"
    html = client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)
    assert f'value="{irpj}" data-imposto="1" data-periodicidade="trimestral"' in html

    # sem forma de pagamento: recusado
    r = client.post(url, data={"obrigacao_id": irpj, "competencia": "2026-05"}, follow_redirects=True)
    assert "forma de pagamento" in r.get_data(as_text=True)
    # quota maior que o imposto: recusado
    r = client.post(url, data={"obrigacao_id": irpj, "competencia": "2026-05", "forma_pagamento": "parcelado",
                               "valor_imposto": "900", "valor_quota": "1.000"}, follow_redirects=True)
    assert "não pode ser maior" in r.get_data(as_text=True)
    # parcelado: competência de maio vira junho (fim do trimestre)
    client.post(url, data={"obrigacao_id": irpj, "competencia": "2026-05", "forma_pagamento": "parcelado",
                           "valor_imposto": "9.000,00", "valor_quota": "3.000,00"})
    # quota única: valor da quota é ignorado
    client.post(url, data={"obrigacao_id": irpj, "competencia": "2026-08", "forma_pagamento": "unica",
                           "valor_imposto": "1.234,56", "valor_quota": "10"})
    # obrigação anual: fica em dezembro, sem dados de imposto
    client.post(url, data={"obrigacao_id": ecd, "competencia": "2025-04", "forma_pagamento": "unica",
                           "valor_imposto": "50"})
    with app.app_context():
        ent = {(e.obrigacao.nome, e.competencia): e for e in Entrega.query}
        par = ent[("IRPJ", date(2026, 6, 1))]
        assert (par.forma_pagamento, par.valor_imposto, par.valor_quota) == ("parcelado", Decimal("9000.00"), Decimal("3000.00"))
        uni = ent[("IRPJ", date(2026, 9, 1))]
        assert (uni.forma_pagamento, uni.valor_imposto, uni.valor_quota) == ("unica", Decimal("1234.56"), None)
        anual = ent[("ECD", date(2025, 12, 1))]
        assert anual.forma_pagamento is None and anual.valor_imposto is None
    html = client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)
    assert "R$ 9.000,00 · Parcelado (quota R$ 3.000,00)" in html
    assert "R$ 1.234,56 · Quota única" in html


def test_obrigacao_marcada_como_imposto(client, app):
    client.post("/contabil/obrigacoes/nova", data={
        "nome": "IRPJ Estimativa", "periodicidade": "mensal", "esfera": "federal",
        "controla_imposto": "on", "ativo": "on"})
    with app.app_context():
        assert Obrigacao.query.filter_by(nome="IRPJ Estimativa").one().controla_imposto


def test_observacoes_na_tela_da_empresa(client, app):
    eid = _cadastrar(client, app)
    html = client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)
    assert 'id="form-observacoes"' in html
    r = client.post(f"/empresas/{eid}/contabil/observacoes",
                    data={"observacoes": "  Sócio prefere contato por e-mail.\nECD com termo especial.  "})
    assert r.status_code == 302 and r.headers["Location"].endswith("#form-observacoes")
    with app.app_context():
        assert db.session.get(Empresa, eid).observacoes == "Sócio prefere contato por e-mail.\nECD com termo especial."
    assert "Sócio prefere contato por e-mail." in client.get(f"/empresas/{eid}/contabil").get_data(as_text=True)
    # o mesmo campo do cadastro: aparece em "Editar cadastro"
    assert "ECD com termo especial." in client.get(f"/empresas/{eid}/editar").get_data(as_text=True)
    client.post(f"/empresas/{eid}/contabil/observacoes", data={"observacoes": "   "})
    with app.app_context():
        assert db.session.get(Empresa, eid).observacoes is None

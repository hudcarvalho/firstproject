from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.models import Empresa, ObrigacaoAnual, RegimeTributario, db


@pytest.fixture
def empresas(app):
    with app.app_context():
        simples = RegimeTributario.query.filter_by(nome="Simples Nacional").one()
        presumido = RegimeTributario.query.filter_by(nome="Lucro Presumido").one()
        a = Empresa(codigo="46", razao_social="EXATA CONTABIL", cnpj="11222333000181", regime=simples)
        b = Empresa(codigo="29", razao_social="CHAVEIRO ITALIA LTDA", cnpj="45997418000153", regime=presumido)
        c = Empresa(codigo="5", razao_social="INATIVA LTDA", cnpj="06990590000123", regime=simples, ativo=False)
        db.session.add_all([a, b, c])
        db.session.commit()
        return a.id, b.id


def test_menu_e_cabecalho(client, empresas):
    html = client.get("/empresas").get_data(as_text=True)
    assert ">Obrigações</a>" in html
    html = client.get("/obrigacoes/?ano=2026").get_data(as_text=True)
    cab = ["CÓDIGO", "EMPRESA", "CNPJ", "TRIBUTAÇÃO", "DEFIS", "ECD", "ECF", "IBGE", "OBSERVAÇÃO"]
    assert 'data-ordem="codigo"' in html and 'data-ordem="nome"' in html
    pos = [html.index(f">{c} <span") if i < 2 else html.index(f">{c}</th>") for i, c in enumerate(cab)]
    assert pos == sorted(pos)
    # ordem por código, só ativas
    assert html.index("CHAVEIRO ITALIA LTDA") < html.index("EXATA CONTABIL")
    assert "INATIVA LTDA" not in html
    assert "45.997.418/0001-53" in html and "LUCRO PRESUMIDO" in html
    for c in ("defis", "ecd", "ecf", "ibge", "observacao"):
        assert f'class="form-select form-select-sm filtro-campo" data-campo="{c}"' in html
    assert ">Em branco</option>" in html and ">Preenchidos</option>" in html


def test_salvar_celulas(client, app, empresas):
    a, b = empresas
    r = client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "defis", "valor": "2026-03-30"})
    assert r.get_json() == {"ok": True}
    client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "observacao",
                                            "valor": " IBGE AGUARDANDO   LIBERAÇÃO "})
    client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "ecd", "valor": "15/06/2026"})
    r = client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "ibge", "valor": "18/08/20260"})
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "cnpj", "valor": "x"}
                       ).status_code == 400
    # apagar
    client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "ecd", "valor": ""})
    # vazio em empresa sem registro não cria linha
    client.post("/obrigacoes/salvar", data={"empresa_id": b, "ano": 2026, "campo": "ecf", "valor": ""})
    with app.app_context():
        regs = ObrigacaoAnual.query.all()
        assert len(regs) == 1
        r = regs[0]
        assert (r.defis, r.ecd, r.ibge, r.observacao) == (date(2026, 3, 30), None, None, "IBGE AGUARDANDO LIBERAÇÃO")
    html = client.get("/obrigacoes/?ano=2026").get_data(as_text=True)
    assert 'value="30/03/2026"' in html and 'value="IBGE AGUARDANDO LIBERAÇÃO"' in html
    assert 'value="30/03/2026"' not in client.get("/obrigacoes/?ano=2025").get_data(as_text=True)


def test_exportar_excel(client, empresas):
    a, _ = empresas
    client.post("/obrigacoes/salvar", data={"empresa_id": a, "ano": 2026, "campo": "defis", "valor": "2026-03-30"})
    r = client.get("/obrigacoes/exportar?ano=2026")
    ws = load_workbook(BytesIO(r.data)).active
    assert [c.value for c in ws[1]] == ["CÓDIGO", "EMPRESA", "CNPJ", "TRIBUTAÇÃO", "DEFIS", "ECD", "ECF", "IBGE",
                                        "OBSERVAÇÃO"]
    assert [c.value for c in ws[2]][:5] == [29, "CHAVEIRO ITALIA LTDA", "45.997.418/0001-53", "LUCRO PRESUMIDO", None]
    assert ws["E3"].value.date() == date(2026, 3, 30) and ws["A3"].value == 46

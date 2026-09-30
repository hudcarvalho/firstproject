from decimal import Decimal

import pytest

from app.competencia import cpf_valido, fmt_documento, fmt_valor, parse_valor
from app.models import DistribuicaoLucro, Empresa, RegimeTributario, Socio, db

CPF1, CPF2 = "529.982.247-25", "111.444.777-35"
CNPJ_SOCIO = "11.444.777/0001-61"


def test_cpf_valido():
    assert cpf_valido(CPF1) and cpf_valido("11144477735")
    assert not cpf_valido("529.982.247-24") and not cpf_valido("111.111.111-11")


@pytest.mark.parametrize("texto,esperado", [
    ("1.234,56", Decimal("1234.56")), ("1234,5", Decimal("1234.50")), ("R$ 10", Decimal("10.00")),
    ("1234.56", Decimal("1234.56")), ("2.000", Decimal("2000.00")), ("1.500.000", Decimal("1500000.00")),
    ("1.5", Decimal("1.50")), ("", None), ("  ", None),
])
def test_parse_valor(texto, esperado):
    assert parse_valor(texto) == esperado


def test_parse_valor_invalido():
    with pytest.raises(ValueError):
        parse_valor("abc")


def test_formatacoes():
    assert fmt_valor(Decimal("1234567.5")) == "1.234.567,50"
    assert fmt_valor(None) == ""
    assert fmt_documento("52998224725") == "529.982.247-25"
    assert fmt_documento("11444777000161") == "11.444.777/0001-61"


@pytest.fixture
def empresas(app):
    with app.app_context():
        regime = RegimeTributario.query.filter_by(nome="Lucro Presumido").one()
        a = Empresa(codigo="29", razao_social="CHAVEIRO ITALIA LTDA", cnpj="11222333000181", regime=regime)
        b = Empresa(codigo="30", razao_social="CHAVEIRO ROMA LTDA", cnpj="45997418000153", regime=regime)
        db.session.add_all([a, b])
        db.session.commit()
        return a.id, b.id


def test_menu_e_selecao(client, empresas):
    a, _ = empresas
    assert "Distribuição de Lucros" in client.get("/contabil/").get_data(as_text=True)
    assert client.get("/distribuicao/").status_code == 200
    # código exato ou item escolhido da lista abre direto
    assert client.get("/distribuicao/?busca=29").headers["Location"].endswith(f"/distribuicao/{a}")
    assert client.get("/distribuicao/?busca=29 — CHAVEIRO ITALIA LTDA").headers["Location"].endswith(f"/distribuicao/{a}")
    assert client.get("/distribuicao/?busca=italia").headers["Location"].endswith(f"/distribuicao/{a}")
    # vários resultados: mostra a lista para escolher
    html = client.get("/distribuicao/?busca=chaveiro").get_data(as_text=True)
    assert "2 clientes encontrados" in html
    assert "Nenhum cliente encontrado" in client.get("/distribuicao/?busca=xyz", follow_redirects=True).get_data(as_text=True)


def test_socios_e_valores(client, app, empresas):
    a, _ = empresas
    url = f"/distribuicao/{a}"
    assert "CPF/CNPJ inválido" in client.post(f"{url}/socios", data={"nome": "Ana", "documento": "123"},
                                              follow_redirects=True).get_data(as_text=True)
    client.post(f"{url}/socios", data={"nome": "Ana  Souza", "documento": CPF1})
    client.post(f"{url}/socios", data={"nome": "Holding X", "documento": CNPJ_SOCIO})
    r = client.post(f"{url}/socios", data={"nome": "Outra", "documento": CPF1}, follow_redirects=True)
    assert "Já existe um sócio" in r.get_data(as_text=True)

    with app.app_context():
        ana = Socio.query.filter_by(nome="Ana Souza").one().id
        holding = Socio.query.filter_by(nome="Holding X").one().id

    r = client.post(f"{url}?ano=2026", data={f"v-{ana}-1": "1.000,00", f"v-{ana}-2": "500,5",
                                             f"v-{holding}-1": "2.000", f"v-{holding}-12": ""})
    assert r.status_code == 302
    html = client.get(f"{url}?ano=2026").get_data(as_text=True)
    assert "1.500,50" in html        # total da Ana
    assert "3.000,00" in html        # total de janeiro
    assert "3.500,50" in html        # total geral
    assert "529.982.247-25" in html and "11.444.777/0001-61" in html

    # outro ano começa vazio
    assert "3.500,50" not in client.get(f"{url}?ano=2025").get_data(as_text=True)

    # apagar um valor (campo vazio) e valor inválido não grava nada
    client.post(f"{url}?ano=2026", data={f"v-{ana}-2": ""})
    r = client.post(f"{url}?ano=2026", data={f"v-{ana}-3": "abc", f"v-{ana}-4": "10"})
    assert "não é um valor válido" in r.get_data(as_text=True)
    with app.app_context():
        valores = {(d.socio_id, d.mes): d.valor for d in DistribuicaoLucro.query}
        assert valores == {(ana, 1): Decimal("1000.00"), (holding, 1): Decimal("2000.00")}


def test_inativar_socio(client, app, empresas):
    a, b = empresas
    url = f"/distribuicao/{a}"
    client.post(f"{url}/socios", data={"nome": "Sem valores", "documento": CPF1})
    client.post(f"{url}/socios", data={"nome": "Com valores", "documento": CPF2})
    with app.app_context():
        sem = Socio.query.filter_by(nome="Sem valores").one().id
        com = Socio.query.filter_by(nome="Com valores").one().id
    client.post(f"{url}?ano=2026", data={f"v-{com}-5": "100"})
    client.post(f"/distribuicao/socios/{sem}/situacao?ano=2026")
    client.post(f"/distribuicao/socios/{com}/situacao?ano=2026")
    html = client.get(f"{url}?ano=2026").get_data(as_text=True)
    assert f'name="v-{sem}-1"' not in html   # inativo sem valores sai da grade
    assert f'name="v-{com}-1"' in html       # inativo com valores no ano continua aparecendo
    assert "Reativar" in html
    client.post(f"/distribuicao/socios/{sem}/situacao")
    with app.app_context():
        assert db.session.get(Socio, sem).ativo
    # valor de sócio de outra empresa é ignorado
    client.post(f"/distribuicao/{b}?ano=2026", data={f"v-{com}-6": "999"})
    with app.app_context():
        assert DistribuicaoLucro.query.count() == 1

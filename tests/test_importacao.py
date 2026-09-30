import io

import openpyxl
import pytest

from app.importacao import interpretar_regime, interpretar_responsavel
from app.models import Empresa, Modulo, RegimeTributario, Responsavel, db
from tests.conftest import criar_usuario, entrar

# CNPJs válidos fictícios
C1, C2, C3, C4 = "11.222.333/0001-81", "11.444.777/0001-61", "45.997.418/0001-53", "19.131.243/0001-97"


@pytest.mark.parametrize("texto,esperado", [
    ("SIMPLES", "Simples Nacional"),
    ("PRESUMIDO", "Lucro Presumido"),
    ("REAL", "Lucro Real"),
    ("REAL TRIMESTRAL", "Lucro Real Trimestral"),
    ("SIMPLES/ PRESUMIDO EM 2026", "Lucro Presumido"),
    ("PRESUMIDO/ SIMPLES EM 2026", "Simples Nacional"),
    ("REAL/ SIMPLES EM 2026", "Simples Nacional"),
    ("SIMPLES ATÉ 30/06/2025/ PRESUMIDO", "Lucro Presumido"),
    ("SIMPLES/ PRESUMIDO A PARTIR DE 04/2025", "Lucro Presumido"),
    ("SEM FINS", "Imune/Isenta"),
    ("MEI", "MEI"),
    ("Normal", None),
    ("♦", None),
    ("", None),
])
def test_interpretar_regime(texto, esperado):
    assert interpretar_regime(texto) == esperado


def test_interpretar_responsavel():
    assert interpretar_responsavel("DIRCEU") == ("Dirceu", None)
    assert interpretar_responsavel("ELIS / MILEIDE") == ("Elis", "ELIS / MILEIDE")
    assert interpretar_responsavel("") == (None, None)


def _xlsx(linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(["Código", "Nome", "CNPJ", "obrigatoriedade", "Regime", "Responsável", "Observações"])
    for linha in linhas:
        ws.append(linha)
    wb.create_sheet("Vazia")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


LINHAS = [
    [29, "EMPRESA ALFA LTDA", C1, 43466, "SIMPLES/ PRESUMIDO EM 2026", "ELLEN", ""],
    [46, "Empresa Beta Ltda", C2, 43466, "Normal", "DIRCEU", "TEM ECD EM 2024"],
    [48, "EMPRESA GAMA  LTDA", C3, "", "REAL TRIMESTRAL", "ELIS / MILEIDE", ""],
    [50, "EMPRESA DELTA", "12.820.022/0001-68", "", "SIMPLES", "DIRCEU", ""],  # CNPJ inválido
    [51, "EMPRESA SEM CNPJ", "♣", "", "SIMPLES", "DIRCEU", ""],
    [52, "EMPRESA REPETIDA", C1, "", "SIMPLES", "", ""],
    [53, "EMPRESA SEM FINS", C4, "", "SEM FINS", "", ""],
]


def _enviar(client, buf, nome="clientes.xlsx"):
    r = client.post("/importar", data={"arquivo": (buf, nome)}, content_type="multipart/form-data")
    assert r.status_code == 302, r.get_data(as_text=True)
    return r.headers["Location"]


def test_importacao_completa(client, app):
    url_previa = _enviar(client, _xlsx(LINHAS))
    html = client.get(url_previa).get_data(as_text=True)
    assert "Conferir importação" in html
    assert "CNPJ inválido" in html and "CNPJ em branco" in html and "CNPJ repetido" in html
    with app.app_context():
        assert Empresa.query.count() == 0  # a prévia não grava nada

    token = url_previa.rstrip("/").split("/")[-1]
    r = client.post(f"/importar/{token}/confirmar", data={"aba": "Clientes"}, follow_redirects=True)
    assert "4 empresa(s) cadastrada(s)" in r.get_data(as_text=True)

    with app.app_context():
        contabil = Modulo.query.filter_by(codigo="contabil").one()
        por_cnpj = {e.cnpj: e for e in Empresa.query}
        alfa, beta, gama, sem_fins = (por_cnpj[c.replace(".", "").replace("/", "").replace("-", "")]
                                      for c in (C1, C2, C3, C4))
        assert alfa.codigo == "29" and alfa.regime.nome == "Lucro Presumido"
        assert "Regime na planilha: SIMPLES/ PRESUMIDO EM 2026" in alfa.observacoes
        assert alfa.controle(contabil).responsavel.nome == "Ellen"
        assert beta.regime.nome == "A definir"
        assert beta.observacoes.startswith("TEM ECD EM 2024") and "Regime na planilha: Normal" in beta.observacoes
        assert gama.razao_social == "EMPRESA GAMA LTDA"
        assert gama.regime.nome == "Lucro Real Trimestral"
        assert gama.controle(contabil).responsavel.nome == "Elis"
        assert "Responsável na planilha: ELIS / MILEIDE" in gama.observacoes
        assert sem_fins.regime.nome == "Imune/Isenta" and sem_fins.controle(contabil) is None
        # Real Trimestral herda as obrigações do Lucro Real
        real = RegimeTributario.query.filter_by(nome="Lucro Real").one()
        trimestral = RegimeTributario.query.filter_by(nome="Lucro Real Trimestral").one()
        assert {o.id for o in trimestral.obrigacoes} == {o.id for o in real.obrigacoes}
        assert sorted(r.nome for r in Responsavel.query) == ["Dirceu", "Elis", "Ellen"]

    # arquivo temporário apagado; reimportar não duplica
    assert client.get(url_previa).status_code == 302
    url2 = _enviar(client, _xlsx(LINHAS))
    token2 = url2.rstrip("/").split("/")[-1]
    client.post(f"/importar/{token2}/confirmar", data={"aba": "Clientes"})
    with app.app_context():
        assert Empresa.query.count() == 4
        assert Responsavel.query.count() == 3


def test_reimportacao_atualiza_quando_pedido(client, app):
    token = _enviar(client, _xlsx([[1, "NOME ANTIGO", C1, "", "SIMPLES", "ANA", ""]])).split("/")[-1]
    client.post(f"/importar/{token}/confirmar", data={})
    token = _enviar(client, _xlsx([[1, "NOME NOVO", C1, "", "PRESUMIDO", "ANA", ""]])).split("/")[-1]
    client.post(f"/importar/{token}/confirmar", data={"atualizar": "on"})
    with app.app_context():
        e = Empresa.query.one()
        assert e.razao_social == "NOME NOVO" and e.regime.nome == "Lucro Presumido"


def test_importacao_csv(client, app):
    csv = f"Código;Razão social;CNPJ;Regime\n7;EMPRESA CSV;{C2};PRESUMIDO\n".encode("cp1252")
    token = _enviar(client, io.BytesIO(csv), "clientes.csv").split("/")[-1]
    client.post(f"/importar/{token}/confirmar", data={})
    with app.app_context():
        assert Empresa.query.one().regime.nome == "Lucro Presumido"


def test_arquivo_invalido(client):
    r = client.post("/importar", data={"arquivo": (io.BytesIO(b"x"), "a.pdf")},
                    content_type="multipart/form-data")
    assert "Envie uma planilha" in r.get_data(as_text=True)
    r = client.post("/importar", data={"arquivo": (io.BytesIO(b"lixo"), "a.xlsx")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Não foi possível ler a planilha" in r.get_data(as_text=True)
    assert client.get("/importar/../../etc/passwd").status_code == 404
    assert client.get("/importar/abc.xlsx").status_code == 404


def test_importacao_so_admin(anonimo, app):
    criar_usuario(app, "ana@x.com", admin=False)
    entrar(anonimo, "ana@x.com")
    assert anonimo.get("/importar").status_code == 403

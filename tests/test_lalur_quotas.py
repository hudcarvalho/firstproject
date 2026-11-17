from datetime import date
from decimal import Decimal as D

import pytest

from app.lalur import lembretes_pendentes, quotas_do_cliente
from app.models import Empresa, LalurApuracao, LalurQuotaEnvio, RegimeTributario, db


@pytest.fixture
def lr(app):
    with app.app_context():
        regime = RegimeTributario.query.filter_by(nome="Lucro Real").one()
        a = Empresa(codigo="2120", razao_social="EBM CHOCOLATES LTDA", cnpj="11222333000181", regime=regime)
        b = Empresa(codigo="2083", razao_social="VILLA BOLICHE LTDA", cnpj="45997418000153", regime=regime)
        db.session.add_all([a, b])
        db.session.commit()
        return a.id, b.id


def _apurar(client, empresa_id, ano, periodo, quotas):
    return client.post(f"/lalur/{empresa_id}/{ano}/{periodo}",
                       data={"lucro_antes": "300.000,00", "compensar": "on", "aliquota_csll": "9", "quotas": quotas})


def test_informar_quotas_na_apuracao(client, app, lr):
    a, _ = lr
    _apurar(client, a, 2026, 1, "3")
    html = client.get(f"/lalur/{a}/2026/1").get_data(as_text=True)
    assert '<option value="3" selected>Dividido em 3 quotas</option>' in html
    assert "3ª de 3 · vence 30/06/2026" in html
    with app.app_context():
        ap = LalurApuracao.query.filter_by(empresa_id=a, ano=2026, periodo=1).one()
        assert [q.vencimento for q in quotas_do_cliente(ap)] == [date(2026, 4, 30), date(2026, 5, 29), date(2026, 6, 30)]
    # a guia já abre parcelada em 3
    assert "3 quotas" in client.get(f"/lalur/{a}/2026/1/guia").get_data(as_text=True)
    # anual: só quota única
    _apurar(client, lr[1], 2025, 0, "3")
    with app.app_context():
        assert LalurApuracao.query.filter_by(empresa_id=lr[1], ano=2025).one().quotas == 1


def test_lembrete_do_dia_10_ate_marcar_enviada(client, app, lr):
    a, _ = lr
    _apurar(client, a, 2026, 1, "2")  # vencem 30/04 e 29/05
    with app.app_context():
        assert lembretes_pendentes(date(2026, 4, 9)) == []
        assert [q.numero for q in lembretes_pendentes(date(2026, 4, 10))] == [1]
        assert [q.numero for q in lembretes_pendentes(date(2026, 5, 10))] == [1, 2]  # a 1ª continua até marcar
        ap_id = LalurApuracao.query.filter_by(empresa_id=a).one().id
    client.post(f"/lalur/quotas/{ap_id}/1/envio", data={"enviado": "1"})
    with app.app_context():
        assert [q.numero for q in lembretes_pendentes(date(2026, 5, 10))] == [2]
        envio = LalurQuotaEnvio.query.one()
        assert envio.enviado_em == date.today() and envio.enviado_por == "Admin"
    client.post(f"/lalur/quotas/{ap_id}/1/envio", data={"enviado": "0"})  # desfazer
    with app.app_context():
        assert LalurQuotaEnvio.query.count() == 0
    # mudar para quota única apaga envios de quotas que não existem mais
    client.post(f"/lalur/quotas/{ap_id}/2/envio", data={"enviado": "1"})
    client.post(f"/lalur/quotas/{ap_id}/definir", data={"quotas": "1"})
    with app.app_context():
        assert LalurQuotaEnvio.query.count() == 0


def test_tela_filtros_e_aviso(client, app, lr):
    a, b = lr
    _apurar(client, a, 2020, 1, "3")  # passado: tudo no lembrete
    _apurar(client, b, 2020, 1, "1")
    client.post(f"/lalur/{b}/2020/2", data={"lucro_antes": "1.000,00", "aliquota_csll": "9"})  # sem quotas
    html = client.get("/empresas").get_data(as_text=True)
    assert "4 quota(s) de IRPJ/CSLL para enviar" in html and 'id="lembrete-quotas"' in html
    def empresas(**f):
        html = client.get("/lalur/quotas", query_string={"ano": 2020, **f}).get_data(as_text=True)
        return [n for n in ("EBM CHOCOLATES", "VILLA BOLICHE") if n in html], html
    assert empresas()[0] == ["EBM CHOCOLATES", "VILLA BOLICHE"]
    assert empresas(quotas="3")[0] == ["EBM CHOCOLATES"]
    assert empresas(quotas="1")[0] == ["VILLA BOLICHE"]
    nao, html = empresas(quotas="nao")
    assert nao == ["VILLA BOLICHE"] and "2º trim. 2020" in html and "1º trim. 2020" not in html
    _, html = empresas(situacao="pendente")
    assert "4 quota(s) a enviar" in html
    with app.app_context():
        ids = [x.id for x in LalurApuracao.query.filter(LalurApuracao.quotas.isnot(None))]
    client.post("/lalur/quotas/enviar-todas", data={"quota": [f"{i}-{n}" for i in ids for n in (1, 2, 3)]})
    assert 'id="lembrete-quotas"' not in client.get("/empresas").get_data(as_text=True)
    assert empresas(situacao="enviada")[0] == ["EBM CHOCOLATES", "VILLA BOLICHE"]
    assert empresas(situacao="pendente")[0] == []


def test_escolher_no_resumo_e_valores_das_quotas(client, app, lr):
    a, _ = lr
    client.post(f"/lalur/{a}/2026/1", data={"lucro_antes": "300.000,00", "compensar": "on", "aliquota_csll": "9"})
    html = client.get(f"/lalur/{a}?ano=2026").get_data(as_text=True)
    assert 'id="linha-quotas"' in html and "Quota única ou parcelado" in html
    with app.app_context():
        ap_id = LalurApuracao.query.filter_by(empresa_id=a).one().id
    r = client.post(f"/lalur/quotas/{ap_id}/definir", data={"quotas": "3", "voltar": f"/lalur/{a}?ano=2026"})
    assert r.headers["Location"].endswith(f"/lalur/{a}?ano=2026")
    html = client.get(f"/lalur/{a}?ano=2026").get_data(as_text=True)
    assert '<option value="3" selected>3 quotas</option>' in html
    assert html.count("<strong>32.000,00</strong>") == 3  # IRPJ 69.000 + CSLL 27.000 em 3 quotas
    html = client.get("/lalur/quotas?ano=2026").get_data(as_text=True)
    assert html.count("R$ 32.000,00") == 3 and "IRPJ 23.000,00 · CSLL 9.000,00" in html
    client.post(f"/lalur/quotas/{ap_id}/definir", data={"quotas": "1"})
    assert "R$ 96.000,00" in client.get("/lalur/quotas?ano=2026").get_data(as_text=True)

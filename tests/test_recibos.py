import zipfile
from datetime import date
from io import BytesIO

import pytest

from app.models import Empresa, ObrigacaoAnual, RegimeTributario, db
from app.pdf_simples import Documento
from app import recibos


def _pdf(linhas):
    doc = Documento("Recibo")
    for i, l in enumerate(linhas):
        doc.texto(40, 40 + i * 14, l, 9)
    return doc.gerar()


DEFIS = ["Declaração de Informações Socioeconômicas e", "Fiscais(DEFIS)", "Exercício: 2026", "Ano Calendário: 2025",
         "RECIBO DE ENTREGA", "1. Informações do Contribuinte", "Nome empresarial CNPJ da Matriz",
         "EMPRESA TESTE LTDA 11.222.333/0001-81", "2. Informações da Recepção da Declaração",
         "Data e Horário da Transmissão da Declaração", "30/03/2026 09:58:48"]
ECD = ["SISTEMA PÚBLICO DE ESCRITURAÇÃO DIGITAL – Sped", "RECIBO DE ENTREGA DE ESCRITURAÇÃO CONTÁBIL DIGITAL",
       "IDENTIFICAÇÃO DO TITULAR DA ESCRITURAÇÃO", "NIRE CNPJ", "35600443581 45.997.418/0001-53",
       "PERÍODO DA ESCRITURAÇÃO 01/01/2025 a 31/12/2025", "Procurador 38892626000122 EXATA 18/03/2026 a 18/03/2027",
       "NÚMERO DO RECIBO: Escrituração recebida via Internet", "pelo Agente Receptor SERPRO", "em 29/06/2026 às 10:37:04"]
ECF = ["RECIBO DE ENTREGA DE ESCRITURAÇÃO FISCAL DIGITAL", "Imposto de Renda de Pessoa Jurídica - ECF", "CNPJ",
       "11.222.333/0001-81", "01/01/2025 a 31/12/2025 Normal", "Escrituração recebida via Internet",
       "em 17/06/2026 às 15:11:59"]
IBGE = ["Comprovante de Entrega de Pesquisa", "Data: 05/08/2026 09:50:56", "Pesquisa: PASXX", "Ano: 2025",
        "CNPJ: 45.997.418/0001-53"]


def test_ler_cada_recibo_pelo_conteudo():
    r = recibos.ler_pdf("nome-errado-ECF.pdf", _pdf(DEFIS))
    assert (r.tipo, r.cnpj, r.data, r.erro) == ("defis", "11222333000181", date(2026, 3, 30), None)
    r = recibos.ler_pdf("x.pdf", _pdf(ECD))
    assert (r.tipo, r.cnpj, r.data) == ("ecd", "45997418000153", date(2026, 6, 29))
    r = recibos.ler_pdf("x.pdf", _pdf(ECF))
    assert (r.tipo, r.cnpj, r.data) == ("ecf", "11222333000181", date(2026, 6, 17))
    r = recibos.ler_pdf("x.pdf", _pdf(IBGE))
    assert (r.tipo, r.cnpj, r.data) == ("ibge", "45997418000153", date(2026, 8, 5))
    r = recibos.ler_pdf("x.pdf", _pdf(["Qualquer outro documento", "CNPJ 11.222.333/0001-81"]))
    assert r.erro and "não reconhecido" in r.erro
    assert recibos.ler_pdf("x.pdf", b"lixo").erro == "não foi possível abrir o PDF"


def test_letras_desenhadas_do_ibge_pelo_gabarito():
    """Cada letra do comprovante sem texto é comparada ao desenho do gabarito."""
    gab = recibos._gabarito()
    por_letra = {}
    for modelos in gab.values():
        for letra, pts in modelos:
            por_letra.setdefault(letra, pts)
    for letra in "0123456789/:.-":
        pts = por_letra[letra]
        # o mesmo desenho em outra posição e escala
        pontos = [(10 + 7 * pts[i], 500 + 7 * pts[i + 1]) for i in range(0, len(pts), 2)]
        assert recibos._reconhecer({"pontos": pontos}) == letra
    assert recibos._reconhecer({"pontos": [(0, 0), (1, 5), (3, 2)]}) == "?"


@pytest.fixture
def empresas(app):
    with app.app_context():
        regime = RegimeTributario.query.filter_by(nome="Simples Nacional").one()
        a = Empresa(codigo="46", razao_social="EXATA CONTABIL", cnpj="11222333000181", regime=regime)
        b = Empresa(codigo="29", razao_social="CHAVEIRO ITALIA LTDA", cnpj="45997418000153", regime=regime)
        db.session.add_all([a, b])
        db.session.flush()
        db.session.add(ObrigacaoAnual(empresa_id=a.id, ano=2026, defis=date(2026, 3, 1)))
        db.session.commit()
        return a.id, b.id


def test_importar_zip_previa_e_gravar(client, app, empresas):
    a, b = empresas
    zbuf = BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("2026/abc.pdf", _pdf(DEFIS))
        z.writestr("2026/sub/ecd.pdf", _pdf(ECD))
        z.writestr("leia-me.txt", "ignorar")
        z.writestr("__MACOSX/._abc.pdf", b"lixo")
    arquivos = [(BytesIO(zbuf.getvalue()), "recibos.zip"), (BytesIO(_pdf(ECF)), "1.pdf"),
                (BytesIO(_pdf(IBGE)), "2.pdf"), (BytesIO(_pdf(DEFIS[:7] + ["X 06.990.590/0001-23"] + DEFIS[8:])), "3.pdf")]
    assert "Importar recibos" in client.get("/obrigacoes/").get_data(as_text=True)
    html = client.post("/obrigacoes/importar", data={"arquivos": arquivos},
                       content_type="multipart/form-data").get_data(as_text=True)
    assert "Prévia: 5 arquivo(s) · 4 data(s) para gravar" in html
    assert "substitui 01/03/2026" in html and "CNPJ não cadastrado no sistema" in html
    itens = [f"{a}|defis|2026-03-30", f"{b}|ecd|2026-06-29", f"{a}|ecf|2026-06-17", f"{b}|ibge|2026-08-05"]
    for i in itens:
        assert f'value="{i}"' in html
    r = client.post("/obrigacoes/importar/confirmar", data={"item": itens})
    assert r.headers["Location"].endswith("/obrigacoes/?ano=2026")
    with app.app_context():
        ra = ObrigacaoAnual.query.filter_by(empresa_id=a, ano=2026).one()
        rb = ObrigacaoAnual.query.filter_by(empresa_id=b, ano=2026).one()
        assert (ra.defis, ra.ecf) == (date(2026, 3, 30), date(2026, 6, 17))
        assert (rb.ecd, rb.ibge) == (date(2026, 6, 29), date(2026, 8, 5))


def test_mesmo_recibo_duas_vezes_vale_o_mais_recente(client, empresas):
    retificado = ECF[:-1] + ["em 20/07/2026 às 08:00:00"]
    html = client.post("/obrigacoes/importar", data={"arquivos": [(BytesIO(_pdf(ECF)), "a.pdf"),
                                                                   (BytesIO(_pdf(retificado)), "b.pdf")]},
                       content_type="multipart/form-data").get_data(as_text=True)
    assert "1 data(s) para gravar" in html and "há recibo mais recente" in html and "2026-07-20" in html

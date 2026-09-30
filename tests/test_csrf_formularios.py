"""Todo formulário POST das telas precisa levar o token CSRF (senão o envio dá erro 400)."""
import re

from app.models import Empresa, RegimeTributario, Socio, db


def test_todo_formulario_post_tem_csrf(client, app):
    with app.app_context():
        regime = RegimeTributario.query.first()
        e = Empresa(codigo="1", razao_social="EMPRESA TESTE", cnpj="11222333000181", regime=regime)
        db.session.add(e)
        db.session.flush()
        db.session.add(Socio(empresa=e, nome="Sócio", documento="52998224725"))
        db.session.commit()
        eid = e.id
    app.config["WTF_CSRF_ENABLED"] = True
    paginas = ["/contabil/", "/empresas", "/empresas/nova", f"/empresas/{eid}/editar",
               f"/empresas/{eid}/contabil", "/contabil/obrigacoes/nova", "/contabil/matriz",
               "/regimes/novo", "/responsaveis/novo", "/modulos/1/editar", "/usuarios/novo",
               "/minha-senha", "/importar", "/distribuicao/", f"/distribuicao/{eid}"]
    for url in paginas:
        html = client.get(url).get_data(as_text=True)
        for form in re.findall(r"<form\b[^>]*>.*?</form>", html, flags=re.S | re.I):
            if re.search(r'method="post"', form, flags=re.I):
                assert 'name="csrf_token"' in form, f"{url}: formulário sem CSRF: {form[:160]}"

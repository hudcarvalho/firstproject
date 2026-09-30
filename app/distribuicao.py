"""Aba Distribuição de Lucros: sócios de cada cliente e valores distribuídos por mês."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from .competencia import cnpj_valido, cpf_valido, parse_valor, so_digitos
from .models import DistribuicaoLucro, Empresa, Socio, db

bp = Blueprint("distribuicao", __name__, url_prefix="/distribuicao")

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _empresa(id_):
    empresa = db.session.get(Empresa, id_)
    if empresa is None:
        abort(404)
    return empresa


def _ano():
    try:
        ano = int(request.values.get("ano", ""))
    except ValueError:
        return date.today().year
    return ano if 2000 <= ano <= 2100 else date.today().year


def _clientes_para_busca():
    return Empresa.query.filter_by(ativo=True).order_by(Empresa.razao_social).all()


@bp.route("/")
def selecionar():
    """Escolha do cliente. Com ?busca=, resolve código exato ou nome e vai direto à empresa."""
    busca = (request.args.get("busca") or "").strip()
    encontrados = []
    if busca:
        rotulo = busca.split(" — ", 1)  # valor vindo da lista: "código — razão social"
        codigo = rotulo[0].strip()
        por_codigo = Empresa.query.filter_by(codigo=codigo).all() if codigo else []
        if len(rotulo) == 2:
            por_codigo = [e for e in por_codigo if e.razao_social == rotulo[1].strip()] or por_codigo
        if len(por_codigo) == 1:
            return redirect(url_for("distribuicao.empresa", id=por_codigo[0].id))
        digitos = so_digitos(busca)
        filtros = [Empresa.razao_social.ilike(f"%{busca}%"), Empresa.nome_fantasia.ilike(f"%{busca}%")]
        if len(digitos) >= 5:
            filtros.append(Empresa.cnpj.contains(digitos))
        encontrados = por_codigo or Empresa.query.filter(or_(*filtros)).order_by(
            Empresa.razao_social).limit(50).all()
        if len(encontrados) == 1:
            return redirect(url_for("distribuicao.empresa", id=encontrados[0].id))
        if not encontrados:
            flash(f"Nenhum cliente encontrado para “{busca}”.", "warning")
    return render_template("distribuicao/selecionar.html", clientes=_clientes_para_busca(),
                           busca=busca, encontrados=encontrados)


def _grade(empresa, ano):
    """Linhas da grade: sócios ativos + inativos que tenham valores no ano."""
    valores = defaultdict(dict)  # socio_id -> {mes: valor}
    ids = [s.id for s in empresa.socios]
    if ids:
        for d in DistribuicaoLucro.query.filter(DistribuicaoLucro.socio_id.in_(ids),
                                                DistribuicaoLucro.ano == ano):
            valores[d.socio_id][d.mes] = d.valor
    linhas = []
    for s in empresa.socios:
        if s.ativo or valores.get(s.id):
            meses = [valores[s.id].get(m) for m in range(1, 13)]
            linhas.append({"socio": s, "meses": meses,
                           "total": sum((v for v in meses if v is not None), Decimal("0"))})
    totais_mes = [sum((l["meses"][i] or Decimal("0") for l in linhas), Decimal("0")) for i in range(12)]
    return linhas, totais_mes, sum(totais_mes, Decimal("0"))


@bp.route("/<int:id>", methods=["GET", "POST"])
def empresa(id):
    empresa = _empresa(id)
    ano = _ano()
    if request.method == "POST":
        erros = _salvar_valores(empresa, ano)
        if erros:
            db.session.rollback()
            for e in erros:
                flash(e, "danger")
        else:
            db.session.commit()
            flash(f"Valores de {ano} salvos.", "success")
            return redirect(url_for("distribuicao.empresa", id=id, ano=ano))
    linhas, totais_mes, total_geral = _grade(empresa, ano)
    return render_template(
        "distribuicao/empresa.html", empresa=empresa, ano=ano, meses=MESES, linhas=linhas,
        totais_mes=totais_mes, total_geral=total_geral, clientes=_clientes_para_busca(),
        valores_digitados=request.form if request.method == "POST" else None,
    )


def _salvar_valores(empresa, ano):
    """Campos do formulário: v-<socio_id>-<mes>. Vazio apaga o valor do mês."""
    socios = {s.id: s for s in empresa.socios}
    existentes = {}
    if socios:
        for d in DistribuicaoLucro.query.filter(DistribuicaoLucro.socio_id.in_(socios),
                                                DistribuicaoLucro.ano == ano):
            existentes[(d.socio_id, d.mes)] = d
    erros = []
    for chave, texto in request.form.items():
        partes = chave.split("-")
        if len(partes) != 3 or partes[0] != "v":
            continue
        try:
            socio_id, mes = int(partes[1]), int(partes[2])
        except ValueError:
            continue
        if socio_id not in socios or not 1 <= mes <= 12:
            continue
        try:
            valor = parse_valor(texto)
        except ValueError:
            erros.append(f"{socios[socio_id].nome} — {MESES[mes - 1]}: “{texto}” não é um valor válido.")
            continue
        if valor is not None and valor < 0:
            erros.append(f"{socios[socio_id].nome} — {MESES[mes - 1]}: o valor não pode ser negativo.")
            continue
        atual = existentes.get((socio_id, mes))
        if valor is None or valor == 0:
            if atual:
                db.session.delete(atual)
        elif atual:
            atual.valor = valor
        else:
            db.session.add(DistribuicaoLucro(socio_id=socio_id, ano=ano, mes=mes, valor=valor))
    return erros


@bp.post("/<int:id>/socios")
def socio_novo(id):
    empresa = _empresa(id)
    ano = _ano()
    nome = " ".join((request.form.get("nome") or "").split())
    documento = so_digitos(request.form.get("documento"))
    if not nome:
        flash("Informe o nome do sócio.", "danger")
    elif not (cpf_valido(documento) or cnpj_valido(documento)):
        flash("CPF/CNPJ inválido.", "danger")
    elif Socio.query.filter_by(empresa_id=id, documento=documento).first():
        flash("Já existe um sócio com esse CPF/CNPJ nesta empresa.", "warning")
    else:
        db.session.add(Socio(empresa=empresa, nome=nome, documento=documento, ativo=True))
        db.session.commit()
        flash(f"Sócio {nome} cadastrado.", "success")
    return redirect(url_for("distribuicao.empresa", id=id, ano=ano))


@bp.post("/socios/<int:socio_id>/situacao")
def socio_situacao(socio_id):
    socio = db.session.get(Socio, socio_id)
    if socio is None:
        abort(404)
    socio.ativo = not socio.ativo
    db.session.commit()
    flash(f"Sócio {socio.nome} {'reativado' if socio.ativo else 'inativado'}.", "success")
    return redirect(url_for("distribuicao.empresa", id=socio.empresa_id, ano=_ano()))

from datetime import date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from werkzeug.security import check_password_hash, generate_password_hash

from .competencia import competencia_esperada, meses_entre

# Nomes previsíveis para constraints — necessários para alterá-las em migrações futuras.
db = SQLAlchemy(metadata=MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}))

PERIODICIDADES = {
    "mensal": "Mensal",
    "trimestral": "Trimestral",
    "anual": "Anual",
    "eventual": "Eventual",
}

ESFERAS = {
    "federal": "Federal",
    "estadual": "Estadual",
    "municipal": "Municipal",
    "interna": "Interna (escritório)",
}

# Relação N:N — quais obrigações cada regime tributário exige.
regime_obrigacao = db.Table(
    "regime_obrigacao",
    db.Column("regime_id", db.Integer, db.ForeignKey("regime_tributario.id"), primary_key=True),
    db.Column("obrigacao_id", db.Integer, db.ForeignKey("obrigacao.id"), primary_key=True),
)


class Modulo(db.Model):
    """Área de atuação do escritório (Contábil, Fiscal, DP, Paralegal).

    Obrigações, responsável e controle de "concluído até" são sempre por módulo.
    Só módulos ativos aparecem nas telas.
    """

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)  # usado na URL
    nome = db.Column(db.String(60), nullable=False)
    # Rótulo do controle de andamento: "Escriturada até", "Apurado até", "Folha fechada até"…
    rotulo_controle = db.Column(db.String(60), nullable=False, default="Concluído até")
    ordem = db.Column(db.Integer, nullable=False, default=0)
    ativo = db.Column(db.Boolean, default=False, nullable=False)

    obrigacoes = db.relationship("Obrigacao", back_populates="modulo", order_by="Obrigacao.nome")

    @staticmethod
    def ativos():
        return Modulo.query.filter_by(ativo=True).order_by(Modulo.ordem).all()


class RegimeTributario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    descricao = db.Column(db.String(255))
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    obrigacoes = db.relationship(
        "Obrigacao", secondary=regime_obrigacao, back_populates="regimes", order_by="Obrigacao.nome"
    )
    empresas = db.relationship("Empresa", back_populates="regime")

    def obrigacoes_do_modulo(self, modulo):
        return [o for o in self.obrigacoes if o.modulo_id == modulo.id]


class Responsavel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    controles = db.relationship("EmpresaModulo", back_populates="responsavel")

    def empresas_ativas(self, modulo=None):
        return [c.empresa for c in self.controles
                if c.empresa.ativo and (modulo is None or c.modulo_id == modulo.id)]


class Obrigacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    modulo_id = db.Column(db.Integer, db.ForeignKey("modulo.id"), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.String(255))
    periodicidade = db.Column(db.String(20), nullable=False, default="mensal")
    esfera = db.Column(db.String(20), nullable=False, default="federal")
    dia_vencimento = db.Column(db.Integer)  # dia do mês de vencimento (informativo)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    modulo = db.relationship("Modulo", back_populates="obrigacoes")
    regimes = db.relationship(
        "RegimeTributario", secondary=regime_obrigacao, back_populates="obrigacoes"
    )

    __table_args__ = (db.UniqueConstraint("modulo_id", "nome"),)

    @property
    def periodicidade_label(self):
        return PERIODICIDADES.get(self.periodicidade, self.periodicidade)

    @property
    def esfera_label(self):
        return ESFERAS.get(self.esfera, self.esfera)


class Empresa(db.Model):
    """Cadastro do cliente — compartilhado por todos os módulos."""

    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(200), nullable=False)
    nome_fantasia = db.Column(db.String(200))
    cnpj = db.Column(db.String(14), unique=True, nullable=False)  # só dígitos
    inscricao_estadual = db.Column(db.String(30))
    inscricao_municipal = db.Column(db.String(30))
    email = db.Column(db.String(120))
    telefone = db.Column(db.String(30))
    regime_id = db.Column(db.Integer, db.ForeignKey("regime_tributario.id"), nullable=False)
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    regime = db.relationship("RegimeTributario", back_populates="empresas")
    controles = db.relationship(
        "EmpresaModulo", back_populates="empresa", cascade="all, delete-orphan"
    )
    ajustes = db.relationship(
        "EmpresaObrigacaoAjuste", back_populates="empresa", cascade="all, delete-orphan"
    )
    entregas = db.relationship(
        "Entrega", back_populates="empresa", cascade="all, delete-orphan",
        order_by="Entrega.competencia.desc()",
    )

    @property
    def cnpj_formatado(self):
        c = self.cnpj or ""
        if len(c) != 14:
            return c
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

    @property
    def nome_exibicao(self):
        return self.nome_fantasia or self.razao_social

    def controle(self, modulo, criar=False):
        """Registro de responsável/andamento da empresa no módulo."""
        for c in self.controles:
            if c.modulo_id == modulo.id:
                return c
        if criar:
            c = EmpresaModulo(modulo=modulo)
            self.controles.append(c)
            return c
        return None

    def obrigacoes_aplicaveis(self, modulo):
        """Obrigações do módulo exigidas pelo regime + inclusões − exclusões (só ativas)."""
        ajustes = [a for a in self.ajustes if a.obrigacao.modulo_id == modulo.id]
        incluir = {a.obrigacao for a in ajustes if a.tipo == "incluir"}
        excluir = {a.obrigacao for a in ajustes if a.tipo == "excluir"}
        todas = (set(self.regime.obrigacoes_do_modulo(modulo)) | incluir) - excluir
        return sorted((o for o in todas if o.ativo), key=lambda o: o.nome)

    def ultima_entrega(self, obrigacao):
        entregas = [e for e in self.entregas if e.obrigacao_id == obrigacao.id]
        return max(entregas, key=lambda e: e.competencia, default=None)

    def entregas_do_modulo(self, modulo):
        return [e for e in self.entregas if e.obrigacao.modulo_id == modulo.id]

    def situacao_obrigacoes(self, modulo, hoje=None):
        """Lista de dicts com a situação de cada obrigação aplicável no módulo."""
        hoje = hoje or date.today()
        do_regime = set(self.regime.obrigacoes)
        resultado = []
        for ob in self.obrigacoes_aplicaveis(modulo):
            ultima = self.ultima_entrega(ob)
            esperada = competencia_esperada(ob.periodicidade, hoje)
            if esperada is None:
                status = "eventual"
            elif ultima and ultima.competencia >= esperada:
                status = "em_dia"
            else:
                status = "pendente"
            resultado.append({
                "obrigacao": ob, "ultima": ultima, "esperada": esperada, "status": status,
                "origem": "regime" if ob in do_regime else "específica",
            })
        return resultado


class EmpresaModulo(db.Model):
    """Controle da empresa dentro de um módulo: quem cuida e até quando está concluído.

    No Contábil, `concluido_ate` é o "escriturada até".
    """

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresa.id"), nullable=False)
    modulo_id = db.Column(db.Integer, db.ForeignKey("modulo.id"), nullable=False)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"))
    concluido_ate = db.Column(db.Date)  # competência (dia 1 do mês)

    empresa = db.relationship("Empresa", back_populates="controles")
    modulo = db.relationship("Modulo")
    responsavel = db.relationship("Responsavel", back_populates="controles")

    __table_args__ = (db.UniqueConstraint("empresa_id", "modulo_id"),)

    def meses_atrasados(self, hoje=None):
        """Quantos meses faltam concluir até o mês anterior a hoje."""
        if self.concluido_ate is None:
            return None
        alvo = competencia_esperada("mensal", hoje or date.today())
        return max(0, meses_entre(self.concluido_ate, alvo))


class EmpresaObrigacaoAjuste(db.Model):
    """Exceção por empresa: inclui uma obrigação fora do regime ou exclui uma do regime."""

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresa.id"), nullable=False)
    obrigacao_id = db.Column(db.Integer, db.ForeignKey("obrigacao.id"), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # "incluir" | "excluir"

    empresa = db.relationship("Empresa", back_populates="ajustes")
    obrigacao = db.relationship("Obrigacao")

    __table_args__ = (db.UniqueConstraint("empresa_id", "obrigacao_id"),)


class Entrega(db.Model):
    """Registro de que uma obrigação foi cumprida para uma competência."""

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresa.id"), nullable=False)
    obrigacao_id = db.Column(db.Integer, db.ForeignKey("obrigacao.id"), nullable=False)
    competencia = db.Column(db.Date, nullable=False)  # dia 1 do mês
    data_entrega = db.Column(db.Date, nullable=False, default=date.today)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"))
    observacao = db.Column(db.String(255))

    empresa = db.relationship("Empresa", back_populates="entregas")
    obrigacao = db.relationship("Obrigacao")
    responsavel = db.relationship("Responsavel")

    __table_args__ = (db.UniqueConstraint("empresa_id", "obrigacao_id", "competencia"),)


class Usuario(UserMixin, db.Model):
    """Quem acessa o sistema. Pode estar ligado a um Responsável ("minhas empresas")."""

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)  # usado como login
    senha_hash = db.Column(db.String(255), nullable=False)
    admin = db.Column(db.Boolean, default=False, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"))

    responsavel = db.relationship("Responsavel")

    SENHA_MINIMA = 8

    @property
    def is_active(self):
        return self.ativo

    def definir_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def confere_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

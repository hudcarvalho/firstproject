from datetime import date

from flask_sqlalchemy import SQLAlchemy

from .competencia import competencia_esperada, meses_entre

db = SQLAlchemy()

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


class RegimeTributario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    descricao = db.Column(db.String(255))
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    obrigacoes = db.relationship(
        "Obrigacao", secondary=regime_obrigacao, back_populates="regimes", order_by="Obrigacao.nome"
    )
    empresas = db.relationship("Empresa", back_populates="regime")


class Responsavel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    empresas = db.relationship("Empresa", back_populates="responsavel")


class Obrigacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    descricao = db.Column(db.String(255))
    periodicidade = db.Column(db.String(20), nullable=False, default="mensal")
    esfera = db.Column(db.String(20), nullable=False, default="federal")
    dia_vencimento = db.Column(db.Integer)  # dia do mês de vencimento (informativo)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    regimes = db.relationship(
        "RegimeTributario", secondary=regime_obrigacao, back_populates="obrigacoes"
    )

    @property
    def periodicidade_label(self):
        return PERIODICIDADES.get(self.periodicidade, self.periodicidade)

    @property
    def esfera_label(self):
        return ESFERAS.get(self.esfera, self.esfera)


class Empresa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(200), nullable=False)
    nome_fantasia = db.Column(db.String(200))
    cnpj = db.Column(db.String(14), unique=True, nullable=False)  # só dígitos
    inscricao_estadual = db.Column(db.String(30))
    inscricao_municipal = db.Column(db.String(30))
    email = db.Column(db.String(120))
    telefone = db.Column(db.String(30))
    regime_id = db.Column(db.Integer, db.ForeignKey("regime_tributario.id"), nullable=False)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"))
    # Último mês (competência) com escrituração concluída — armazenado como dia 1 do mês.
    escriturada_ate = db.Column(db.Date)
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    regime = db.relationship("RegimeTributario", back_populates="empresas")
    responsavel = db.relationship("Responsavel", back_populates="empresas")
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

    def meses_escrituracao_atrasada(self, hoje=None):
        """Quantos meses faltam escriturar até o mês anterior a hoje."""
        alvo = competencia_esperada("mensal", hoje or date.today())
        if self.escriturada_ate is None:
            return None
        return max(0, meses_entre(self.escriturada_ate, alvo))

    def obrigacoes_aplicaveis(self):
        """Obrigações do regime + inclusões específicas − exclusões específicas (só ativas)."""
        incluir = {a.obrigacao for a in self.ajustes if a.tipo == "incluir"}
        excluir = {a.obrigacao for a in self.ajustes if a.tipo == "excluir"}
        todas = (set(self.regime.obrigacoes) | incluir) - excluir
        return sorted((o for o in todas if o.ativo), key=lambda o: o.nome)

    def ultima_entrega(self, obrigacao):
        entregas = [e for e in self.entregas if e.obrigacao_id == obrigacao.id]
        return max(entregas, key=lambda e: e.competencia, default=None)

    def situacao_obrigacoes(self, hoje=None):
        """Lista de dicts com a situação de cada obrigação aplicável."""
        hoje = hoje or date.today()
        resultado = []
        for ob in self.obrigacoes_aplicaveis():
            ultima = self.ultima_entrega(ob)
            esperada = competencia_esperada(ob.periodicidade, hoje)
            if esperada is None:
                status = "eventual"
            elif ultima and ultima.competencia >= esperada:
                status = "em_dia"
            else:
                status = "pendente"
            origem = "regime" if ob in self.regime.obrigacoes else "específica"
            resultado.append(
                {"obrigacao": ob, "ultima": ultima, "esperada": esperada,
                 "status": status, "origem": origem}
            )
        return resultado


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

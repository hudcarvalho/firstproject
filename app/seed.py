"""Dados iniciais: módulos, regimes tributários, obrigações de exemplo e o vínculo entre eles.

Tudo pode ser alterado depois pelas telas de parametrização.
"""
from .models import Modulo, Obrigacao, RegimeTributario, db

# (codigo, nome, rótulo do controle de andamento, ativo)
MODULOS = [
    ("contabil", "Contábil", "Escriturada até", True),
    ("fiscal", "Fiscal", "Apurado até", False),
    ("dp", "Departamento Pessoal", "Folha fechada até", False),
    ("paralegal", "Paralegal", "Concluído até", False),
]

REGIMES = [
    ("Simples Nacional", "LC 123/2006"),
    ("Lucro Presumido", "IRPJ/CSLL sobre base presumida"),
    ("Lucro Real", "IRPJ/CSLL sobre o lucro contábil ajustado"),
    ("MEI", "Microempreendedor Individual"),
    ("Imune/Isenta", "Entidades imunes ou isentas"),
]

SN, LP, LR, MEI, IMU = (r[0] for r in REGIMES)

# módulo -> [(nome, descrição, periodicidade, esfera, dia_vencimento, regimes)]
# As obrigações dos módulos ainda inativos já ficam cadastradas para quando forem ligados.
OBRIGACOES = {
    "contabil": [
        ("Distribuição de Lucros", "Apuração e registro da distribuição de lucros aos sócios",
         "mensal", "interna", None, [SN, LP, LR]),
        ("IRPJ", "Apuração e recolhimento do IRPJ (DARF)", "trimestral", "federal", None, [LP, LR]),
        ("CSLL", "Apuração e recolhimento da CSLL (DARF)", "trimestral", "federal", None, [LP, LR]),
        ("ECD", "Escrituração Contábil Digital (SPED Contábil)", "anual", "federal", None,
         [LP, LR, IMU]),
        ("ECF", "Escrituração Contábil Fiscal", "anual", "federal", None, [LP, LR, IMU]),
        ("DEFIS", "Declaração de informações socioeconômicas e fiscais", "anual", "federal", None,
         [SN]),
    ],
    "fiscal": [
        ("PIS/COFINS", "Apuração e recolhimento de PIS e COFINS", "mensal", "federal", 25, [LP, LR]),
        ("EFD-Contribuições", "SPED PIS/COFINS", "mensal", "federal", None, [LP, LR]),
        ("EFD-Reinf", "Escrituração de retenções e outras informações fiscais", "mensal", "federal",
         15, [SN, LP, LR, IMU]),
        ("PGDAS-D / DAS", "Apuração do Simples Nacional", "mensal", "federal", 20, [SN]),
        ("DAS-MEI", "Recolhimento mensal do MEI", "mensal", "federal", 20, [MEI]),
        ("DASN-SIMEI", "Declaração anual do MEI", "anual", "federal", None, [MEI]),
    ],
    "dp": [
        ("Folha de pagamento", "Fechamento da folha", "mensal", "interna", 5, [SN, LP, LR, IMU]),
        ("eSocial", "Eventos trabalhistas e previdenciários", "mensal", "federal", 15,
         [SN, LP, LR, IMU]),
        ("DCTFWeb", "Declaração de débitos e créditos tributários federais", "mensal", "federal", 15,
         [SN, LP, LR, IMU]),
        ("FGTS Digital", "Recolhimento do FGTS", "mensal", "federal", 20, [SN, LP, LR, IMU]),
    ],
    "paralegal": [],
}


def seed():
    # Módulos: idempotente por código, para que novos módulos possam ser acrescentados aqui.
    existentes = {m.codigo for m in Modulo.query}
    for ordem, (codigo, nome, rotulo, ativo) in enumerate(MODULOS):
        if codigo not in existentes:
            db.session.add(Modulo(codigo=codigo, nome=nome, rotulo_controle=rotulo,
                                  ordem=ordem, ativo=ativo))
    db.session.commit()

    if RegimeTributario.query.first():
        return
    regimes = {}
    for nome, desc in REGIMES:
        regimes[nome] = RegimeTributario(nome=nome, descricao=desc)
        db.session.add(regimes[nome])
    modulos = {m.codigo: m for m in Modulo.query}
    for codigo, obrigacoes in OBRIGACOES.items():
        for nome, desc, per, esf, dia, rs in obrigacoes:
            db.session.add(Obrigacao(
                modulo=modulos[codigo], nome=nome, descricao=desc, periodicidade=per, esfera=esf,
                dia_vencimento=dia, regimes=[regimes[r] for r in rs],
            ))
    db.session.commit()

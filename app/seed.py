"""Dados iniciais: regimes tributários, obrigações de exemplo e o vínculo entre eles.

Tudo pode ser alterado depois pelas telas de parametrização.
"""
from .models import Obrigacao, RegimeTributario, db

REGIMES = [
    ("Simples Nacional", "LC 123/2006"),
    ("Lucro Presumido", "IRPJ/CSLL sobre base presumida"),
    ("Lucro Real", "IRPJ/CSLL sobre o lucro contábil ajustado"),
    ("MEI", "Microempreendedor Individual"),
    ("Imune/Isenta", "Entidades imunes ou isentas"),
]

SN, LP, LR, MEI, IMU = (r[0] for r in REGIMES)

# (nome, descrição, periodicidade, esfera, dia_vencimento, regimes)
OBRIGACOES = [
    ("Distribuição de Lucros", "Apuração e registro da distribuição de lucros aos sócios",
     "mensal", "interna", None, [SN, LP, LR]),
    ("IRPJ", "Apuração e recolhimento do IRPJ (DARF)", "trimestral", "federal", None, [LP, LR]),
    ("CSLL", "Apuração e recolhimento da CSLL (DARF)", "trimestral", "federal", None, [LP, LR]),
    ("PIS/COFINS", "Apuração e recolhimento de PIS e COFINS", "mensal", "federal", 25, [LP, LR]),
    ("EFD-Contribuições", "SPED PIS/COFINS", "mensal", "federal", None, [LP, LR]),
    ("DCTFWeb", "Declaração de débitos e créditos tributários federais", "mensal", "federal", 15,
     [SN, LP, LR, IMU]),
    ("EFD-Reinf", "Escrituração de retenções e outras informações fiscais", "mensal", "federal", 15,
     [SN, LP, LR, IMU]),
    ("eSocial", "Eventos trabalhistas e previdenciários", "mensal", "federal", 15,
     [SN, LP, LR, IMU]),
    ("PGDAS-D / DAS", "Apuração do Simples Nacional", "mensal", "federal", 20, [SN]),
    ("DEFIS", "Declaração de informações socioeconômicas e fiscais", "anual", "federal", None, [SN]),
    ("DAS-MEI", "Recolhimento mensal do MEI", "mensal", "federal", 20, [MEI]),
    ("DASN-SIMEI", "Declaração anual do MEI", "anual", "federal", None, [MEI]),
    ("ECD", "Escrituração Contábil Digital (SPED Contábil)", "anual", "federal", None, [LP, LR, IMU]),
    ("ECF", "Escrituração Contábil Fiscal", "anual", "federal", None, [LP, LR, IMU]),
]


def seed():
    if RegimeTributario.query.first():
        return
    regimes = {}
    for nome, desc in REGIMES:
        regimes[nome] = RegimeTributario(nome=nome, descricao=desc)
        db.session.add(regimes[nome])
    for nome, desc, per, esf, dia, rs in OBRIGACOES:
        db.session.add(Obrigacao(
            nome=nome, descricao=desc, periodicidade=per, esfera=esf, dia_vencimento=dia,
            regimes=[regimes[r] for r in rs],
        ))
    db.session.commit()

from datetime import date

from app.competencia import cnpj_valido, competencia_esperada, parse_competencia


def test_parse_competencia():
    assert parse_competencia("2026-08") == date(2026, 8, 1)
    assert parse_competencia("08/2026") == date(2026, 8, 1)
    assert parse_competencia("2026-13") is None
    assert parse_competencia("") is None


def test_competencia_esperada():
    hoje = date(2026, 9, 30)
    assert competencia_esperada("mensal", hoje) == date(2026, 8, 1)
    assert competencia_esperada("trimestral", hoje) == date(2026, 6, 1)
    assert competencia_esperada("trimestral", date(2026, 10, 1)) == date(2026, 9, 1)
    assert competencia_esperada("trimestral", date(2026, 2, 1)) == date(2025, 12, 1)
    assert competencia_esperada("mensal", date(2026, 1, 10)) == date(2025, 12, 1)
    assert competencia_esperada("anual", hoje) == date(2025, 12, 1)
    assert competencia_esperada("eventual", hoje) is None


def test_cnpj():
    assert cnpj_valido("11.222.333/0001-81")
    assert not cnpj_valido("11.222.333/0001-80")
    assert not cnpj_valido("11111111111111")

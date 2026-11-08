import pytest

from docparse.amounts import detect_currency, parse_amount


@pytest.mark.parametrize("raw,expected", [
    ("1 234,50 €", 1234.50), ("1,234.50", 1234.50), ("$1,234.50", 1234.50), ("1.234,50 EUR", 1234.50),
    ("1 234,50", 1234.50), ("1 234,50", 1234.50), ("12,50", 12.5), ("12.5", 12.5), ("0", 0.0),
    ("-5,00", -5.0), ("1,234,567.89", 1234567.89), ("1.234.567,89", 1234567.89),
    ("1,234", 1234.0),   # un seul séparateur suivi de 3 chiffres : milliers (documenté)
    ("1.234", 1234.0),
    ("12,345", 12345.0),
    ("1234,5", 1234.5),   # 4 chiffres avant : jamais des milliers à une seule décimale
    ("1234,567", 1234.567),   # 4 chiffres avant le séparateur : pas des milliers
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["abc", "", "1 481,4O", "12-34", "€"])
def test_parse_amount_rejects_non_numbers(raw):
    assert parse_amount(raw) is None


def test_detect_currency():
    assert detect_currency("Total : 12 €") == "EUR"
    assert detect_currency("Total: $12") == "USD"
    assert detect_currency("Total 12 gbp") == "GBP"
    assert detect_currency("Total 12") is None

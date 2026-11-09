from datetime import date

import pytest

from docparse.schema import Line
from docparse.validate import CHECK_NAMES, CHECKS, TOLERANCE, VAT_TOLERANCE, validate
from helpers import good_invoice

TODAY = date(2026, 11, 5)


def test_consistent_invoice_has_no_issue():
    assert validate(good_invoice(), TODAY) == []


@pytest.mark.parametrize("attribute", ["number", "date", "supplier", "subtotal", "total"])
def test_missing_required_field(attribute):
    issues = validate(good_invoice(**{attribute: None}), TODAY)
    assert any(i.startswith("champ manquant") for i in issues)


def test_no_lines():
    assert any("aucune ligne" in i for i in validate(good_invoice(lines=[]), TODAY))


def test_line_arithmetic_tolerance_boundary():
    ok = good_invoice(lines=[Line("A", 3, 3.33, 9.99), Line("B", 1, 90.01, 90.01)])
    assert not any("ligne incohérente" in i for i in validate(ok, TODAY))
    off_by_two_cents = good_invoice(lines=[Line("A", 3, 3.33, 10.01), Line("B", 1, 89.99, 89.99)])
    assert any("ligne incohérente" in i for i in validate(off_by_two_cents, TODAY))


def test_sum_of_lines_must_match_subtotal_within_one_cent():
    assert not any("somme des lignes" in i for i in validate(good_invoice(subtotal=100.01, vat_amount=20.00, total=120.01), TODAY))
    assert any("somme des lignes" in i for i in validate(good_invoice(subtotal=100.02, vat_amount=20.00, total=120.02), TODAY))


def test_subtotal_plus_vat_must_match_total():
    assert any("≠ total" in i for i in validate(good_invoice(total=121.00), TODAY))
    assert not any("≠ total" in i for i in validate(good_invoice(total=120.01), TODAY))


def test_vat_rate_consistency_and_tolerance():
    assert not any("TVA (" in i for i in validate(good_invoice(vat_amount=20.02, total=120.02), TODAY))
    assert any("% de" in i for i in validate(good_invoice(vat_amount=20.03, total=120.03), TODAY))


def test_vat_rate_check_skipped_without_rate():
    assert validate(good_invoice(vat_rate=None), TODAY) == []


def test_missing_vat_line_with_gap_between_subtotal_and_total():
    issues = validate(good_invoice(vat_amount=None, vat_rate=None), TODAY)
    assert any("sans ligne de TVA" in i for i in issues)


def test_missing_vat_line_is_fine_when_total_equals_subtotal():
    assert validate(good_invoice(vat_amount=None, vat_rate=None, total=100.00), TODAY) == []


def test_date_range():
    assert any("improbable" in i for i in validate(good_invoice(date=date(1999, 12, 31)), TODAY))
    assert not any("improbable" in i for i in validate(good_invoice(date=date(2000, 1, 1)), TODAY))
    assert not any("improbable" in i for i in validate(good_invoice(date=date(2027, 11, 6)), TODAY))
    assert any("improbable" in i for i in validate(good_invoice(date=date(2027, 11, 7)), TODAY))


def test_known_suppliers_case_insensitive_and_flags_typos():
    known = frozenset({"atelier modèle sas"})
    assert validate(good_invoice(), TODAY, known) == []
    assert validate(good_invoice(supplier="ATELIER MODÈLE SAS"), TODAY, known) == []
    issues = validate(good_invoice(supplier="Ate1ier Modèle SAS"), TODAY, known)
    assert any("fournisseur inconnu" in i for i in issues)


def test_supplier_check_inactive_without_list_or_with_empty_list():
    assert validate(good_invoice(supplier="Inconnu SA"), TODAY) == []
    assert validate(good_invoice(supplier="Inconnu SA"), TODAY, frozenset()) == []


def test_tolerance_constants_documented_values():
    assert TOLERANCE == 0.01 and VAT_TOLERANCE == 0.02


# --- skip : désactiver un contrôle nommé -------------------------------------------------------------

KNOWN = frozenset({"atelier modèle sas"})
# nom du contrôle -> (facture qui le déclenche, fournisseurs connus, extrait du message qu'il produit)
SKIP_CASES = {
    "required": (good_invoice(number=None), None, "champ manquant"),
    "known-supplier": (good_invoice(supplier="Inconnu SA"), KNOWN, "fournisseur inconnu"),
    "lines": (good_invoice(lines=[]), None, "aucune ligne"),
    "date": (good_invoice(date=date(1999, 12, 31)), None, "improbable"),
    "line-amount": (good_invoice(lines=[Line("A", 2, 10.00, 21.00), Line("B", 4, 20.00, 79.00)]), None, "ligne incohérente"),
    "lines-sum": (good_invoice(subtotal=100.05, total=120.05), None, "somme des lignes"),
    "vat-total": (good_invoice(total=121.00), None, "≠ total"),
    "vat-rate": (good_invoice(vat_amount=25.00, total=125.00), None, "% de"),
    "vat-gap": (good_invoice(vat_amount=None, vat_rate=None, total=130.00), None, "sans ligne de TVA"),
}


def test_every_named_check_has_a_skip_case():
    assert set(SKIP_CASES) == set(CHECK_NAMES) and len(CHECK_NAMES) == len(set(CHECK_NAMES))
    assert all(description for _, description in CHECKS)


@pytest.mark.parametrize("name", CHECK_NAMES)
def test_skip_removes_exactly_that_check(name):
    invoice, known, fragment = SKIP_CASES[name]
    default = validate(invoice, TODAY, known)
    assert any(fragment in issue for issue in default), "le cas doit déclencher son contrôle"
    skipped = validate(invoice, TODAY, known, skip=[name])
    assert skipped == [issue for issue in default if fragment not in issue]  # les autres alertes restent


@pytest.mark.parametrize("name", CHECK_NAMES)
def test_skipping_another_check_keeps_this_one(name):
    invoice, known, fragment = SKIP_CASES[name]
    other = next(n for n in CHECK_NAMES if n != name and n != "required")
    assert any(fragment in issue for issue in validate(invoice, TODAY, known, skip=[other]))


def test_skip_accepts_any_iterable_and_everything_can_be_skipped():
    broken = good_invoice(number=None, lines=[], total=999.0, date=date(1999, 1, 1))
    assert validate(broken, TODAY)
    assert validate(broken, TODAY, skip=(n for n in CHECK_NAMES)) == []
    assert validate(broken, TODAY, skip={"required"}) == validate(broken, TODAY, skip=("required", "required"))


def test_unknown_check_name_is_an_error_not_a_silent_no_op():
    with pytest.raises(ValueError, match=r"contrôle inconnu : lines-sm \(contrôles disponibles : required, known-supplier"):
        validate(good_invoice(), TODAY, skip=["lines-sm"])
    with pytest.raises(ValueError, match="bogus, nope"):
        validate(good_invoice(), TODAY, skip=["nope", "bogus", "lines"])

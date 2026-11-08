import math

import pytest

from docparse.evaluate import compare, evaluate, wilson
from docparse.schema import Extraction, Invoice, Line
from helpers import good_invoice

TRUTH = {
    "supplier": "Atelier Modèle SAS", "number": "F-2026-0001", "date": "2026-06-15", "currency": "EUR",
    "subtotal": 100.0, "vat_amount": 20.0, "total": 120.0, "lines": [20.0, 80.0], "template": "T1",
}


def test_wilson_known_values():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson(5, 10)
    assert (lo, hi) == pytest.approx((0.2366, 0.7634), abs=1e-3)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=1e-3)
    assert all(math.isnan(x) for x in wilson(0, 0))


def test_compare_all_correct():
    assert all(compare(good_invoice(), TRUTH).values())


@pytest.mark.parametrize("field,change", [
    ("supplier", dict(supplier="Autre")), ("number", dict(number="F-2026-0002")),
    ("currency", dict(currency="USD")), ("subtotal", dict(subtotal=100.01)), ("vat_amount", dict(vat_amount=None)),
    ("total", dict(total=119.0)), ("lines", dict(lines=[Line("A", 2, 10.0, 20.0)])),
    ("lines", dict(lines=[Line("A", 2, 10.0, 20.0), Line("B", 4, 20.0, 81.0)])),
])
def test_compare_detects_each_field(field, change):
    verdicts = compare(good_invoice(**change), TRUTH)
    assert verdicts[field] is False
    assert sum(not ok for ok in verdicts.values()) == 1


def test_compare_supplier_is_case_insensitive_and_date_checked():
    assert compare(good_invoice(supplier="ATELIER MODÈLE SAS"), TRUTH)["supplier"]
    assert not compare(good_invoice(date=None), TRUTH)["date"]


def test_money_tolerance_is_half_a_cent():
    assert compare(good_invoice(total=120.004), TRUTH)["total"]
    assert not compare(good_invoice(total=120.006), TRUTH)["total"]


def _ext(name, invoice, issues=()):
    return Extraction(name, invoice, list(issues))


def test_counts_silent_errors_flagged_errors_and_false_alarms():
    truth = {n: dict(TRUTH, template=t) for n, t in [("ok", "T1"), ("flagged_wrong", "T1"), ("silent_wrong", "T2"), ("false_alarm", "T2")]}
    results = [
        _ext("ok", good_invoice()),
        _ext("flagged_wrong", good_invoice(total=1.0), ["total manquant"]),
        _ext("silent_wrong", good_invoice(number="F-2026-0O01")),
        _ext("false_alarm", good_invoice(), ["alerte inutile"]),
    ]
    ev = evaluate(results, truth)
    assert ev.documents == 4
    assert (ev.overall.fully_correct, ev.overall.wrong, ev.overall.flagged_wrong, ev.overall.silent_errors, ev.overall.false_alarms) == (2, 2, 1, 1, 1)
    assert ev.silent_error_files == ["silent_wrong"]
    assert ev.by_template["T1"].documents == 2 and ev.by_template["T2"].silent_errors == 1
    assert ev.field_correct["number"] == 3 and ev.field_correct["total"] == 3


def test_unmatched_documents_are_reported_not_counted():
    ev = evaluate([_ext("a", good_invoice()), _ext("extra", Invoice())], {"a": TRUTH, "missing": TRUTH})
    assert ev.documents == 1
    assert ev.not_in_truth == ["extra"] and ev.not_processed == ["missing"]

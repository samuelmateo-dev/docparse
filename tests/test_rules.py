from datetime import date

import pytest

from docparse import rules
from docparse.evaluate import compare
from docparse.synth import generate

T1 = """FACTURE N° F-2026-0042
Fournisseur : Boulangerie Exemple SARL
Date : 12/10/2026
Date d'échéance : 11/11/2026

Désignation                    Qté         PU HT      Montant HT
Pain de campagne                10          2,50           25,00
Conseil (heure)                  3        120,00          360,00

Total HT : 385,00 €
TVA 20 % : 77,00 €
Total TTC : 462,00 €"""

T2 = """INVOICE #INV-86750
From: Demo Logistics Ltd
Issued: 2026-08-27
Payment due: 2026-09-26
Item                           Qty    Unit price          Amount
Network cable 5 m               16        123.11        1,969.76
Subtotal: $1,969.76
VAT (8.25%): $162.51
Total due: $2,132.27"""


def test_t1_full_extraction():
    inv = rules.extract(T1)
    assert (inv.number, inv.supplier, inv.currency) == ("F-2026-0042", "Boulangerie Exemple SARL", "EUR")
    assert inv.date == date(2026, 10, 12)
    assert (inv.subtotal, inv.vat_rate, inv.vat_amount, inv.total) == (385.0, 20.0, 77.0, 462.0)
    assert [(l.description, l.quantity, l.unit_price, l.amount) for l in inv.lines] == [
        ("Pain de campagne", 10, 2.5, 25.0), ("Conseil (heure)", 3, 120.0, 360.0)]


def test_currency_symbol_before_amount_regression():
    """Bug trouvé par l'évaluation : les montants en « $1,234.50 » n'étaient pas lus (17 factures sur 17 fausses)."""
    inv = rules.extract(T2)
    assert (inv.subtotal, inv.vat_rate, inv.vat_amount, inv.total) == (1969.76, 8.25, 162.51, 2132.27)
    assert inv.currency == "USD" and inv.date == date(2026, 8, 27)


def test_issue_date_preferred_over_due_date_even_when_due_comes_first():
    text = "FACTURE N° A-1\nÉchéance : 01/12/2026\nDate : 01/11/2026\nTotal TTC : 10,00 €"
    assert rules.extract(text).date == date(2026, 11, 1)


def test_only_due_date_present_gives_none():
    assert rules.extract("FACTURE N° A-1\nDate d'échéance : 01/12/2026").date is None


def test_french_month_name_date():
    assert rules.extract("Facture numéro 2026/0042\nÉmise le 5 octobre 2026").date == date(2026, 10, 5)


def test_unknown_month_or_impossible_date_gives_none():
    assert rules.extract("Émise le 5 smarch 2026").date is None
    assert rules.extract("Date : 31/02/2026").date is None


def test_total_ht_is_not_taken_as_total():
    inv = rules.extract("Total HT : 100,00 €")
    assert inv.subtotal == 100.0 and inv.total is None


def test_unknown_labels_stay_none_instead_of_guessing():
    inv = rules.extract("Facture numéro 2026/0042\nBase imposable : 100,00 EUR\nNet à payer : 120,00 EUR")
    assert inv.subtotal is None and inv.total is None and inv.supplier is None


def test_vat_without_rate():
    inv = rules.extract("VAT: $12.00")
    assert inv.vat_amount == 12.0 and inv.vat_rate is None


def test_number_needs_a_digit():
    assert rules.extract("FACTURE\nDate : 01/11/2026").number is None


def test_line_item_with_thousands_separators():
    inv = rules.extract("Serveur dédié                    2      1 250,00         2 500,00")
    assert [(l.quantity, l.unit_price, l.amount) for l in inv.lines] == [(2, 1250.0, 2500.0)]


def test_header_row_is_not_a_line():
    assert rules.extract("Désignation      Qté     PU HT     Montant HT").lines == []


def test_clean_t1_and_t2_documents_are_extracted_perfectly():
    docs = [d for d in generate(80, seed=3, noise_rate=0.0) if d.truth["template"] in ("T1", "T2")]
    assert len(docs) > 30
    for doc in docs:
        verdicts = compare(rules.extract(doc.text), doc.truth)
        assert all(verdicts.values()), (doc.name, verdicts)


def test_t3_documents_are_never_silently_wrong_on_totals():
    docs = [d for d in generate(80, seed=3, noise_rate=0.0) if d.truth["template"] == "T3"]
    assert docs
    for doc in docs:
        inv = rules.extract(doc.text)
        assert inv.total is None and inv.subtotal is None  # il s'abstient

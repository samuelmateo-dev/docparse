"""Règles supplémentaires (--rules) : ce qu'elles ajoutent, ce qu'elles refusent, et ce qu'elles ne changent pas."""
import json
from datetime import date
from pathlib import Path

import pytest

from docparse import pipeline, rules
from docparse.rules import RulesError, build_rules, extract

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_FILE = ROOT / "examples" / "rules.example.json"


def with_rules(text: str, config: dict):
    return extract(text, build_rules(config))


# --- Ce que les libellés ajoutés permettent de lire -------------------------------------------------

def test_custom_total_and_subtotal_labels_are_read():
    text = "Facture numéro 2026/0042\nBase imposable : 100,00 EUR\nNet à payer : 120,00 EUR"
    before = extract(text)
    assert before.subtotal is None and before.total is None  # sans règle : jamais de devinette
    after = with_rules(text, {"labels": {"subtotal": ["base imposable"], "total": ["net à payer"]}})
    assert (after.subtotal, after.total) == (100.0, 120.0)


def test_added_label_wins_over_the_generic_one():
    """Un « Total » générique placé avant ne doit pas masquer le « Net à payer » que tu as déclaré."""
    text = "Total : 50,00 €\nNet à payer : 120,00 €"
    assert extract(text).total == 50.0
    assert with_rules(text, {"labels": {"total": ["net à payer"]}}).total == 120.0


def test_custom_invoice_number_supplier_and_vat_labels():
    text = "Pièce n° P-2026-9\nRaison sociale : Atelier Exemple\nImpôt 20 % : 20,00 €"
    before = extract(text)
    assert before.number is None and before.supplier is None and before.vat_amount is None
    after = with_rules(text, {"labels": {"invoice_number": ["pièce"], "supplier": ["raison sociale"], "vat": ["impôt"]}})
    assert (after.number, after.supplier, after.vat_rate, after.vat_amount) == ("P-2026-9", "Atelier Exemple", 20.0, 20.0)


def test_custom_date_label_prefers_the_labelled_date():
    text = "Commande du 01/01/2026\nÉtablie le 05/11/2026"
    assert extract(text).date == date(2026, 1, 1)  # aucun libellé connu : on prend la première date
    assert with_rules(text, {"labels": {"date": ["établie le"]}}).date == date(2026, 11, 5)


def test_custom_due_date_label_is_not_mistaken_for_the_issue_date():
    """« Date limite » contient « date » : sans règle elle passait pour la date d'émission (erreur silencieuse)."""
    text = "Date limite : 01/12/2026\nDate : 01/11/2026"
    assert extract(text).date == date(2026, 12, 1)
    assert with_rules(text, {"labels": {"due_date": ["date limite"]}}).date == date(2026, 11, 1)


def test_custom_months():
    assert extract("Date : 5 enero 2026").date is None
    assert with_rules("Date : 5 enero 2026", {"months": {"enero": 1}}).date == date(2026, 1, 5)
    german = {"months": {"märz": 3}}
    assert extract("Datum : 5 März 2026").date is None
    assert with_rules("Datum : 5 März 2026", german).date == date(2026, 3, 5)
    assert with_rules("Date : 5 MÄRZ 2026", german).date == date(2026, 3, 5)  # majuscules accentuées aussi
    assert with_rules("Date : 5 Enero 2026", {"months": {"Enero": 1}}).date == date(2026, 1, 5)


def test_a_month_that_is_not_declared_is_still_not_guessed():
    assert with_rules("Date : 5 smarch 2026", {"months": {"märz": 3}}).date is None


# --- Texte littéral, pas expression régulière --------------------------------------------------------

def test_labels_are_literal_text_not_regular_expressions():
    config = {"labels": {"total": ["n.a.p"]}}
    assert with_rules("n.a.p : 5,00 €", config).total == 5.0
    assert with_rules("nXaXp : 5,00 €", config).total is None  # le point ne veut pas dire « n'importe quel caractère »
    plus = {"labels": {"total": ["a+b"]}}
    assert with_rules("a+b : 5,00 €", plus).total == 5.0
    assert with_rules("aab : 5,00 €", plus).total is None  # « + » n'est pas un quantificateur
    pipe = {"labels": {"total": ["a|b"]}}
    assert with_rules("a|b : 5,00 €", pipe).total == 5.0
    assert with_rules("a : 5,00 €", pipe).total is None  # « | » n'est pas une alternative


def test_labels_ignore_case_and_extra_spaces():
    config = {"labels": {"total": ["net   à payer"]}}
    assert with_rules("NET  À  PAYER : 12,00 €", config).total == 12.0


# --- Les règles s'ajoutent, ne remplacent pas -------------------------------------------------------

def test_empty_and_example_rules_do_not_change_default_reading():
    from test_rules import T1, T2  # mêmes documents que les tests de lecture d'origine

    for config in ({}, {"labels": {}, "months": {}}, json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))):
        built = build_rules(config)
        assert extract(T1, built) == extract(T1)
        assert extract(T2, built) == extract(T2)


def _sample(extractor=rules.extract):
    folder = ROOT / "data" / "sample"
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))["files"]
    results = pipeline.process(folder / "invoices", extractor=extractor, today=date(2026, 11, 5))
    return truth, results


def test_example_rules_only_change_the_unknown_layout_of_the_sample():
    """Le fichier d'exemple fait lire la mise en page inconnue T3 (« Base imposable », « Net à payer »), et
    ne touche à aucun des 50 autres documents. Il a été écrit en regardant T3 : c'est une illustration, pas une mesure."""
    truth, plain = _sample()
    _, custom = _sample(rules.extractor(rules.load_rules(EXAMPLE_FILE)))
    for before, after in zip(plain, custom):
        if truth[before.source]["template"] != "T3":
            assert (before.invoice, before.issues) == (after.invoice, after.issues), before.source
        else:
            assert before.invoice.subtotal is None and before.invoice.total is None
            assert after.invoice.subtotal is not None and after.invoice.total is not None
            assert after.issues == ["champ manquant : fournisseur"]  # le fournisseur n'a pas de libellé dans cette mise en page


def test_default_label_list_matches_what_is_actually_recognised():
    """`docparse rules` affiche DEFAULT_LABELS : chaque libellé affiché doit vraiment être lu, et pour le bon champ."""
    for label in rules.DEFAULT_LABELS["invoice_number"]:
        assert extract(f"{label} N° A-12").number == "A-12", label
    for label in rules.DEFAULT_LABELS["supplier"]:
        assert extract(f"{label} : X Corp").supplier == "X Corp", label
    for label in rules.DEFAULT_LABELS["date"]:
        assert extract(f"Commande 01/01/2026\n{label} : 12/10/2026").date == date(2026, 10, 12), label
    for label in rules.DEFAULT_LABELS["due_date"]:
        assert extract(f"{label} : 01/12/2026\nDate : 01/11/2026").date == date(2026, 11, 1), label
    for label in rules.DEFAULT_LABELS["subtotal"]:
        inv = extract(f"{label} : 100,00 €")
        assert (inv.subtotal, inv.total) == (100.0, None), label
    for label in rules.DEFAULT_LABELS["total"]:
        inv = extract(f"{label} : 462,00 €")
        assert (inv.total, inv.subtotal) == (462.0, None), label
    for label in rules.DEFAULT_LABELS["vat"]:
        inv = extract(f"{label} 20 % : 20,00 €")
        assert (inv.vat_rate, inv.vat_amount) == (20.0, 20.0), label
    assert set(rules.DEFAULT_LABELS) == set(rules.LABEL_FIELDS)


def test_total_h_t_with_dots_is_read_as_subtotal():
    """Bug de la version d'origine : « Total H.T. » n'était jamais reconnu (un \\b ne peut pas suivre un point)."""
    assert extract("Total H.T. : 100,00 €").subtotal == 100.0
    assert extract("Total H.T. 100,00 €").subtotal == 100.0
    assert extract("Total HTX : 100,00 €").subtotal is None  # le libellé reste un mot entier


# --- Fichiers invalides : message clair, jamais d'ignorance silencieuse ----------------------------

BAD_CONFIGS = [
    ([], r"objet JSON"),
    ("texte", r"objet JSON"),
    ({"labelz": {}}, r"labelz : clé inconnue"),
    ({"labels": []}, r"labels : objet attendu"),
    ({"labels": {"totl": ["x"]}}, r"labels\.totl : champ inconnu \(champs acceptés : invoice_number"),
    ({"labels": {"total": "net"}}, r"labels\.total : liste de libellés attendue"),
    ({"labels": {"total": [3]}}, r"labels\.total\[0\] : texte attendu, reçu 3"),
    ({"labels": {"total": ["ok", ""]}}, r"labels\.total\[1\] : libellé vide"),
    ({"labels": {"total": ["   "]}}, r"libellé vide"),
    ({"labels": {"total": ["net à payer :"]}}, r"doit commencer et finir par une lettre ou un chiffre"),
    ({"labels": {"total": [".net"]}}, r"doit commencer et finir"),
    ({"labels": {"total": ["a" * 61]}}, r"trop long \(61 caractères, 60 au maximum\)"),
    ({"labels": {"total": ["a%d" % i for i in range(51)]}}, r"51 libellés, 50 au maximum"),
    ({"months": []}, r"months : objet attendu"),
    ({"months": {"en ero": 1}}, r"months\.en ero : un nom de mois ne contient que des lettres"),
    ({"months": {"mars2": 3}}, r"que des lettres"),
    ({"months": {"enero": 13}}, r"months\.enero : numéro de mois entre 1 et 12 attendu, reçu 13"),
    ({"months": {"enero": 0}}, r"entre 1 et 12"),
    ({"months": {"enero": "1"}}, r"entre 1 et 12 attendu, reçu \"1\""),
    ({"months": {"enero": True}}, r"entre 1 et 12"),
    ({"months": {"enero": 1.5}}, r"entre 1 et 12"),
]


@pytest.mark.parametrize("config, message", BAD_CONFIGS)
def test_invalid_configuration_is_refused_with_a_clear_message(config, message):
    with pytest.raises(RulesError, match=message):
        build_rules(config)


def test_exactly_fifty_labels_and_sixty_characters_are_accepted():
    build_rules({"labels": {"total": ["a%d" % i for i in range(50)]}})
    build_rules({"labels": {"total": ["a" * 60]}})


def test_load_rules_reports_unreadable_and_malformed_files(tmp_path):
    with pytest.raises(RulesError, match="illisible"):
        rules.load_rules(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{ pas du json", encoding="utf-8")
    with pytest.raises(RulesError, match="JSON invalide"):
        rules.load_rules(bad)
    typo = tmp_path / "typo.json"
    typo.write_text(json.dumps({"labels": {"totl": ["x"]}}), encoding="utf-8")
    with pytest.raises(RulesError, match="champ inconnu"):
        rules.load_rules(typo)


def test_example_file_matches_the_text_shown_by_docparse_rules():
    assert EXAMPLE_FILE.read_text(encoding="utf-8") == rules.EXAMPLE_TEXT
    assert json.loads(rules.EXAMPLE_TEXT) == rules.EXAMPLE_CONFIG
    built = rules.load_rules(EXAMPLE_FILE)
    inv = extract("Pièce n° P-1\nRaison sociale : X\nBase imposable : 10,00 €\nNet à payer : 12,00 €\nDate limite : 01/12/2026\nDate : 5 enero 2026", built)
    assert (inv.number, inv.supplier, inv.subtotal, inv.total, inv.date) == ("P-1", "X", 10.0, 12.0, date(2026, 1, 5))

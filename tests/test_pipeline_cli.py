import csv
import json
from datetime import date
from pathlib import Path

import pytest
from fpdf import FPDF
from pypdf import PdfWriter

from docparse import pipeline
from docparse.cli import main
from docparse.evaluate import evaluate

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 5)


def _truth(folder: str) -> dict:
    return json.loads((ROOT / "data" / folder / "truth.json").read_text(encoding="utf-8"))["files"]


def _run(folder: str, suppliers: bool = False):
    sup = pipeline.load_suppliers(ROOT / "data" / "sample" / "suppliers.txt") if suppliers else None
    return evaluate(pipeline.process(ROOT / "data" / folder / "invoices", today=TODAY, known_suppliers=sup), _truth(folder))


def test_sample_results_are_pinned():
    """Chiffres du README. Si ce test casse, soit le code a changé, soit le README est faux."""
    o = _run("sample").overall
    assert (o.documents, o.fully_correct, o.flagged_wrong, o.silent_errors, o.false_alarms) == (60, 45, 13, 2, 0)


def test_noisy_sample_results_are_pinned_without_and_with_supplier_list():
    o = _run("sample_noisy").overall
    assert (o.fully_correct, o.flagged_wrong, o.silent_errors) == (19, 36, 5)
    o = _run("sample_noisy", suppliers=True).overall
    assert (o.fully_correct, o.flagged_wrong, o.silent_errors) == (19, 38, 3)


def test_unknown_layout_t3_is_always_flagged_never_silent():
    ev = _run("sample")
    t3 = ev.by_template["T3"]
    assert t3.documents > 0 and t3.fully_correct == 0 and t3.silent_errors == 0


def _blank_pdf(path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.output(str(path))


def test_pdf_without_text_layer_is_flagged(tmp_path):
    _blank_pdf(tmp_path / "scan.pdf")
    [result] = pipeline.process(tmp_path, today=TODAY)
    assert result.issues == [pipeline.NO_TEXT]


def test_corrupt_pdf_is_flagged_not_crashing(tmp_path):
    (tmp_path / "cassé.pdf").write_bytes(b"%PDF-1.4 ceci n'est pas un vrai pdf")
    [result] = pipeline.process(tmp_path, today=TODAY)
    assert result.needs_review and "illisible" in result.issues[0]


def test_encrypted_pdf_is_flagged(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    try:
        writer.encrypt("secret", algorithm="RC4-40")
    except Exception as exc:  # pragma: no cover - dépend des bibliothèques de chiffrement installées
        pytest.skip(f"chiffrement indisponible : {exc}")
    with (tmp_path / "protégé.pdf").open("wb") as handle:
        writer.write(handle)
    [result] = pipeline.process(tmp_path, today=TODAY)
    assert result.needs_review and "mot de passe" in result.issues[0]


def test_unsupported_file_passed_directly_is_flagged_and_ignored_in_folders(tmp_path):
    doc = tmp_path / "facture.docx"
    doc.write_bytes(b"x")
    [direct] = pipeline.process(doc, today=TODAY)
    assert "format non géré" in direct.issues[0]
    assert pipeline.process(tmp_path, today=TODAY) == []


def test_txt_files_are_read(tmp_path):
    (tmp_path / "a.txt").write_text("FACTURE N° A-1\nFournisseur : X\nDate : 01/11/2026\nTotal HT : 10,00 €\nTotal TTC : 10,00 €", encoding="utf-8")
    [result] = pipeline.process(tmp_path, today=TODAY)
    assert result.invoice.number == "A-1" and result.invoice.total == 10.0


def test_csv_output(tmp_path):
    results = pipeline.process(ROOT / "data" / "sample" / "invoices", today=TODAY)
    out = tmp_path / "out.csv"
    pipeline.write_csv(results, out, ";")
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM : Excel lit bien les accents
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter=";"))
    assert rows[0] == pipeline.COLUMNS and len(rows) == 61
    assert any("Modèle" in row[1] for row in rows[1:])
    flagged = [r for r in rows[1:] if r[10] == "oui"]
    assert len(flagged) == sum(r.needs_review for r in results) and all(r[11] for r in flagged)


def test_cli_run_and_exit_codes(tmp_path, capsys):
    assert main(["run", str(ROOT / "data" / "sample" / "invoices"), "--out", str(tmp_path / "o.csv")]) == 0
    out = capsys.readouterr().out
    assert "60 document(s) lu(s)" in out and (tmp_path / "o.csv").exists()
    assert main(["run", str(tmp_path / "inexistant")]) == 1
    assert main(["run", str(tmp_path)]) == 1  # dossier sans document
    assert main(["run", str(ROOT / "data" / "sample" / "invoices"), "--suppliers", str(tmp_path / "nope.txt")]) == 1


def test_cli_eval(capsys):
    code = main(["eval", str(ROOT / "data" / "sample_noisy" / "invoices"), "--truth", str(ROOT / "data" / "sample_noisy" / "truth.json")])
    out = capsys.readouterr().out
    assert code == 0 and "5 ERREURS SILENCIEUSES" in out and "IC 95 %" in out and "mesurent la méthode" in out
    assert main(["eval", str(ROOT / "data" / "sample" / "invoices"), "--truth", "/nope.json"]) == 1


def test_load_suppliers_ignores_blank_lines_and_case(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("Atelier Modèle SAS\n\n  Garage Fictif  \n", encoding="utf-8")
    assert pipeline.load_suppliers(f) == frozenset({"atelier modèle sas", "garage fictif"})


# --- Règles supplémentaires (--rules) et contrôles désactivables (--skip) ---------------------------

PIECE = """Pièce n° P-2026-77
Raison sociale : Atelier Test
Établie le 12/10/2026
Désignation                    Qté         PU HT      Montant HT
Pain                            10          2,50           25,00
Base imposable : 25,00 €
TVA 20 % : 5,00 €
Net à payer : 30,00 €"""
NO_LINES = "FACTURE N° A-1\nFournisseur : X\nDate : 01/11/2026\nTotal HT : 10,00 €\nTVA 20 % : 2,00 €\nTotal TTC : 12,00 €"


def test_cli_rules_lists_defaults_checks_and_file_format(capsys):
    from docparse import rules
    from docparse.validate import CHECK_NAMES

    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    for labels in rules.DEFAULT_LABELS.values():
        for label in labels:
            assert label in out
    assert all(name in out for name in CHECK_NAMES)
    assert rules.EXAMPLE_TEXT.rstrip() in out and "--rules" in out and "--skip" in out
    assert "janvier" in out and "december" in out


def test_cli_run_with_rules_reads_a_layout_the_defaults_do_not(tmp_path, capsys):
    (tmp_path / "piece.txt").write_text(PIECE, encoding="utf-8")
    rules_file = tmp_path / "regles.json"
    rules_file.write_text(json.dumps({"labels": {
        "invoice_number": ["pièce"], "supplier": ["raison sociale"], "subtotal": ["base imposable"], "total": ["net à payer"]}}), encoding="utf-8")

    assert main(["run", str(tmp_path / "piece.txt")]) == 0
    out = capsys.readouterr().out
    assert "1 document(s) lu(s), 1 à vérifier" in out and "Règles supplémentaires" not in out

    assert main(["run", str(tmp_path / "piece.txt"), "--rules", str(rules_file), "--out", str(tmp_path / "o.csv")]) == 0
    out = capsys.readouterr().out
    assert "1 document(s) lu(s), 0 à vérifier" in out and "P-2026-77" in out and "30.00" in out
    assert f"Règles supplémentaires : {rules_file}" in out
    row = list(csv.reader((tmp_path / "o.csv").read_text(encoding="utf-8-sig").splitlines()))[1]
    assert row[1] == "Atelier Test" and row[10] == "non"


def test_cli_run_with_skip_and_the_reminder_about_what_it_costs(tmp_path, capsys):
    doc = tmp_path / "sans_lignes.txt"
    doc.write_text(NO_LINES, encoding="utf-8")
    assert main(["run", str(doc)]) == 0
    assert "1 à vérifier" in capsys.readouterr().out

    assert main(["run", str(doc), "--skip", "lines"]) == 0
    out = capsys.readouterr().out
    assert "0 à vérifier" in out and "Contrôles désactivés : lines." in out and "moins fiable" in out

    assert main(["run", str(doc), "--skip", " lines , lines-sum ,"]) == 0  # espaces et virgule finale tolérés
    assert "Contrôles désactivés : lines, lines-sum." in capsys.readouterr().out

    assert main(["run", str(doc), "--skip", ""]) == 0
    out = capsys.readouterr().out
    assert "1 à vérifier" in out and "Contrôles désactivés" not in out


def test_cli_eval_default_output_is_unchanged_and_skip_shows_the_cost(capsys):
    sample = ["eval", str(ROOT / "data" / "sample" / "invoices"), "--truth", str(ROOT / "data" / "sample" / "truth.json")]
    assert main(sample) == 0
    default = capsys.readouterr().out
    assert default.startswith("Évaluation sur 60 documents (intervalles de Wilson à 95 %)\n\n")
    assert "Contrôles désactivés" not in default and "2 ERREURS SILENCIEUSES" in default

    assert main([*sample, "--skip", "required"]) == 0
    out = capsys.readouterr().out
    assert "Contrôles désactivés : required." in out and "14 ERREURS SILENCIEUSES" in out  # 2 avec tous les contrôles


def test_skipping_checks_turns_flagged_errors_into_silent_ones():
    """La raison pour laquelle --skip est signalé à chaque fois : 13 erreurs signalées deviennent silencieuses."""
    folder = ROOT / "data" / "sample"
    full = evaluate(pipeline.process(folder / "invoices", today=TODAY), _truth("sample")).overall
    cut = evaluate(pipeline.process(folder / "invoices", today=TODAY, skip=["required"]), _truth("sample")).overall
    assert (full.fully_correct, full.flagged_wrong, full.silent_errors) == (45, 13, 2)
    assert (cut.fully_correct, cut.flagged_wrong, cut.silent_errors) == (45, 1, 14)


def test_cli_rules_and_skip_apply_to_eval_too(tmp_path, capsys):
    sample = ["eval", str(ROOT / "data" / "sample" / "invoices"), "--truth", str(ROOT / "data" / "sample" / "truth.json")]
    assert main(sample) == 0
    plain = capsys.readouterr().out
    assert "subtotal     50/60" in plain and "total        48/60" in plain
    assert main([*sample, "--rules", str(ROOT / "examples" / "rules.example.json")]) == 0
    out = capsys.readouterr().out
    assert "Règles supplémentaires" in out
    assert "subtotal     60/60" in out and "total        58/60" in out  # la mise en page T3 devient lisible
    assert "T3       10          0              10              0" in out  # ... mais reste signalée (fournisseur sans libellé)


@pytest.mark.parametrize("make_args, message", [
    (lambda d: ["--rules", str(d / "absent.json")], "Introuvable"),
    (lambda d: ["--rules", str(d / "mal.json")], "Règles invalides"),
    (lambda d: ["--rules", str(d / "faute.json")], "labels.totl : champ inconnu"),
    (lambda d: ["--skip", "lines-sm"], "contrôle inconnu : lines-sm"),
    (lambda d: ["--skip", "lines,bogus"], "contrôle inconnu : bogus"),
])
def test_invalid_rules_or_skip_stop_before_anything_is_read(tmp_path, capsys, make_args, message):
    (tmp_path / "doc.txt").write_text(NO_LINES, encoding="utf-8")
    (tmp_path / "mal.json").write_text("{ pas du json", encoding="utf-8")
    (tmp_path / "faute.json").write_text(json.dumps({"labels": {"totl": ["x"]}}), encoding="utf-8")
    truth = ROOT / "data" / "sample" / "truth.json"
    for command in (["run", str(tmp_path / "doc.txt")], ["eval", str(ROOT / "data" / "sample" / "invoices"), "--truth", str(truth)]):
        assert main([*command, *make_args(tmp_path)]) == 1
        captured = capsys.readouterr()
        assert message in captured.err and captured.out == ""


def test_pipeline_rejects_unknown_check_names_even_when_there_is_nothing_to_validate(tmp_path):
    with pytest.raises(ValueError, match="contrôle inconnu : bogus"):
        pipeline.process(tmp_path, skip=["bogus"])  # dossier vide
    with pytest.raises(ValueError, match="contrôle inconnu : bogus"):
        pipeline.process_text("vide.txt", "", skip=["bogus"])  # texte vide : renvoyé avant toute validation

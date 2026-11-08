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

"""Du dossier de documents à la liste d'extractions contrôlées."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

from . import rules
from .pdf import UnreadableDocument, read_text
from .schema import Extraction, ExtractionError, Invoice
from .validate import check_skip, validate

EXTENSIONS = {".pdf", ".txt"}
NO_TEXT = "aucun texte lisible (scan ? l'OCR n'est pas géré)"

Extractor = Callable[[str], Invoice]


def load_suppliers(path: Path) -> frozenset[str]:
    """Un nom de fournisseur par ligne."""
    names = {line.strip().casefold() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    return frozenset(names)


def list_documents(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)


def process_text(
    source: str,
    text: str,
    extractor: Extractor = rules.extract,
    today: date | None = None,
    known_suppliers: frozenset[str] | None = None,
    skip: Iterable[str] = (),
) -> Extraction:
    skip = check_skip(skip)
    if not text.strip():
        return Extraction(source, Invoice(), [NO_TEXT])
    try:
        invoice = extractor(text)
    except ExtractionError as exc:
        return Extraction(source, Invoice(), [f"extraction impossible : {exc}"])
    return Extraction(source, invoice, validate(invoice, today, known_suppliers, skip))


def process(
    root: Path,
    extractor: Extractor = rules.extract,
    today: date | None = None,
    known_suppliers: frozenset[str] | None = None,
    skip: Iterable[str] = (),
) -> list[Extraction]:
    skip = check_skip(skip)
    results = []
    for path in list_documents(root):
        try:
            text = read_text(path)
        except UnreadableDocument as exc:
            results.append(Extraction(path.name, Invoice(), [str(exc)]))
            continue
        results.append(process_text(path.name, text, extractor, today, known_suppliers, skip))
    return results


COLUMNS = ["fichier", "fournisseur", "numero", "date", "devise", "total_ht", "taux_tva", "tva", "total", "nb_lignes", "a_verifier", "problemes"]


def to_rows(results: Iterable[Extraction]) -> list[list[str]]:
    rows = []
    for r in results:
        i = r.invoice
        rows.append([
            r.source, i.supplier or "", i.number or "", i.date.isoformat() if i.date else "", i.currency or "",
            "" if i.subtotal is None else f"{i.subtotal:.2f}", "" if i.vat_rate is None else f"{i.vat_rate:g}",
            "" if i.vat_amount is None else f"{i.vat_amount:.2f}", "" if i.total is None else f"{i.total:.2f}",
            str(len(i.lines)), "oui" if r.needs_review else "non", " | ".join(r.issues),
        ])
    return rows


def write_csv(results: Iterable[Extraction], path: Path, delimiter: str = ",") -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:  # utf-8-sig : Excel lit bien les accents
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(COLUMNS)
        writer.writerows(to_rows(results))

"""Extraction par règles : fonctionne sur les mises en page prévues, et le dit quand ce n'est pas le cas.

Chaque champ non reconnu reste à None : c'est ``validate`` qui le signale. Une règle ne devine jamais.
"""
from __future__ import annotations

import re
from datetime import date

from .amounts import AMOUNT, CURRENCY_PATTERN, detect_currency, parse_amount
from .schema import Invoice, Line

MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_NUMBER = re.compile(
    r"^\s*(?:facture|invoice)\s*(?:n\s*[°o]\.?|numéro|number|no\.?|#)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/_.]*\d[A-Z0-9\-/_.]*)",
    re.IGNORECASE | re.MULTILINE,
)
_SUPPLIER = re.compile(r"^\s*(?:fournisseur|émetteur|from|seller|vendor)\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DATE_PATTERNS = (
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),  # jj/mm/aaaa (pas mm/jj)
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})\s+([A-Za-zéèûôîàç]+)\s+(\d{4})\b"), lambda m: (int(m[3]), MONTHS.get(m[2].lower(), 0), int(m[1]))),
)
_DUE = re.compile(r"échéance|echeance|due\b|paiement|payment", re.IGNORECASE)
_DATE_LABEL = re.compile(r"date|issued|émis|emis", re.IGNORECASE)

_CUR = r"(?:€|\$|£|EUR|USD|GBP)?"
_TOTAL_LABELS = (r"total\s*ttc", r"total\s*due", r"amount\s*due", r"total\s*à\s*payer", r"total\s*amount", r"total")
_SUBTOTAL_LABELS = (r"total\s*ht", r"total\s*h\.t\.", r"sub-?total", r"sous[- ]total")
_VAT = re.compile(
    rf"^\s*(?:tva|vat|tax|taxe)\s*(?:\(?\s*(\d+(?:[.,]\d+)?)\s*%\s*\)?)?\s*[:\-]?\s*{_CUR}\s*({AMOUNT})\s*{_CUR}\s*$", re.IGNORECASE
)
_LINE = re.compile(
    rf"^\s*(?P<d>.+?)\s{{2,}}(?P<q>\d+(?:[.,]\d+)?)\s{{2,}}(?P<u>{AMOUNT})\s*{_CUR}\s{{2,}}(?P<a>{AMOUNT})\s*{_CUR}\s*$"
)


def _labelled_amount(lines: list[str], labels: tuple[str, ...]) -> float | None:
    for label in labels:
        pattern = re.compile(rf"^\s*{label}\b\s*[:\-]?\s*{_CUR}\s*({AMOUNT})\s*{_CUR}\s*$", re.IGNORECASE)
        for line in lines:
            match = pattern.match(line)
            if match:
                return parse_amount(match.group(1))
    return None


def _find_date(lines: list[str]) -> date | None:
    labelled: date | None = None
    fallback: date | None = None
    for line in lines:
        if _DUE.search(line):
            continue
        for pattern, build in _DATE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            try:
                found = date(*build(match))
            except ValueError:
                continue
            if _DATE_LABEL.search(line) and labelled is None:
                labelled = found
            elif fallback is None:
                fallback = found
            break
    return labelled or fallback


def extract(text: str) -> Invoice:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    invoice = Invoice()
    match = _NUMBER.search(text)
    invoice.number = match.group(1).strip(".") if match else None
    match = _SUPPLIER.search(text)
    invoice.supplier = match.group(1) if match else None
    invoice.date = _find_date(lines)
    invoice.currency = detect_currency(text)
    invoice.subtotal = _labelled_amount(lines, _SUBTOTAL_LABELS)
    invoice.total = _labelled_amount(lines, _TOTAL_LABELS)
    for line in lines:
        vat = _VAT.match(line)
        if vat:
            invoice.vat_rate = parse_amount(vat.group(1)) if vat.group(1) else None
            invoice.vat_amount = parse_amount(vat.group(2))
            break
    for line in lines:
        row = _LINE.match(line)
        if not row:
            continue
        quantity, unit, amount = parse_amount(row["q"]), parse_amount(row["u"]), parse_amount(row["a"])
        if None in (quantity, unit, amount):
            continue
        invoice.lines.append(Line(row["d"].strip(), quantity, unit, amount))
    return invoice

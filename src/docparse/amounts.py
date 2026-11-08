"""Montants et devises : formats français (1 234,50) et anglais (1,234.50)."""
from __future__ import annotations

import re

CURRENCY_PATTERN = re.compile(r"€|\$|£|\b(?:EUR|USD|GBP)\b", re.IGNORECASE)
_CURRENCY_CODES = {"€": "EUR", "$": "USD", "£": "GBP", "EUR": "EUR", "USD": "USD", "GBP": "GBP"}

# Un montant : groupes de milliers séparés par UN espace (normal, insécable ou fin), un point ou une virgule, puis 1-2 décimales.
AMOUNT = r"(?:\d{1,3}(?:[   .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"


def detect_currency(text: str) -> str | None:
    match = CURRENCY_PATTERN.search(text)
    return _CURRENCY_CODES[match.group(0).upper()] if match else None


def parse_amount(raw: str) -> float | None:
    """Convertit un montant écrit en nombre, ou None si le texte n'en est pas un.

    Règle pour un seul séparateur, présent une seule fois : exactement 3 chiffres après lui => séparateur
    de milliers (« 1,234 » vaut 1234) ; sinon séparateur décimal. Les montants à trois décimales ne sont
    donc pas gérés.
    """
    cleaned = CURRENCY_PATTERN.sub("", raw)
    cleaned = re.sub(r"[\s  ]", "", cleaned)
    if not re.fullmatch(r"-?\d[\d.,]*", cleaned):
        return None
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("-")
    if "," in cleaned and "." in cleaned:
        decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
    else:
        for separator in (",", "."):
            if separator in cleaned:
                head, _, tail = cleaned.rpartition(separator)
                if cleaned.count(separator) > 1 or (len(tail) == 3 and 0 < len(head) <= 3):
                    cleaned = cleaned.replace(separator, "")
                else:
                    cleaned = f"{head}.{tail}"
                break
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative else value

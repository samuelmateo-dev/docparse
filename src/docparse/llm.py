"""Extraction par modèle de langage : une interface, PAS de client réseau.

Tu fournis ``complete(prompt) -> str`` (l'appel à l'API de ton choix). Le résultat passe ensuite par les
mêmes contrôles de cohérence que l'extraction par règles : une erreur d'arithmétique du modèle est signalée.

Non testé contre une vraie API dans ce dépôt : les tests utilisent un faux modèle. Envoyer des factures de
clients à un service externe pose une question de protection des données à régler avec le client avant.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

from .amounts import parse_amount
from .schema import ExtractionError, Invoice, Line

PROMPT = (
    "Tu extrais les données d'une facture. Réponds UNIQUEMENT par un objet JSON avec les clés : "
    "supplier, number, date (AAAA-MM-JJ), currency (EUR, USD ou GBP), "
    "lines (liste d'objets description, quantity, unit_price, amount), subtotal, vat_rate, vat_amount, total. "
    "Mets null pour toute information absente du texte. N'invente rien.\n\nTEXTE :\n{text}"
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_amount(str(value))


def _text(value: Any) -> str | None:
    return str(value).strip() or None if value is not None else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def parse_response(raw: str) -> Invoice:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ExtractionError("la réponse ne contient pas d'objet JSON")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"JSON invalide ({exc.msg})") from exc
    lines = []
    for item in data.get("lines") or []:
        if not isinstance(item, dict):
            continue
        quantity, unit, amount = _number(item.get("quantity")), _number(item.get("unit_price")), _number(item.get("amount"))
        if None not in (quantity, unit, amount):
            lines.append(Line(str(item.get("description") or ""), quantity, unit, amount))
    currency = _text(data.get("currency"))
    return Invoice(
        supplier=_text(data.get("supplier")), number=_text(data.get("number")), date=_date(data.get("date")),
        currency=currency.upper() if currency else None, lines=lines, subtotal=_number(data.get("subtotal")),
        vat_rate=_number(data.get("vat_rate")), vat_amount=_number(data.get("vat_amount")), total=_number(data.get("total")),
    )


class LLMExtractor:
    def __init__(self, complete: Callable[[str], str]):
        self._complete = complete

    def __call__(self, text: str) -> Invoice:
        return parse_response(self._complete(PROMPT.format(text=text)))

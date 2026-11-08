"""Structures de données."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class ExtractionError(Exception):
    """Un extracteur n'a pas pu produire de facture exploitable (ex. réponse LLM qui n'est pas du JSON)."""


@dataclass
class Line:
    description: str
    quantity: float
    unit_price: float
    amount: float


@dataclass
class Invoice:
    supplier: str | None = None
    number: str | None = None
    date: date | None = None
    currency: str | None = None
    lines: list[Line] = field(default_factory=list)
    subtotal: float | None = None
    vat_rate: float | None = None
    vat_amount: float | None = None
    total: float | None = None


@dataclass
class Extraction:
    """Résultat pour UN document : la facture lue, et ce qui cloche (liste vide = rien à signaler)."""

    source: str
    invoice: Invoice
    issues: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

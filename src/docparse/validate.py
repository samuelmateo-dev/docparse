"""Contrôles de cohérence : ils attrapent les erreurs de lecture QUI CASSENT L'ARITHMÉTIQUE.

Ils ne voient pas une faute dans un nom ou un numéro de facture : voir ``evaluate`` (erreurs silencieuses).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .schema import Invoice

TOLERANCE = 0.01  # un centime, pour les arrondis
VAT_TOLERANCE = 0.02  # la TVA est arrondie une fois sur le total, pas ligne par ligne

def _differs(a: float, b: float, tolerance: float) -> bool:
    """Écart strictement supérieur à la tolérance. L'arrondi à 6 décimales retire le bruit des flottants :
    sans lui, 100.01 - 100.00 vaut 0.0100000000000051 et un écart d'exactement un centime serait refusé."""
    return round(abs(a - b), 6) > tolerance


REQUIRED = (
    ("number", "numéro de facture"),
    ("date", "date"),
    ("supplier", "fournisseur"),
    ("subtotal", "total HT"),
    ("total", "total à payer"),
)


# Contrôles nommés, dans l'ordre où leurs messages sont produits. Le nom sert à en désactiver un (``skip``).
CHECKS: tuple[tuple[str, str], ...] = (
    ("required", "champs obligatoires présents (numéro, date, fournisseur, total HT, total à payer)"),
    ("known-supplier", "fournisseur présent dans ta liste (seulement si tu en donnes une)"),
    ("lines", "au moins une ligne de facture lue"),
    ("date", "date plausible (entre 2000 et un an dans le futur)"),
    ("line-amount", "quantité × prix unitaire = montant, ligne par ligne"),
    ("lines-sum", "somme des lignes = total HT"),
    ("vat-total", "HT + TVA = total à payer"),
    ("vat-rate", "TVA = taux × HT"),
    ("vat-gap", "pas d'écart entre HT et total quand aucune ligne de TVA n'est lue"),
)
CHECK_NAMES = tuple(name for name, _ in CHECKS)


def check_skip(skip: Iterable[str]) -> frozenset[str]:
    """Noms de contrôles à ignorer, vérifiés : un nom inconnu (faute de frappe) lève ValueError."""
    skipped = frozenset(skip)
    unknown = sorted(skipped - set(CHECK_NAMES))
    if unknown:
        raise ValueError(f"contrôle inconnu : {', '.join(unknown)} (contrôles disponibles : {', '.join(CHECK_NAMES)})")
    return skipped


def validate(
    invoice: Invoice,
    today: date | None = None,
    known_suppliers: frozenset[str] | None = None,
    skip: Iterable[str] = (),
) -> list[str]:
    """``known_suppliers`` : noms (en minuscules) de tes fournisseurs habituels ; un nom absent de la liste est signalé.

    ``skip`` : noms de contrôles à ne pas faire (voir ``CHECKS``). Un nom inconnu est une erreur, pas un oubli silencieux.
    """
    skipped = check_skip(skip)
    today = today or date.today()
    issues: list[str] = []

    def active(name: str) -> bool:
        return name not in skipped

    if active("required"):
        for attribute, label in REQUIRED:
            if getattr(invoice, attribute) is None:
                issues.append(f"champ manquant : {label}")
    if active("known-supplier") and known_suppliers and invoice.supplier is not None and invoice.supplier.casefold() not in known_suppliers:
        issues.append(f"fournisseur inconnu : {invoice.supplier!r} (faute de lecture ?)")
    if active("lines") and not invoice.lines:
        issues.append("aucune ligne de facture lue")
    if active("date") and invoice.date is not None and not (date(2000, 1, 1) <= invoice.date <= today + timedelta(days=366)):
        issues.append(f"date improbable : {invoice.date.isoformat()}")
    if active("line-amount"):
        for line in invoice.lines:
            if _differs(line.quantity * line.unit_price, line.amount, TOLERANCE):
                issues.append(f"ligne incohérente : {line.description!r} ({line.quantity} × {line.unit_price} ≠ {line.amount})")
    if active("lines-sum") and invoice.lines and invoice.subtotal is not None:
        lines_sum = round(sum(line.amount for line in invoice.lines), 2)
        if _differs(lines_sum, invoice.subtotal, TOLERANCE):
            issues.append(f"somme des lignes ({lines_sum}) ≠ total HT ({invoice.subtotal})")
    if active("vat-total") and invoice.subtotal is not None and invoice.vat_amount is not None and invoice.total is not None:
        if _differs(invoice.subtotal + invoice.vat_amount, invoice.total, TOLERANCE):
            issues.append(f"HT ({invoice.subtotal}) + TVA ({invoice.vat_amount}) ≠ total ({invoice.total})")
    if active("vat-rate") and invoice.subtotal is not None and invoice.vat_rate is not None and invoice.vat_amount is not None:
        if _differs(invoice.subtotal * invoice.vat_rate / 100, invoice.vat_amount, VAT_TOLERANCE):
            issues.append(f"TVA ({invoice.vat_amount}) ≠ {invoice.vat_rate} % de {invoice.subtotal}")
    if active("vat-gap") and invoice.vat_amount is None and invoice.subtotal is not None and invoice.total is not None:
        if _differs(invoice.subtotal, invoice.total, TOLERANCE):
            issues.append("écart entre HT et total sans ligne de TVA lue")
    return issues

from datetime import date

from docparse.schema import Invoice, Line


def good_invoice(**overrides) -> Invoice:
    """Une facture cohérente : 2 lignes, HT 100, TVA 20 %, total 120."""
    base = dict(
        supplier="Atelier Modèle SAS", number="F-2026-0001", date=date(2026, 6, 15), currency="EUR",
        lines=[Line("A", 2, 10.00, 20.00), Line("B", 4, 20.00, 80.00)],
        subtotal=100.00, vat_rate=20.0, vat_amount=20.00, total=120.00,
    )
    base.update(overrides)
    return Invoice(**base)

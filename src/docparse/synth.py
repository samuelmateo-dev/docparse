"""Factures FICTIVES pour démontrer et mesurer l'outil. Tous les noms sont inventés.

Trois mises en page : T1 (français, €), T2 (anglais, $) et T3 (français, libellés que l'extracteur ne connaît
pas : il doit s'abstenir et signaler le document). Avec la probabilité ``noise_rate``, un caractère est
remplacé par un sosie (0↔O, 1↔l, 5↔S, 8↔B) comme le ferait un OCR approximatif.

Les chiffres obtenus sur ces documents mesurent la MÉTHODE, pas la performance sur de vrais documents :
le générateur et l'extracteur ont été écrits par la même personne.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

FR_SUPPLIERS = ["Boulangerie Exemple SARL", "Atelier Modèle SAS", "Garage Fictif et Fils", "Papeterie Démo SARL", "Domaine Test SCEA"]
EN_SUPPLIERS = ["Demo Harbor LLC", "Example Supplies Inc.", "Sample Parts Co.", "Demo Logistics Ltd"]
FR_ITEMS = ["Pain de campagne", "Viennoiseries (lot de 12)", "Maintenance mensuelle", "Impression A4 (500 f.)", "Hébergement web annuel", "Câble réseau 5 m", "Conseil (heure)", "Carton d'emballage"]
EN_ITEMS = ["Web hosting (annual)", "Printer paper (500 sh.)", "Consulting (hour)", "Network cable 5 m", "Packing box", "Monthly maintenance"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
LOOKALIKE = {"0": "O", "O": "0", "1": "l", "l": "1", "5": "S", "S": "5", "8": "B", "B": "8"}


@dataclass(frozen=True)
class SyntheticInvoice:
    name: str
    text: str
    truth: dict


def _fmt(value: float, style: str) -> str:
    english = f"{value:,.2f}"
    if style == "en":
        return english
    if style == "fr":
        return english.replace(",", " ").replace(".", ",")
    return english.replace(",", "_").replace(".", ",").replace("_", ".")  # style « de » : 1.234,50


def _rows(items: list[tuple[str, int, float, float]], style: str) -> list[str]:
    return [f"{desc:<28}  {qty:>4}  {_fmt(unit, style):>12}  {_fmt(amount, style):>14}" for desc, qty, unit, amount in items]


def _render(template: str, d: dict, rng: random.Random) -> list[str]:
    due = date.fromisoformat(d["date"]) + timedelta(days=30)
    issued = date.fromisoformat(d["date"])
    if template == "T1":
        style, cur = "fr", " €"
        head = [f"FACTURE N° {d['number']}", f"Fournisseur : {d['supplier']}", f"Date : {issued:%d/%m/%Y}", f"Date d'échéance : {due:%d/%m/%Y}", ""]
        cols = f"{'Désignation':<28}  {'Qté':>4}  {'PU HT':>12}  {'Montant HT':>14}"
        foot = [f"Total HT : {_fmt(d['subtotal'], style)}{cur}", f"TVA {d['vat_rate']:g} % : {_fmt(d['vat_amount'], style)}{cur}", f"Total TTC : {_fmt(d['total'], style)}{cur}"]
    elif template == "T2":
        style, cur = "en", ""
        head = [f"INVOICE #{d['number']}", f"From: {d['supplier']}", f"Issued: {issued:%Y-%m-%d}", f"Payment due: {due:%Y-%m-%d}", ""]
        cols = f"{'Item':<28}  {'Qty':>4}  {'Unit price':>12}  {'Amount':>14}"
        foot = [f"Subtotal: ${_fmt(d['subtotal'], style)}", f"VAT ({d['vat_rate']:g}%): ${_fmt(d['vat_amount'], style)}", f"Total due: ${_fmt(d['total'], style)}"]
    else:  # T3 : libellés inconnus de l'extracteur, fournisseur en en-tête sans étiquette
        style, cur = "de", " EUR"
        head = [d["supplier"], f"Facture numéro {d['number']}", f"Émise le {issued.day} {MONTHS_FR[issued.month - 1]} {issued.year}", ""]
        cols = f"{'Désignation':<28}  {'Qté':>4}  {'PU HT':>12}  {'Montant HT':>14}"
        foot = [f"Base imposable : {_fmt(d['subtotal'], style)}{cur}", f"TVA {d['vat_rate']:g} % : {_fmt(d['vat_amount'], style)}{cur}", f"Net à payer : {_fmt(d['total'], style)}{cur}"]
    return head + [cols] + _rows(d["_items"], style) + [""] + foot


def _corrupt(lines: list[str], rng: random.Random) -> list[str]:
    spots = [(i, j) for i, line in enumerate(lines) for j, ch in enumerate(line) if ch in LOOKALIKE]
    if not spots:
        return lines
    i, j = rng.choice(spots)
    out = list(lines)
    out[i] = out[i][:j] + LOOKALIKE[out[i][j]] + out[i][j + 1 :]
    return out


def generate(n: int, seed: int = 7, noise_rate: float = 0.15) -> list[SyntheticInvoice]:
    rng = random.Random(seed)
    noise_rng = random.Random(f"bruit-{seed}")  # flux séparé : le contenu des factures ne dépend pas du taux de bruit
    invoices = []
    for k in range(1, n + 1):
        template = rng.choices(["T1", "T2", "T3"], weights=[40, 35, 25])[0]
        english = template == "T2"
        items = []
        for _ in range(rng.randint(1, 5)):
            qty = rng.randint(1, 20)
            unit = round(rng.uniform(2, 180), 2)
            items.append((rng.choice(EN_ITEMS if english else FR_ITEMS), qty, unit, round(qty * unit, 2)))
        subtotal = round(sum(item[3] for item in items), 2)
        rate = rng.choice([0, 8.25, 20] if english else [5.5, 10, 20])
        vat = round(subtotal * rate / 100, 2)
        issued = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
        number = {"T1": f"F-2026-{k:04d}", "T2": f"INV-{rng.randint(10000, 99999)}", "T3": f"2026/{k:04d}"}[template]
        record = {
            "supplier": rng.choice(EN_SUPPLIERS if english else FR_SUPPLIERS), "number": number, "date": issued.isoformat(),
            "currency": {"T1": "EUR", "T2": "USD", "T3": "EUR"}[template], "subtotal": subtotal, "vat_rate": rate,
            "vat_amount": vat, "total": round(subtotal + vat, 2), "lines": [item[3] for item in items], "template": template,
            "_items": items,
        }
        lines = _render(template, record, rng)
        corrupted = noise_rng.random() < noise_rate
        if corrupted:
            lines = _corrupt(lines, noise_rng)
        truth = {key: value for key, value in record.items() if key != "_items"}
        truth["corrupted"] = corrupted
        invoices.append(SyntheticInvoice(f"facture_{k:03d}.pdf", "\n".join(lines), truth))
    return invoices

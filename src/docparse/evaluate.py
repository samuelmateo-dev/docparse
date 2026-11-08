"""Mesure de la précision contre des documents dont on connaît la bonne réponse.

Ce qui compte pour un client n'est pas seulement le taux de champs justes, mais les ERREURS SILENCIEUSES :
documents faux ET non signalés « à vérifier ».
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .schema import Extraction, Invoice

FIELDS = ("supplier", "number", "date", "currency", "subtotal", "vat_amount", "total", "lines")
MONEY_TOLERANCE = 0.005


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de Wilson à 95 % d'une proportion (fiable même pour de petits échantillons)."""
    if n == 0:
        return (math.nan, math.nan)
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, center - half), min(1.0, center + half))


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < MONEY_TOLERANCE


def compare(invoice: Invoice, truth: dict) -> dict[str, bool]:
    return {
        "supplier": invoice.supplier is not None and invoice.supplier.casefold() == truth["supplier"].casefold(),
        "number": invoice.number == truth["number"],
        "date": invoice.date is not None and invoice.date.isoformat() == truth["date"],
        "currency": invoice.currency == truth["currency"],
        "subtotal": _close(invoice.subtotal, truth["subtotal"]),
        "vat_amount": _close(invoice.vat_amount, truth["vat_amount"]),
        "total": _close(invoice.total, truth["total"]),
        "lines": len(invoice.lines) == len(truth["lines"])
        and all(_close(line.amount, expected) for line, expected in zip(invoice.lines, truth["lines"])),
    }


@dataclass
class GroupStats:
    documents: int = 0
    fully_correct: int = 0
    wrong: int = 0
    flagged_wrong: int = 0
    false_alarms: int = 0

    @property
    def silent_errors(self) -> int:
        return self.wrong - self.flagged_wrong


@dataclass
class Evaluation:
    documents: int
    field_correct: dict[str, int]
    overall: GroupStats
    by_template: dict[str, GroupStats]
    silent_error_files: list[str] = field(default_factory=list)
    not_in_truth: list[str] = field(default_factory=list)
    not_processed: list[str] = field(default_factory=list)


def evaluate(results: list[Extraction], truth: dict[str, dict]) -> Evaluation:
    by_name = {r.source: r for r in results}
    names = sorted(set(by_name) & set(truth))
    field_correct = {name: 0 for name in FIELDS}
    overall = GroupStats()
    by_template: dict[str, GroupStats] = {}
    silent: list[str] = []
    for name in names:
        result, expected = by_name[name], truth[name]
        verdicts = compare(result.invoice, expected)
        for key, ok in verdicts.items():
            field_correct[key] += ok
        correct = all(verdicts.values())
        for group in (overall, by_template.setdefault(expected.get("template", "?"), GroupStats())):
            group.documents += 1
            if correct:
                group.fully_correct += 1
                group.false_alarms += result.needs_review
            else:
                group.wrong += 1
                group.flagged_wrong += result.needs_review
        if not correct and not result.needs_review:
            silent.append(name)
    return Evaluation(
        documents=len(names), field_correct=field_correct, overall=overall, by_template=dict(sorted(by_template.items())),
        silent_error_files=silent, not_in_truth=sorted(set(by_name) - set(truth)), not_processed=sorted(set(truth) - set(by_name)),
    )

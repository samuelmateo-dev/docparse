"""Extraction par règles : fonctionne sur les mises en page prévues, et le dit quand ce n'est pas le cas.

Chaque champ non reconnu reste à None : c'est ``validate`` qui le signale. Une règle ne devine jamais.

Les libellés lus par défaut peuvent être complétés (``build_rules`` / fichier ``--rules``) : on AJOUTE des
libellés ou des noms de mois, on n'enlève rien. Sans configuration, le comportement est exactement celui
des règles d'origine.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

from .amounts import AMOUNT, CURRENCY_PATTERN, detect_currency, parse_amount
from .schema import Invoice, Line

MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_CUR = r"(?:€|\$|£|EUR|USD|GBP)?"
_BASE_MONTH_LETTERS = "A-Za-zéèûôîàç"

# Libellés par défaut, sous forme d'expressions régulières (comme à l'origine).
_NUMBER_LABELS = ("facture", "invoice")
_SUPPLIER_LABELS = ("fournisseur", "émetteur", "from", "seller", "vendor")
_DATE_LABELS = ("date", "issued", "émis", "emis")
_DUE_LABELS = ("échéance", "echeance", r"due\b", "paiement", "payment")
_VAT_LABELS = ("tva", "vat", "tax", "taxe")
_TOTAL_LABELS = (r"total\s*ttc", r"total\s*due", r"amount\s*due", r"total\s*à\s*payer", r"total\s*amount", r"total")
_SUBTOTAL_LABELS = (r"total\s*ht", r"total\s*h\.t\.", r"sub-?total", r"sous[- ]total")

# Les mêmes, lisibles, pour ``docparse rules``. Un test vérifie que chacun est bien reconnu.
DEFAULT_LABELS: dict[str, tuple[str, ...]] = {
    "invoice_number": ("facture", "invoice"),
    "supplier": ("fournisseur", "émetteur", "from", "seller", "vendor"),
    "date": ("date", "issued", "émis", "emis"),
    "due_date": ("échéance", "echeance", "due", "paiement", "payment"),
    "subtotal": ("total ht", "total h.t.", "subtotal", "sub-total", "sous-total", "sous total"),
    "total": ("total ttc", "total due", "amount due", "total à payer", "total amount", "total"),
    "vat": ("tva", "vat", "tax", "taxe"),
}
LABEL_FIELDS = tuple(DEFAULT_LABELS)
MAX_LABELS_PER_FIELD = 50
MAX_LABEL_LENGTH = 60


# Exemple de fichier de règles : même texte dans examples/rules.example.json et dans ``docparse rules``
# (un test vérifie qu'ils sont identiques).
EXAMPLE_TEXT = """{
  "labels": {
    "total": ["net à payer", "montant dû"],
    "subtotal": ["base imposable"],
    "invoice_number": ["pièce"],
    "supplier": ["raison sociale"],
    "due_date": ["date limite"]
  },
  "months": { "enero": 1, "märz": 3 }
}
"""
EXAMPLE_CONFIG: dict[str, Any] = json.loads(EXAMPLE_TEXT)


class RulesError(ValueError):
    """Configuration de règles invalide : le message dit où et pourquoi."""


@dataclass(frozen=True)
class Rules:
    number: re.Pattern[str]
    supplier: re.Pattern[str]
    date_label: re.Pattern[str]
    due: re.Pattern[str]
    vat: re.Pattern[str]
    date_patterns: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], tuple[int, int, int]]], ...]
    subtotal_labels: tuple[str, ...]
    total_labels: tuple[str, ...]


def _label_regex(label: str) -> str:
    """Libellé de l'utilisateur -> expression régulière : texte littéral, espaces souples."""
    return r"\s+".join(re.escape(word) for word in label.split())


def _check_label(path: str, label: Any) -> str:
    if not isinstance(label, str):
        raise RulesError(f"{path} : texte attendu, reçu {json.dumps(label, ensure_ascii=False)}")
    clean = label.strip()
    if not clean:
        raise RulesError(f"{path} : libellé vide")
    if len(clean) > MAX_LABEL_LENGTH:
        raise RulesError(f"{path} : libellé trop long ({len(clean)} caractères, {MAX_LABEL_LENGTH} au maximum)")
    if not (clean[0].isalnum() and clean[-1].isalnum()):
        raise RulesError(
            f"{path} : {clean!r} doit commencer et finir par une lettre ou un chiffre "
            "(la ponctuation de fin, comme « : » ou « . », est déjà acceptée après le libellé)"
        )
    return clean


def _extra_labels(config: Mapping[str, Any]) -> dict[str, list[str]]:
    labels = config.get("labels", {})
    if not isinstance(labels, dict):
        raise RulesError("labels : objet attendu, par exemple {\"total\": [\"net à payer\"]}")
    for key in labels:
        if key not in LABEL_FIELDS:
            raise RulesError(f"labels.{key} : champ inconnu (champs acceptés : {', '.join(LABEL_FIELDS)})")
    out: dict[str, list[str]] = {}
    for key, values in labels.items():
        if not isinstance(values, list):
            raise RulesError(f"labels.{key} : liste de libellés attendue")
        if len(values) > MAX_LABELS_PER_FIELD:
            raise RulesError(f"labels.{key} : {len(values)} libellés, {MAX_LABELS_PER_FIELD} au maximum")
        out[key] = [_check_label(f"labels.{key}[{i}]", v) for i, v in enumerate(values)]
    return out


def _extra_months(config: Mapping[str, Any]) -> dict[str, int]:
    months = config.get("months", {})
    if not isinstance(months, dict):
        raise RulesError("months : objet attendu, par exemple {\"enero\": 1}")
    out: dict[str, int] = {}
    for name, number in months.items():
        if not name.isalpha():
            raise RulesError(f"months.{name} : un nom de mois ne contient que des lettres, sans espace ni chiffre")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 12:
            raise RulesError(f"months.{name} : numéro de mois entre 1 et 12 attendu, reçu {json.dumps(number)}")
        out[name.lower()] = number
    return out


def build_rules(config: Mapping[str, Any] | None = None) -> Rules:
    """Règles par défaut, complétées par ``config`` : ``{"labels": {champ: [libellés]}, "months": {nom: numéro}}``.

    Pour les montants (total, total HT), les libellés ajoutés sont essayés AVANT ceux d'origine : le libellé
    générique « total » ne doit pas masquer ton « net à payer ». Pour les autres champs, l'ordre ne change rien.
    """
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise RulesError("le fichier doit contenir un objet JSON { \"labels\": ..., \"months\": ... }")
    unknown = [k for k in config if k not in ("labels", "months")]
    if unknown:
        raise RulesError(f"{unknown[0]} : clé inconnue (clés acceptées : labels, months)")
    extra = _extra_labels(config)

    def alternation(field: str, defaults: tuple[str, ...]) -> str:
        return "|".join([*map(_label_regex, extra.get(field, [])), *defaults])

    def ordered(field: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
        return (*map(_label_regex, extra.get(field, [])), *defaults)

    extra_months = _extra_months(config)
    months = {**MONTHS, **extra_months}
    # Lettres acceptées dans un nom de mois : celles d'origine, plus celles des mois ajoutés (ex. « ä » pour « märz »).
    extra_letters = sorted({c for name in extra_months for ch in name for c in (ch.lower(), ch.upper()) if not re.fullmatch(f"[{_BASE_MONTH_LETTERS}]", c)})
    letters = _BASE_MONTH_LETTERS + "".join(extra_letters)
    date_patterns = (
        (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),  # jj/mm/aaaa (pas mm/jj)
        (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (re.compile(rf"\b(\d{{1,2}})\s+([{letters}]+)\s+(\d{{4}})\b"), lambda m: (int(m[3]), months.get(m[2].lower(), 0), int(m[1]))),
    )
    return Rules(
        number=re.compile(
            rf"^\s*(?:{alternation('invoice_number', _NUMBER_LABELS)})\s*(?:n\s*[°o]\.?|numéro|number|no\.?|#)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/_.]*\d[A-Z0-9\-/_.]*)",
            re.IGNORECASE | re.MULTILINE,
        ),
        supplier=re.compile(rf"^\s*(?:{alternation('supplier', _SUPPLIER_LABELS)})\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
        date_label=re.compile(alternation("date", _DATE_LABELS), re.IGNORECASE),
        due=re.compile(alternation("due_date", _DUE_LABELS), re.IGNORECASE),
        vat=re.compile(
            rf"^\s*(?:{alternation('vat', _VAT_LABELS)})\s*(?:\(?\s*(\d+(?:[.,]\d+)?)\s*%\s*\)?)?\s*[:\-]?\s*{_CUR}\s*({AMOUNT})\s*{_CUR}\s*$",
            re.IGNORECASE,
        ),
        date_patterns=date_patterns,
        subtotal_labels=ordered("subtotal", _SUBTOTAL_LABELS),
        total_labels=ordered("total", _TOTAL_LABELS),
    )


def load_rules(path: Path) -> Rules:
    """Lit un fichier JSON de règles supplémentaires (voir ``docparse rules``)."""
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RulesError(f"fichier illisible : {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RulesError(f"JSON invalide : {exc}") from exc
    return build_rules(config)


DEFAULT_RULES = build_rules()

_LINE = re.compile(
    rf"^\s*(?P<d>.+?)\s{{2,}}(?P<q>\d+(?:[.,]\d+)?)\s{{2,}}(?P<u>{AMOUNT})\s*{_CUR}\s{{2,}}(?P<a>{AMOUNT})\s*{_CUR}\s*$"
)


def _labelled_amount(lines: list[str], labels: tuple[str, ...]) -> float | None:
    for label in labels:
        pattern = re.compile(rf"^\s*{label}(?!\w)\s*[:\-]?\s*{_CUR}\s*({AMOUNT})\s*{_CUR}\s*$", re.IGNORECASE)
        for line in lines:
            match = pattern.match(line)
            if match:
                return parse_amount(match.group(1))
    return None


def _find_date(lines: list[str], rules: Rules) -> date | None:
    labelled: date | None = None
    fallback: date | None = None
    for line in lines:
        if rules.due.search(line):
            continue
        for pattern, build in rules.date_patterns:
            match = pattern.search(line)
            if not match:
                continue
            try:
                found = date(*build(match))
            except ValueError:
                continue
            if rules.date_label.search(line) and labelled is None:
                labelled = found
            elif fallback is None:
                fallback = found
            break
    return labelled or fallback


def extract(text: str, rules: Rules | None = None) -> Invoice:
    rules = rules or DEFAULT_RULES
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    invoice = Invoice()
    match = rules.number.search(text)
    invoice.number = match.group(1).strip(".") if match else None
    match = rules.supplier.search(text)
    invoice.supplier = match.group(1) if match else None
    invoice.date = _find_date(lines, rules)
    invoice.currency = detect_currency(text)
    invoice.subtotal = _labelled_amount(lines, rules.subtotal_labels)
    invoice.total = _labelled_amount(lines, rules.total_labels)
    for line in lines:
        vat = rules.vat.match(line)
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


def extractor(rules: Rules) -> Callable[[str], Invoice]:
    """Extracteur utilisable par ``pipeline.process`` avec des règles personnalisées."""
    return lambda text: extract(text, rules)

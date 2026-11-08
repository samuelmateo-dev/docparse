import json
from datetime import date

import pytest

from docparse.llm import LLMExtractor, PROMPT, parse_response
from docparse.pipeline import process_text
from docparse.schema import ExtractionError

GOOD = {
    "supplier": "Atelier Modèle SAS", "number": "F-1", "date": "2026-06-15", "currency": "eur",
    "lines": [{"description": "A", "quantity": 2, "unit_price": "10,00", "amount": 20}],
    "subtotal": "20,00", "vat_rate": 20, "vat_amount": 4, "total": "24,00",
}


def test_parse_clean_json_and_fenced_json_with_text_around():
    for raw in (json.dumps(GOOD), "Voici :\n```json\n" + json.dumps(GOOD) + "\n```\nBonne journée"):
        inv = parse_response(raw)
        assert inv.supplier == "Atelier Modèle SAS" and inv.date == date(2026, 6, 15) and inv.currency == "EUR"
        assert inv.total == 24.0 and inv.subtotal == 20.0 and inv.lines[0].unit_price == 10.0


def test_parse_nulls_and_garbage_values_become_none():
    inv = parse_response(json.dumps({"supplier": None, "date": "pas une date", "total": "beaucoup", "lines": ["x", {"description": "d"}]}))
    assert inv.supplier is None and inv.date is None and inv.total is None and inv.lines == []


@pytest.mark.parametrize("raw", ["pas de json", "{ cassé", "[1, 2]", ""])
def test_unusable_responses_raise(raw):
    with pytest.raises(ExtractionError):
        parse_response(raw)


def test_extractor_sends_the_document_text_in_the_prompt():
    seen = []
    LLMExtractor(lambda prompt: seen.append(prompt) or json.dumps(GOOD))("TEXTE-DE-LA-FACTURE")
    assert "TEXTE-DE-LA-FACTURE" in seen[0] and seen[0].startswith(PROMPT.split("{text}")[0])


def test_pipeline_flags_a_model_that_gets_the_arithmetic_wrong():
    wrong = dict(GOOD, total="25,00")
    result = process_text("f.pdf", "texte", LLMExtractor(lambda _: json.dumps(wrong)), today=date(2026, 11, 5))
    assert result.needs_review and any("≠ total" in i for i in result.issues)


def test_pipeline_flags_a_model_that_answers_garbage():
    result = process_text("f.pdf", "texte", LLMExtractor(lambda _: "désolé, je ne peux pas"), today=date(2026, 11, 5))
    assert result.needs_review and result.issues[0].startswith("extraction impossible")


def test_pipeline_accepts_a_correct_model_answer():
    result = process_text("f.pdf", "texte", LLMExtractor(lambda _: json.dumps(GOOD)), today=date(2026, 11, 5))
    assert result.issues == []

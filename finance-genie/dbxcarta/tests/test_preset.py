"""Non-live tests for the consumer preset."""

from __future__ import annotations

from finance_genie_dbxcarta import preset


def test_preset_questions_file_resolves() -> None:
    assert preset.questions_file.exists()
    assert preset.questions_file.name == "questions.json"


def test_preset_targets_single_catalog() -> None:
    text = preset.questions_file.read_text(encoding="utf-8")
    assert "graph-enriched-lakehouse" in text
    # Option (b): the silver/gold split must not survive the retarget.
    assert "graph-enriched-finance-silver" not in text
    assert "graph-enriched-finance-gold" not in text

"""Tests for the grounding panel's set-difference check."""

from __future__ import annotations

from grounding import DeclaredIdentifier, ground


def test_ground_marks_exact_match_as_retrieved() -> None:
    rows = ground(
        [DeclaredIdentifier(name="gold_accounts", source_tool="table_search")],
        {"gold_accounts"},
    )

    assert rows[0].retrieved is True


def test_ground_marks_table_qualified_column_as_retrieved() -> None:
    rows = ground(
        [DeclaredIdentifier(name="gold_accounts.account_id", source_tool="column_search")],
        {"account_id"},
    )

    assert rows[0].retrieved is True
    assert rows[0].name == "gold_accounts.account_id"


def test_ground_marks_unretrieved_name_as_not_retrieved() -> None:
    rows = ground(
        [DeclaredIdentifier(name="invented_column", source_tool="column_search")],
        {"account_id"},
    )

    assert rows[0].retrieved is False

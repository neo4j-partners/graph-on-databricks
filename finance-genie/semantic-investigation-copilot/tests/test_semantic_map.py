"""Tests for the semantic-map node caption fallback."""

from __future__ import annotations

from semantic_map import _node_caption


def test_node_caption_prefers_name() -> None:
    assert _node_caption({"name": "gold_accounts", "label": "Table"}, "fallback") == "gold_accounts"


def test_node_caption_falls_back_to_label_when_name_is_absent() -> None:
    assert _node_caption({"label": "Account"}, "fallback") == "Account"


def test_node_caption_falls_back_to_type_when_name_and_label_are_absent() -> None:
    assert _node_caption({"type": "REFERENCES"}, "fallback") == "REFERENCES"


def test_node_caption_uses_default_when_nothing_matches() -> None:
    assert _node_caption({}, "fallback") == "fallback"

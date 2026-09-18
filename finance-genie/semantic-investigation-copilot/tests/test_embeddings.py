"""Tests for NeoCarta embedding creation and stored-vector validation."""

from __future__ import annotations

import pytest
from neocarta import NodeLabel

import embeddings
from validate_embeddings import validate_embedding_state


def test_create_embeddings_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class StubConnector:
        def __init__(self, **kwargs: object) -> None:
            calls["init"] = kwargs

        def run(self, **kwargs: object) -> None:
            calls["run"] = kwargs

    driver = object()
    monkeypatch.setenv("EMBEDDING_MODEL", "databricks/test-embedding-model")
    monkeypatch.setattr(embeddings, "LiteLLMEmbeddingsConnector", StubConnector)

    embeddings.create_embeddings(driver, "semantic")  # type: ignore[arg-type]

    assert calls["init"] == {
        "neo4j_driver": driver,
        "embedding_model": "databricks/test-embedding-model",
        "database_name": "semantic",
    }
    assert calls["run"] == {"node_labels": [NodeLabel.TABLE, NodeLabel.COLUMN]}


def test_validate_embedding_state_accepts_complete_vectors() -> None:
    coverage = [
        {"label": "Table", "eligible": 17, "embedded": 17, "dimensions": [1024]},
        {"label": "Column", "eligible": 172, "embedded": 172, "dimensions": [1024]},
    ]
    indexes = [
        {
            "name": "table_vector_index",
            "state": "ONLINE",
            "labelsOrTypes": ["Table"],
            "properties": ["embedding"],
            "options": {"indexConfig": {"vector.dimensions": 1024}},
        },
        {
            "name": "column_vector_index",
            "state": "ONLINE",
            "labelsOrTypes": ["Column"],
            "properties": ["embedding"],
            "options": {"indexConfig": {"vector.dimensions": 1024}},
        },
    ]

    result = validate_embedding_state(coverage, indexes, 1024)

    assert result["Table"]["embedded"] == 17
    assert result["Column"]["dimensions"] == [1024]


def test_validate_embedding_state_rejects_partial_coverage() -> None:
    coverage = [
        {"label": "Table", "eligible": 17, "embedded": 16, "dimensions": [1024]},
        {"label": "Column", "eligible": 172, "embedded": 172, "dimensions": [1024]},
    ]

    with pytest.raises(RuntimeError, match="Table embedding coverage is incomplete"):
        validate_embedding_state(coverage, [], 1024)

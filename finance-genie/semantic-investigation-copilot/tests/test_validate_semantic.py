"""Tests for the semantic-store validation contract."""

from __future__ import annotations

import pytest

from validate_semantic import (
    EXPECTED_NODES,
    EXPECTED_RELATIONSHIPS,
    require_exact_counts,
    validate_indexes,
)


def test_exact_semantic_graph_counts_are_accepted() -> None:
    require_exact_counts(EXPECTED_NODES.copy(), EXPECTED_NODES, "node")
    require_exact_counts(EXPECTED_RELATIONSHIPS.copy(), EXPECTED_RELATIONSHIPS, "relationship")


def test_semantic_graph_count_drift_is_rejected() -> None:
    changed = EXPECTED_NODES.copy()
    changed["BusinessConcept"] -= 1
    with pytest.raises(RuntimeError, match="node counts"):
        require_exact_counts(changed, EXPECTED_NODES, "node")


def test_business_term_indexes_require_native_dimensions() -> None:
    indexes = [
        {
            "name": "businessterm_full_text_index",
            "type": "FULLTEXT",
            "state": "ONLINE",
        },
        {
            "name": "businessterm_vector_index",
            "type": "VECTOR",
            "state": "ONLINE",
            "options": {"indexConfig": {"vector.dimensions": 1024}},
        },
    ]
    validate_indexes(indexes)
    indexes[1]["options"]["indexConfig"]["vector.dimensions"] = 768
    with pytest.raises(RuntimeError, match="dimensions changed"):
        validate_indexes(indexes)

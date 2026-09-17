"""Tests for the strict base semantic-store contract."""

from __future__ import annotations

import pytest

from runtime_contract import (
    EXPECTED_CONSTRAINTS,
    EXPECTED_INDEXES,
    EXPECTED_NODE_COUNTS,
    EXPECTED_TABLES,
)
from validate_store import (
    validate_constraints,
    validate_counts,
    validate_indexes,
    validate_target,
)


def expected_indexes() -> list[dict]:
    """Build index records matching the validation contract."""
    return [
        {"name": name, "type": index_type, "state": state}
        for name, (index_type, state) in EXPECTED_INDEXES.items()
    ]


def expected_constraints() -> list[dict]:
    """Build constraint records matching the validation contract."""
    return [
        {
            "name": name,
            "type": constraint_type,
            "entityType": entity_type,
            "labelsOrTypes": list(labels),
            "properties": list(properties),
        }
        for name, (constraint_type, entity_type, labels, properties) in EXPECTED_CONSTRAINTS.items()
    ]


def test_accepts_exact_runtime_contract() -> None:
    validate_counts(EXPECTED_NODE_COUNTS.copy(), EXPECTED_NODE_COUNTS, "node")
    validate_indexes(expected_indexes())
    validate_constraints(expected_constraints())
    validate_target(
        [{"tables": sorted(EXPECTED_TABLES)}],
        [{"table": "gold_accounts", "column": "identity_cluster_id"}],
    )


def test_rejects_missing_index() -> None:
    indexes = expected_indexes()
    indexes.pop()

    with pytest.raises(RuntimeError, match="indexes are missing or invalid"):
        validate_indexes(indexes)


def test_rejects_wrong_constraint_property() -> None:
    constraints = expected_constraints()
    constraints[0]["properties"] = ["name"]

    with pytest.raises(RuntimeError, match="constraints are missing or invalid"):
        validate_constraints(constraints)


def test_rejects_count_drift() -> None:
    counts = EXPECTED_NODE_COUNTS.copy()
    counts["Column"] += 1

    with pytest.raises(RuntimeError, match="Unexpected node counts"):
        validate_counts(counts, EXPECTED_NODE_COUNTS, "node")


def test_rejects_table_inventory_drift() -> None:
    tables = set(EXPECTED_TABLES)
    tables.remove("gold_accounts")

    with pytest.raises(RuntimeError, match="table inventory changed"):
        validate_target(
            [{"tables": sorted(tables)}],
            [{"table": "gold_accounts", "column": "identity_cluster_id"}],
        )

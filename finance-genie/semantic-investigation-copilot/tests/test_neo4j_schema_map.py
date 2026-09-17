"""Tests for the minimal, source-derived Neo4j schema map."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from config import SourceNeo4jConnection
from neo4j_schema_map import (
    DELETE_SCOPE_QUERY,
    ENDPOINTS_QUERY,
    LABELS_QUERY,
    NODE_PROPERTIES_QUERY,
    RELATIONSHIP_PROPERTIES_QUERY,
    RELATIONSHIP_TYPES_QUERY,
    build_schema_map,
    context_from_rows,
    extract_schema_map,
    replace_schema_map,
)
from validate_neo4j_schema import validate_context

CONNECTION = SourceNeo4jConnection(
    uri="neo4j+s://finance.example.com",
    username="reader",
    password="secret",
    database="finance",
)
METADATA = {
    "labels": [{"label": "Account"}, {"label": "Customer"}, {"label": "VIP"}],
    "relationship_types": [{"relationshipType": "TRANSFER"}],
    "node_properties": [
        {
            "nodeType": ":Account",
            "nodeLabels": ["Account"],
            "propertyName": "account_id",
            "propertyTypes": ["INTEGER"],
            "mandatory": True,
        },
        {
            "nodeType": ":Customer:VIP",
            "nodeLabels": ["Customer", "VIP"],
            "propertyName": "name",
            "propertyTypes": ["STRING"],
            "mandatory": False,
        },
    ],
    "relationship_properties": [
        {
            "relType": ":TRANSFER",
            "propertyName": "amount",
            "propertyTypes": ["FLOAT", "INTEGER"],
            "mandatory": True,
        }
    ],
}
ENDPOINTS = [
    {
        "relationship_type": "TRANSFER",
        "source_label": "Account",
        "target_label": "Customer",
    }
]


def test_builds_canonical_map_from_source_metadata() -> None:
    schema_map = build_schema_map(
        CONNECTION,
        METADATA,
        ENDPOINTS,
        endpoints_available=True,
    )

    assert schema_map.database["service"] == "NEO4J"
    assert schema_map.database["endpoints_available"] is True
    assert {
        (node["label"], tuple(node.get("additional_labels", []))) for node in schema_map.nodes
    } == {
        ("Account", ()),
        ("Customer", ()),
        ("Customer", ("VIP",)),
        ("VIP", ()),
    }
    assert schema_map.relationships[0]["type"] == "TRANSFER"
    assert {(row["name"], row["type"], row["nullable"]) for row in schema_map.properties} == {
        ("account_id", "INTEGER", False),
        ("name", "STRING", True),
        ("amount", "FLOAT | INTEGER", False),
    }
    assert {edge["kind"] for edge in schema_map.edges} == {
        "HAS_SCHEMA",
        "HAS_NODE",
        "HAS_RELATIONSHIP",
        "HAS_SOURCE_NODE",
        "HAS_TARGET_NODE",
        "HAS_PROPERTY",
    }


def test_builds_map_without_optional_endpoint_metadata() -> None:
    schema_map = build_schema_map(
        CONNECTION,
        METADATA,
        [],
        endpoints_available=False,
    )

    assert not schema_map.endpoints_available
    assert "HAS_SOURCE_NODE" not in {edge["kind"] for edge in schema_map.edges}


class SourceDriver:
    """Return source schema-procedure fixtures and reject data reads."""

    def execute_query(self, query_: str, **kwargs):
        assert "MATCH" not in query_
        query_results = {
            LABELS_QUERY: METADATA["labels"],
            RELATIONSHIP_TYPES_QUERY: METADATA["relationship_types"],
            NODE_PROPERTIES_QUERY: METADATA["node_properties"],
            RELATIONSHIP_PROPERTIES_QUERY: METADATA["relationship_properties"],
            ENDPOINTS_QUERY: ENDPOINTS,
        }
        return (query_results[query_], None, None)


def test_extracts_only_schema_procedures() -> None:
    schema_map = extract_schema_map(SourceDriver(), CONNECTION)

    assert schema_map.endpoints_available
    assert len(schema_map.properties) == 3


@dataclass
class Result:
    """Minimal transaction result stub."""

    def consume(self) -> None:
        return None


class Transaction:
    """Record transactional schema-map writes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        return Result()


class Session:
    """Provide one write transaction to the fake semantic driver."""

    def __init__(self, transaction: Transaction) -> None:
        self.transaction = transaction

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute_write(self, function, *args) -> None:
        function(self.transaction, *args)


class SemanticDriver:
    """Expose a single fake session for scoped-replacement tests."""

    def __init__(self) -> None:
        self.transaction = Transaction()

    def session(self, **kwargs) -> Session:
        return Session(self.transaction)


def test_replaces_only_the_source_scope_in_one_transaction() -> None:
    schema_map = build_schema_map(CONNECTION, METADATA, ENDPOINTS, endpoints_available=True)
    driver = SemanticDriver()

    replace_schema_map(driver, "semantic", schema_map)

    assert driver.transaction.calls[0] == (
        DELETE_SCOPE_QUERY,
        {"source_scope": schema_map.source_scope},
    )
    assert all("source_scope" not in parameters for _, parameters in driver.transaction.calls[1:])


def test_validation_rejects_stale_context() -> None:
    schema_map = build_schema_map(CONNECTION, METADATA, ENDPOINTS, endpoints_available=True)
    context = {"nodes": [], "relationships": []}

    with pytest.raises(RuntimeError, match="nodes do not match"):
        validate_context(schema_map, context)


def test_context_round_trip_preserves_canonical_rows() -> None:
    schema_map = build_schema_map(CONNECTION, METADATA, ENDPOINTS, endpoints_available=True)
    rows = []
    for kind, node in schema_map.node_rows():
        node_edges = [edge for edge in schema_map.edges if edge["source_id"] == node["id"]]
        if not node_edges:
            rows.append(
                {
                    "kind": kind,
                    "id": node["id"],
                    "metadata": node,
                    "relationship_type": None,
                    "target_id": None,
                }
            )
        for edge in node_edges:
            rows.append(
                {
                    "kind": kind,
                    "id": node["id"],
                    "metadata": node,
                    "relationship_type": edge["kind"],
                    "target_id": edge["target_id"],
                }
            )

    context = context_from_rows(rows, schema_map.source_scope)

    validate_context(schema_map, context)

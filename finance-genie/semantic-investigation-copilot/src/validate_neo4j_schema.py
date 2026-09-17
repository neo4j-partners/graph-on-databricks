"""Validate the persisted Finance Genie Neo4j schema map."""

from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
    source_neo4j_connection,
)
from neo4j_schema_map import (
    SchemaMap,
    extract_schema_map,
    read_schema_context,
    source_scope,
)


def expected_nodes(schema_map: SchemaMap) -> dict[str, dict[str, Any]]:
    """Return all expected canonical node rows keyed by stable identifier."""
    return {row["id"]: {"kind": kind, **row} for kind, row in schema_map.node_rows()}


def validate_context(schema_map: SchemaMap, context: dict[str, Any]) -> None:
    """Require persisted canonical nodes and relationships to match the source map."""
    expected = expected_nodes(schema_map)
    actual = {row["id"]: row for row in context["nodes"]}
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys())
        unexpected = sorted(actual.keys() - expected.keys())
        mismatch = next(
            (
                {
                    "id": node_id,
                    "expected": expected[node_id],
                    "actual": actual[node_id],
                }
                for node_id in expected.keys() & actual.keys()
                if expected[node_id] != actual[node_id]
            ),
            None,
        )
        raise RuntimeError(
            "Neo4j schema map nodes do not match the source metadata: "
            f"missing={missing}, unexpected={unexpected}, mismatch={mismatch}"
        )

    expected_edges = {(row["source_id"], row["kind"], row["target_id"]) for row in schema_map.edges}
    actual_edges = {
        (row["source_id"], row["kind"], row["target_id"]) for row in context["relationships"]
    }
    if actual_edges != expected_edges:
        raise RuntimeError("Neo4j schema map relationships do not match the source metadata.")


def main() -> None:
    """Compare the persisted map to a fresh, metadata-only source extraction."""
    load_demo_env()
    assert_semantic_store_target()
    source = source_neo4j_connection()
    source_driver = GraphDatabase.driver(source.uri, auth=(source.username, source.password))
    semantic_driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        source_driver.verify_connectivity()
        semantic_driver.verify_connectivity()
        semantic_database = require_env("NEO4J_DATABASE")
        assert_no_operational_graph_nodes(semantic_driver, semantic_database)
        schema_map = extract_schema_map(source_driver, source)
        context = read_schema_context(
            semantic_driver,
            semantic_database,
            source_scope(source),
        )
        validate_context(schema_map, context)
    finally:
        source_driver.close()
        semantic_driver.close()

    print("Validated the source-derived Neo4j schema map.")


if __name__ == "__main__":
    main()

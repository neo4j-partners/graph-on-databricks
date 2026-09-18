"""Validate the configured embedding endpoint and vectors stored by NeoCarta."""

from __future__ import annotations

import json
from typing import Any

from neo4j import GraphDatabase, RoutingControl

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
)
from runtime_contract import EXPECTED_VECTOR_INDEXES

EMBEDDING_COVERAGE_QUERY = """CYPHER 25
MATCH (node:Table)
RETURN 'Table' AS label,
       count(node) AS eligible,
       count(node.embedding) AS embedded,
       collect(DISTINCT size(node.embedding)) AS dimensions
UNION ALL
MATCH (node:Column)
RETURN 'Column' AS label,
       count(node) AS eligible,
       count(node.embedding) AS embedded,
       collect(DISTINCT size(node.embedding)) AS dimensions
"""

VECTOR_INDEX_QUERY = """CYPHER 25
SHOW INDEXES
YIELD name, type, state, labelsOrTypes, properties, options
WHERE type = 'VECTOR'
RETURN name, state, labelsOrTypes, properties, options
ORDER BY name
"""


def probe_embedding_dimensions(model: str) -> int:
    """Return the configured endpoint's vector dimension from one probe."""
    if not model.startswith("databricks/"):
        raise RuntimeError("EMBEDDING_MODEL must use the databricks/ provider prefix")

    import litellm

    response = litellm.embedding(model=model, input=["shared identity investigation"])
    vector = response.data[0]["embedding"]
    if not vector:
        raise RuntimeError("Databricks embedding endpoint returned an empty vector")
    return len(vector)


def validate_embedding_state(
    coverage_records: list[dict[str, Any]],
    index_records: list[dict[str, Any]],
    expected_dimensions: int,
) -> dict[str, dict[str, Any]]:
    """Validate vector coverage and index configuration, returning coverage by label."""
    coverage = {record["label"]: record for record in coverage_records}
    expected_labels = set(EXPECTED_VECTOR_INDEXES.values())
    if set(coverage) != expected_labels:
        raise RuntimeError(
            f"Embedding coverage labels changed: expected {sorted(expected_labels)}, "
            f"received {sorted(coverage)}"
        )

    for label, record in coverage.items():
        eligible = int(record["eligible"])
        embedded = int(record["embedded"])
        dimensions = sorted(int(value) for value in record.get("dimensions", []))
        if eligible == 0:
            raise RuntimeError(f"No {label} nodes are eligible for embedding")
        if embedded != eligible:
            raise RuntimeError(
                f"Stored {label} embedding coverage is incomplete: {embedded}/{eligible}"
            )
        if dimensions != [expected_dimensions]:
            raise RuntimeError(
                f"Stored {label} embedding dimensions changed: "
                f"expected {[expected_dimensions]}, received {dimensions}"
            )

    indexes = {record["name"]: record for record in index_records}
    missing_indexes = set(EXPECTED_VECTOR_INDEXES).difference(indexes)
    if missing_indexes:
        raise RuntimeError(f"Missing NeoCarta vector indexes: {sorted(missing_indexes)}")

    for name, label in EXPECTED_VECTOR_INDEXES.items():
        record = indexes[name]
        options = record.get("options") or {}
        index_config = options.get("indexConfig") or {}
        dimensions = index_config.get("vector.dimensions")
        if record.get("state") != "ONLINE":
            raise RuntimeError(f"Vector index {name} is not ONLINE")
        if record.get("labelsOrTypes") != [label] or record.get("properties") != ["embedding"]:
            raise RuntimeError(f"Vector index {name} targets an unexpected label or property")
        if int(dimensions or 0) != expected_dimensions:
            raise RuntimeError(
                f"Vector index {name} has dimension {dimensions}, expected {expected_dimensions}"
            )

    return {
        label: {
            "eligible": int(record["eligible"]),
            "embedded": int(record["embedded"]),
            "dimensions": sorted(int(value) for value in record["dimensions"]),
        }
        for label, record in sorted(coverage.items())
    }


def main() -> None:
    """Validate the endpoint, stored vectors, and NeoCarta vector indexes."""
    load_demo_env()
    assert_semantic_store_target()
    model = require_env("EMBEDDING_MODEL")
    dimensions = probe_embedding_dimensions(model)
    database_name = require_env("NEO4J_DATABASE")
    driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        driver.verify_connectivity()
        assert_no_operational_graph_nodes(driver, database_name)
        coverage_records = driver.execute_query(
            EMBEDDING_COVERAGE_QUERY,
            database_=database_name,
            routing_=RoutingControl.READ,
            result_transformer_=lambda result: result.data(),
        )
        index_records = driver.execute_query(
            VECTOR_INDEX_QUERY,
            database_=database_name,
            routing_=RoutingControl.READ,
            result_transformer_=lambda result: result.data(),
        )
    finally:
        driver.close()

    coverage = validate_embedding_state(coverage_records, index_records, dimensions)

    print(
        json.dumps(
            {
                "status": "passed",
                "provider": "databricks",
                "model": model.removeprefix("databricks/"),
                "dimensions": dimensions,
                "data_stored": True,
                "coverage": coverage,
                "vector_indexes": sorted(EXPECTED_VECTOR_INDEXES),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

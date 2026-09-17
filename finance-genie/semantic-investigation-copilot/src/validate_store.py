"""Validate the Neocarta semantic store after metadata ingestion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from neo4j import GraphDatabase

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
)
from runtime_contract import (
    EXPECTED_CONSTRAINTS,
    EXPECTED_INDEXES,
    EXPECTED_NODE_COUNTS,
    EXPECTED_RELATIONSHIP_COUNTS,
    EXPECTED_TABLES,
    KNOWN_COLUMN,
    KNOWN_TABLE,
)

NODE_COUNTS_QUERY = """CYPHER 25
UNWIND ['__neocarta_graph__', 'Database', 'Schema', 'Table', 'Column', 'Value'] AS label
CALL (label) {
  MATCH (n)
  WHERE label IN labels(n)
  RETURN count(n) AS count
}
RETURN label, count
ORDER BY label
"""

RELATIONSHIP_COUNTS_QUERY = """CYPHER 25
UNWIND ['HAS_SCHEMA', 'HAS_TABLE', 'HAS_COLUMN', 'HAS_VALUE', 'REFERENCES'] AS rel_type
CALL (rel_type) {
  MATCH ()-[r]->()
  WHERE type(r) = rel_type
  RETURN count(r) AS count
}
RETURN rel_type, count
ORDER BY rel_type
"""

INDEX_QUERY = """CYPHER 25
SHOW INDEXES
YIELD name, type, state
WHERE name STARTS WITH 'schema_'
   OR name STARTS WITH 'table_'
   OR name STARTS WITH 'column_'
   OR name STARTS WITH 'database_'
RETURN name, type, state
ORDER BY name
"""

CONSTRAINT_QUERY = """CYPHER 25
SHOW CONSTRAINTS
YIELD name, type, entityType, labelsOrTypes, properties
RETURN name, type, entityType, labelsOrTypes, properties
ORDER BY name
"""

TARGET_QUERY = """CYPHER 25
MATCH (database:Database)-[:HAS_SCHEMA]->(schema:Schema)-[:HAS_TABLE]->(table:Table)
WHERE database.name = $catalog AND schema.name = $schema
RETURN database.name AS catalog, schema.name AS schema, collect(table.name) AS tables
"""

KNOWN_ASSET_QUERY = """CYPHER 25
MATCH (database:Database)-[:HAS_SCHEMA]->(schema:Schema)-[:HAS_TABLE]->
      (table:Table)-[:HAS_COLUMN]->(column:Column)
WHERE database.name = $catalog
  AND schema.name = $schema
  AND table.name = $table
  AND column.name = $column
RETURN database.name AS catalog,
       schema.name AS schema,
       table.name AS table,
       column.name AS column
"""


def rows_by_key(records: Sequence[Mapping[str, Any]], key: str, value: str) -> dict[str, int]:
    """Convert two-column count records to a dictionary."""
    return {record[key]: int(record[value]) for record in records}


def validate_counts(actual: dict[str, int], expected: dict[str, int], kind: str) -> None:
    """Require the fixed demo's exact node or relationship counts."""
    if actual != expected:
        raise RuntimeError(f"Unexpected {kind} counts: expected {expected}, received {actual}")


def validate_indexes(indexes: Sequence[Mapping[str, Any]]) -> None:
    """Require every expected index with its exact type and online state."""
    actual = {index["name"]: (index["type"], index["state"]) for index in indexes}
    mismatched = {
        name: {"expected": definition, "actual": actual.get(name)}
        for name, definition in EXPECTED_INDEXES.items()
        if actual.get(name) != definition
    }
    if mismatched:
        raise RuntimeError(f"Required Neocarta indexes are missing or invalid: {mismatched}")


def validate_constraints(constraints: Sequence[Mapping[str, Any]]) -> None:
    """Require every expected node-key constraint and its id property."""
    actual = {
        constraint["name"]: (
            constraint["type"],
            constraint["entityType"],
            tuple(constraint["labelsOrTypes"]),
            tuple(constraint["properties"]),
        )
        for constraint in constraints
    }
    mismatched = {
        name: {"expected": definition, "actual": actual.get(name)}
        for name, definition in EXPECTED_CONSTRAINTS.items()
        if actual.get(name) != definition
    }
    if mismatched:
        raise RuntimeError(f"Required Neocarta constraints are missing or invalid: {mismatched}")


def validate_target(
    targets: Sequence[Mapping[str, Any]],
    known_assets: Sequence[Mapping[str, Any]],
) -> None:
    """Require the exact table inventory and known retrieval asset."""
    if len(targets) != 1:
        raise RuntimeError(
            f"Expected one configured catalog/schema target, received {len(targets)}"
        )

    actual_tables = set(targets[0]["tables"])
    if actual_tables != EXPECTED_TABLES:
        missing = sorted(EXPECTED_TABLES.difference(actual_tables))
        unexpected = sorted(actual_tables.difference(EXPECTED_TABLES))
        raise RuntimeError(
            f"Configured schema table inventory changed: missing={missing}, unexpected={unexpected}"
        )
    if len(known_assets) != 1:
        raise RuntimeError(
            f"Expected {KNOWN_TABLE}.{KNOWN_COLUMN} in the configured source, "
            f"received {len(known_assets)} matches"
        )


def main() -> None:
    """Validate graph contents and print a machine-readable result."""
    load_demo_env()
    assert_semantic_store_target()

    driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        driver.verify_connectivity()
        database = require_env("NEO4J_DATABASE")
        assert_no_operational_graph_nodes(driver, database)
        node_records, _, _ = driver.execute_query(NODE_COUNTS_QUERY, database_=database)
        relationship_records, _, _ = driver.execute_query(
            RELATIONSHIP_COUNTS_QUERY, database_=database
        )
        index_records, _, _ = driver.execute_query(INDEX_QUERY, database_=database)
        constraint_records, _, _ = driver.execute_query(CONSTRAINT_QUERY, database_=database)
        target_records, _, _ = driver.execute_query(
            TARGET_QUERY,
            catalog=require_env("DATABRICKS_CATALOG"),
            schema=require_env("DATABRICKS_SCHEMA"),
            database_=database,
        )
        known_asset_records, _, _ = driver.execute_query(
            KNOWN_ASSET_QUERY,
            catalog=require_env("DATABRICKS_CATALOG"),
            schema=require_env("DATABRICKS_SCHEMA"),
            table=KNOWN_TABLE,
            column=KNOWN_COLUMN,
            database_=database,
        )
    finally:
        driver.close()

    node_counts = rows_by_key(node_records, "label", "count")
    relationship_counts = rows_by_key(relationship_records, "rel_type", "count")
    indexes = [record.data() for record in index_records]
    constraints = [record.data() for record in constraint_records]
    targets = [record.data() for record in target_records]
    known_assets = [record.data() for record in known_asset_records]

    validate_counts(node_counts, EXPECTED_NODE_COUNTS, "node")
    validate_counts(relationship_counts, EXPECTED_RELATIONSHIP_COUNTS, "relationship")
    validate_indexes(indexes)
    validate_constraints(constraints)
    validate_target(targets, known_assets)

    result = {
        "status": "passed",
        "node_counts": node_counts,
        "relationship_counts": relationship_counts,
        "indexes": indexes,
        "constraints": constraints,
        "target": targets[0],
        "known_asset": known_assets[0],
        "value_sampling": "disabled",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

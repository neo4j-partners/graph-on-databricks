"""Validate the Neocarta semantic store after metadata ingestion."""

from __future__ import annotations

import json

from neo4j import GraphDatabase

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
)

NODE_COUNTS_QUERY = """
UNWIND ['__neocarta_graph__', 'Database', 'Schema', 'Table', 'Column', 'Value'] AS label
CALL (label) {
  MATCH (n)
  WHERE label IN labels(n)
  RETURN count(n) AS count
}
RETURN label, count
ORDER BY label
"""

RELATIONSHIP_COUNTS_QUERY = """
UNWIND ['HAS_SCHEMA', 'HAS_TABLE', 'HAS_COLUMN', 'HAS_VALUE', 'REFERENCES'] AS rel_type
CALL (rel_type) {
  MATCH ()-[r]->()
  WHERE type(r) = rel_type
  RETURN count(r) AS count
}
RETURN rel_type, count
ORDER BY rel_type
"""

INDEX_QUERY = """
SHOW INDEXES
YIELD name, type, state
WHERE name STARTS WITH 'schema_'
   OR name STARTS WITH 'table_'
   OR name STARTS WITH 'column_'
   OR name STARTS WITH 'database_'
RETURN name, type, state
ORDER BY name
"""

CONSTRAINT_QUERY = """
SHOW CONSTRAINTS
YIELD name, type, entityType, labelsOrTypes, properties
RETURN name, type, entityType, labelsOrTypes, properties
ORDER BY name
"""

TARGET_QUERY = """
MATCH (database:Database)-[:HAS_SCHEMA]->(schema:Schema)-[:HAS_TABLE]->(table:Table)
WHERE database.name = $catalog AND schema.name = $schema
RETURN database.name AS catalog, schema.name AS schema, collect(table.name) AS tables
"""


def rows_by_key(records: list, key: str, value: str) -> dict[str, int]:
    """Convert two-column count records to a dictionary."""
    return {record[key]: int(record[value]) for record in records}


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
    finally:
        driver.close()

    node_counts = rows_by_key(node_records, "label", "count")
    relationship_counts = rows_by_key(relationship_records, "rel_type", "count")
    indexes = [record.data() for record in index_records]
    constraints = [record.data() for record in constraint_records]
    targets = [record.data() for record in target_records]

    required_positive = ["__neocarta_graph__", "Database", "Schema", "Table", "Column"]
    missing = [label for label in required_positive if node_counts.get(label, 0) < 1]
    if missing:
        raise RuntimeError(f"Required metadata labels are empty: {', '.join(missing)}")
    if node_counts.get("Value", 0) != 0 or relationship_counts.get("HAS_VALUE", 0) != 0:
        raise RuntimeError("Value sampling boundary failed: Value metadata was stored")
    if not targets:
        raise RuntimeError("Configured Databricks catalog and schema were not found")
    if any(index["state"] != "ONLINE" for index in indexes):
        raise RuntimeError("One or more Neocarta indexes are not online")
    constrained_labels = {
        label for constraint in constraints for label in constraint["labelsOrTypes"]
    }
    missing_constraints = {"Database", "Schema", "Table", "Column"}.difference(constrained_labels)
    if missing_constraints:
        raise RuntimeError(
            f"Required uniqueness constraints are missing: {sorted(missing_constraints)}"
        )

    result = {
        "status": "passed",
        "node_counts": node_counts,
        "relationship_counts": relationship_counts,
        "indexes": indexes,
        "constraints": constraints,
        "target": targets[0],
        "value_sampling": "disabled",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

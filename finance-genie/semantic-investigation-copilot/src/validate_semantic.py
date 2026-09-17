"""Validate and optionally record the semantic graph contract."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from neo4j import GraphDatabase

from config import (
    DEMO_DIR,
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
)

EVIDENCE_FILE = DEMO_DIR / "validation" / "semantic-graph-validation.json"

EXPECTED_NODES = {
    "Glossary": 1,
    "Category": 1,
    "BusinessTerm": 5,
    "BusinessConcept": 5,
    "GraphDatabase": 1,
    "GraphNodeLabel": 8,
    "GraphRelationshipType": 9,
    "GraphProperty": 35,
    "Value": 0,
}

EXPECTED_RELATIONSHIPS = {
    "HAS_CATEGORY": 1,
    "HAS_BUSINESS_TERM": 5,
    "TAGGED_WITH": 29,
    "MAPS_TO_TABLE": 6,
    "MAPS_TO_COLUMN": 23,
    "HAS_NODE_LABEL": 8,
    "HAS_RELATIONSHIP_TYPE": 9,
    "HAS_PROPERTY": 35,
    "HAS_SOURCE_LABEL": 9,
    "HAS_TARGET_LABEL": 9,
    "MAPS_TO_GRAPH_ASSET": 81,
    "HAS_VALUE": 0,
}

NODE_COUNTS_QUERY = """CYPHER 25
UNWIND $labels AS label
CALL (label) {
  MATCH (node)
  WHERE label IN labels(node)
  RETURN count(node) AS count
}
RETURN label, count
ORDER BY label
"""

RELATIONSHIP_COUNTS_QUERY = """CYPHER 25
UNWIND $types AS relationship_type
CALL (relationship_type) {
  MATCH ()-[relationship]->()
  WHERE type(relationship) = relationship_type
  RETURN count(relationship) AS count
}
RETURN relationship_type, count
ORDER BY relationship_type
"""

EMBEDDING_QUERY = """CYPHER 25
MATCH (concept:BusinessConcept)
RETURN count(concept) AS concepts,
       count(concept.embedding) AS embedded_concepts,
       collect(DISTINCT size(concept.embedding)) AS dimensions
"""

INDEX_QUERY = """CYPHER 25
SHOW INDEXES
YIELD name, type, state, labelsOrTypes, properties, options
WHERE name IN ['businessterm_full_text_index', 'businessterm_vector_index']
RETURN name, type, state, labelsOrTypes, properties, options
ORDER BY name
"""


def _counts(records: list[Any], key: str) -> dict[str, int]:
    return {str(record[key]): int(record["count"]) for record in records}


def require_exact_counts(actual: dict[str, int], expected: dict[str, int], kind: str) -> None:
    """Require the fixed demo's exact semantic-graph cardinalities."""
    if actual != expected:
        raise RuntimeError(f"Unexpected semantic-graph {kind} counts: {actual}")


def validate_indexes(indexes: list[dict[str, Any]]) -> dict[str, Any]:
    """Require online full-text and 1,024-dimensional vector indexes."""
    by_name = {index["name"]: index for index in indexes}
    full_text = by_name.get("businessterm_full_text_index")
    vector = by_name.get("businessterm_vector_index")
    if not full_text or (full_text["type"], full_text["state"]) != ("FULLTEXT", "ONLINE"):
        raise RuntimeError("BusinessTerm full-text index is missing or offline")
    if not vector or (vector["type"], vector["state"]) != ("VECTOR", "ONLINE"):
        raise RuntimeError("BusinessTerm vector index is missing or offline")
    dimensions = vector.get("options", {}).get("indexConfig", {}).get("vector.dimensions")
    if dimensions != 1024:
        raise RuntimeError(f"BusinessTerm vector dimensions changed: {dimensions}")
    return {"full_text": full_text, "vector": vector}


def validate(*, write_evidence: bool = False) -> dict[str, Any]:
    """Validate the live semantic graph and return reviewable evidence."""
    load_demo_env()
    assert_semantic_store_target()
    database = require_env("NEO4J_DATABASE")
    driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        driver.verify_connectivity()
        assert_no_operational_graph_nodes(driver, database)
        node_records, _, _ = driver.execute_query(
            NODE_COUNTS_QUERY,
            parameters_={"labels": list(EXPECTED_NODES)},
            database_=database,
        )
        relationship_records, _, _ = driver.execute_query(
            RELATIONSHIP_COUNTS_QUERY,
            parameters_={"types": list(EXPECTED_RELATIONSHIPS)},
            database_=database,
        )
        embedding_records, _, _ = driver.execute_query(EMBEDDING_QUERY, database_=database)
        index_records, _, _ = driver.execute_query(INDEX_QUERY, database_=database)
    finally:
        driver.close()

    node_counts = _counts(node_records, "label")
    relationship_counts = _counts(relationship_records, "relationship_type")
    require_exact_counts(node_counts, EXPECTED_NODES, "node")
    require_exact_counts(relationship_counts, EXPECTED_RELATIONSHIPS, "relationship")

    embedding = embedding_records[0].data()
    embedding["dimensions"] = sorted(value for value in embedding["dimensions"] if value)
    if embedding != {"concepts": 5, "embedded_concepts": 5, "dimensions": [1024]}:
        raise RuntimeError(f"BusinessConcept embeddings are incomplete: {embedding}")
    indexes = validate_indexes([record.data() for record in index_records])

    result = {
        "validation": "semantic_graph",
        "status": "complete",
        "evidence_date": datetime.now(UTC).date().isoformat(),
        "recorded_at": datetime.now(UTC).isoformat(),
        "semantic_store_database": database,
        "node_counts": node_counts,
        "relationship_counts": relationship_counts,
        "embedding": embedding,
        "indexes": indexes,
        "metadata_only": True,
        "value_nodes": 0,
        "has_value_relationships": 0,
        "operational_nodes": 0,
        "validation_command": "uv run finance-semantic-validate-graph",
    }
    if write_evidence:
        EVIDENCE_FILE.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    """Validate the semantic graph and print a machine-readable result."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    print(json.dumps(validate(write_evidence=args.write_evidence), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

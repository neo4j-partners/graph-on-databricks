"""Build a minimal, source-derived LPG schema map for Finance Genie."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from neo4j import AsyncDriver, GraphDatabase, RoutingControl
from neo4j.exceptions import Neo4jError

from config import (
    SourceNeo4jConnection,
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
    source_neo4j_connection,
)

logger = logging.getLogger(__name__)

LABELS_QUERY = "CALL db.labels() YIELD label RETURN label ORDER BY label"
RELATIONSHIP_TYPES_QUERY = (
    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
)
NODE_PROPERTIES_QUERY = """
CALL db.schema.nodeTypeProperties()
YIELD nodeType, nodeLabels, propertyName, propertyTypes, mandatory
RETURN nodeType, nodeLabels, propertyName, propertyTypes, mandatory
ORDER BY nodeType, propertyName
"""
RELATIONSHIP_PROPERTIES_QUERY = """
CALL db.schema.relTypeProperties()
YIELD relType, propertyName, propertyTypes, mandatory
RETURN relType, propertyName, propertyTypes, mandatory
ORDER BY relType, propertyName
"""
ENDPOINTS_QUERY = """
CALL db.schema.visualization()
YIELD relationships
UNWIND relationships AS relationship
WITH relationship, startNode(relationship) AS source, endNode(relationship) AS target
RETURN relationship.name AS relationship_type,
       source.name AS source_label,
       target.name AS target_label
ORDER BY relationship_type, source_label, target_label
"""

DELETE_SCOPE_QUERY = """
MATCH (entity {source_scope: $source_scope})
DETACH DELETE entity
"""
UPSERT_DATABASE_QUERY = """
UNWIND $rows AS row
MERGE (entity:Database {id: row.id})
SET entity += row
"""
UPSERT_SCHEMA_QUERY = """
UNWIND $rows AS row
MERGE (entity:Schema {id: row.id})
SET entity += row
"""
UPSERT_NODE_QUERY = """
UNWIND $rows AS row
MERGE (entity:Node {id: row.id})
SET entity += row
"""
UPSERT_RELATIONSHIP_QUERY = """
UNWIND $rows AS row
MERGE (entity:Relationship {id: row.id})
SET entity += row
"""
UPSERT_PROPERTY_QUERY = """
UNWIND $rows AS row
MERGE (entity:Property {id: row.id})
SET entity += row
"""
UPSERT_EDGE_QUERY = """
UNWIND $rows AS row
MATCH (source {id: row.source_id})
MATCH (target {id: row.target_id})
CALL (source, target, row) {
  WITH source, target, row
  WITH source, target WHERE row.kind = "HAS_SCHEMA"
  MERGE (source)-[:HAS_SCHEMA]->(target)
  RETURN 1 AS ignored
  UNION
  WITH source, target, row
  WITH source, target WHERE row.kind = "HAS_NODE"
  MERGE (source)-[:HAS_NODE]->(target)
  RETURN 1 AS ignored
  UNION
  WITH source, target, row
  WITH source, target WHERE row.kind = "HAS_RELATIONSHIP"
  MERGE (source)-[:HAS_RELATIONSHIP]->(target)
  RETURN 1 AS ignored
  UNION
  WITH source, target, row
  WITH source, target WHERE row.kind = "HAS_SOURCE_NODE"
  MERGE (source)-[:HAS_SOURCE_NODE]->(target)
  RETURN 1 AS ignored
  UNION
  WITH source, target, row
  WITH source, target WHERE row.kind = "HAS_TARGET_NODE"
  MERGE (source)-[:HAS_TARGET_NODE]->(target)
  RETURN 1 AS ignored
  UNION
  WITH source, target, row
  WITH source, target WHERE row.kind = "HAS_PROPERTY"
  MERGE (source)-[:HAS_PROPERTY]->(target)
  RETURN 1 AS ignored
}
RETURN count(*) AS relationships_processed
"""
CONTEXT_QUERY = """
MATCH (entity {source_scope: $source_scope})
OPTIONAL MATCH (entity)-[relationship]->(target {source_scope: $source_scope})
RETURN labels(entity)[0] AS kind,
       entity.id AS id,
       properties(entity) AS metadata,
       type(relationship) AS relationship_type,
       target.id AS target_id
ORDER BY kind, id, relationship_type, target_id
"""


@dataclass(frozen=True)
class SchemaMap:
    """Canonical LPG rows and relationships for one operational source."""

    source_scope: str
    database: dict[str, Any]
    schema: dict[str, Any]
    nodes: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]
    properties: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, str], ...]
    endpoints_available: bool

    def node_rows(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Return rows grouped with their canonical Neo4j label."""
        return (
            ("Database", self.database),
            ("Schema", self.schema),
            *(("Node", row) for row in self.nodes),
            *(("Relationship", row) for row in self.relationships),
            *(("Property", row) for row in self.properties),
        )


def source_scope(connection: SourceNeo4jConnection) -> str:
    """Build a stable identity without storing source credentials."""
    digest = hashlib.sha256(f"{connection.uri}|{connection.database}".encode()).hexdigest()[:16]
    return f"neo4j:{digest}"


def scoped_id(scope: str, kind: str, *parts: str) -> str:
    """Return a stable, source-scoped identifier for one canonical entity."""
    value = "\x1f".join(parts)
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"{scope}:{kind}:{digest}"


def normalize_labels(value: object) -> tuple[str, ...]:
    """Normalize a source label collection into a stable canonical identity."""
    if not isinstance(value, Iterable) or isinstance(value, (bytes, str)):
        return ()
    return tuple(sorted({str(label) for label in value if str(label)}))


def canonical_labels(labels: tuple[str, ...]) -> tuple[str, ...]:
    """Represent unlabeled nodes in the current LPG model's required label field."""
    return labels or ("<unlabeled>",)


def property_type(value: object) -> str | None:
    """Render a source-reported property type union without inferring a type."""
    if not isinstance(value, Iterable) or isinstance(value, (bytes, str)):
        return str(value) if value else None
    values = sorted({str(item) for item in value if str(item)})
    return " | ".join(values) or None


def row_data(records: Sequence[Any]) -> list[dict[str, Any]]:
    """Convert driver records or mapping stubs to ordinary dictionaries."""
    rows: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, Mapping):
            rows.append(dict(record))
        else:
            rows.append(record.data())
    return rows


def read_required_schema_metadata(
    source_driver: Any, database: str
) -> dict[str, list[dict[str, Any]]]:
    """Read required schema metadata or raise an actionable source-access error."""
    queries = {
        "labels": LABELS_QUERY,
        "relationship_types": RELATIONSHIP_TYPES_QUERY,
        "node_properties": NODE_PROPERTIES_QUERY,
        "relationship_properties": RELATIONSHIP_PROPERTIES_QUERY,
    }
    metadata: dict[str, list[dict[str, Any]]] = {}
    try:
        for name, query in queries.items():
            records, _, _ = source_driver.execute_query(
                query_=query,
                database_=database,
                routing_=RoutingControl.READ,
            )
            metadata[name] = row_data(records)
    except Neo4jError as error:
        raise RuntimeError(
            "Unable to read required Neo4j schema metadata. Grant the source identity "
            "access to db.labels, db.relationshipTypes, db.schema.nodeTypeProperties, "
            "and db.schema.relTypeProperties."
        ) from error
    return metadata


def read_endpoints(source_driver: Any, database: str) -> tuple[list[dict[str, Any]], bool]:
    """Read statistics-based endpoint metadata when the source permits it."""
    try:
        records, _, _ = source_driver.execute_query(
            query_=ENDPOINTS_QUERY,
            database_=database,
            routing_=RoutingControl.READ,
        )
    except Neo4jError as error:
        logger.warning("Neo4j schema endpoints were unavailable: %s", error.code)
        return [], False
    return row_data(records), True


def build_schema_map(
    connection: SourceNeo4jConnection,
    metadata: Mapping[str, Sequence[Mapping[str, Any]]],
    endpoints: Sequence[Mapping[str, Any]],
    *,
    endpoints_available: bool,
) -> SchemaMap:
    """Transform source-reported metadata into the existing canonical LPG model."""
    scope = source_scope(connection)
    database_id = scoped_id(scope, "database", connection.database)
    schema_id = scoped_id(scope, "schema", "default")
    label_sets: set[tuple[str, ...]] = set()

    for row in metadata["labels"]:
        label = str(row["label"])
        if label:
            label_sets.add((label,))
    for row in metadata["node_properties"]:
        label_sets.add(canonical_labels(normalize_labels(row["nodeLabels"])))
    for row in endpoints:
        label_sets.add((str(row["source_label"]),))
        label_sets.add((str(row["target_label"]),))

    node_ids = {labels: scoped_id(scope, "node", *labels) for labels in sorted(label_sets)}
    nodes: list[dict[str, Any]] = []
    for labels, node_id in node_ids.items():
        row: dict[str, Any] = {
            "id": node_id,
            "label": labels[0],
            "source_scope": scope,
        }
        if len(labels) > 1:
            row["additional_labels"] = list(labels[1:])
        nodes.append(row)

    relationship_types = {
        str(row["relationshipType"])
        for row in metadata["relationship_types"]
        if str(row["relationshipType"])
    }
    relationship_types.update(
        str(row["relType"]).removeprefix(":")
        for row in metadata["relationship_properties"]
        if str(row["relType"])
    )
    relationship_types.update(
        str(row["relationship_type"]) for row in endpoints if str(row["relationship_type"])
    )
    relationship_ids = {
        relationship_type: scoped_id(scope, "relationship", relationship_type)
        for relationship_type in sorted(relationship_types)
    }
    relationships = [
        {"id": relationship_id, "type": relationship_type, "source_scope": scope}
        for relationship_type, relationship_id in relationship_ids.items()
    ]

    properties: list[dict[str, Any]] = []
    edges: set[tuple[str, str, str]] = {(database_id, "HAS_SCHEMA", schema_id)}
    edges.update((schema_id, "HAS_NODE", node_id) for node_id in node_ids.values())
    edges.update(
        (schema_id, "HAS_RELATIONSHIP", relationship_id)
        for relationship_id in relationship_ids.values()
    )
    for row in metadata["node_properties"]:
        labels = canonical_labels(normalize_labels(row["nodeLabels"]))
        owner_id = node_ids[labels]
        property_name = str(row["propertyName"])
        property_id = scoped_id(scope, "node-property", owner_id, property_name)
        row_type = property_type(row["propertyTypes"])
        property_row: dict[str, Any] = {
            "id": property_id,
            "name": property_name,
            "nullable": not bool(row["mandatory"]),
            "unique": False,
            "indexed": False,
            "existence": False,
            "source_scope": scope,
        }
        if row_type is not None:
            property_row["type"] = row_type
        properties.append(property_row)
        edges.add((owner_id, "HAS_PROPERTY", property_id))
    for row in metadata["relationship_properties"]:
        relationship_type = str(row["relType"]).removeprefix(":")
        owner_id = relationship_ids[relationship_type]
        property_name = str(row["propertyName"])
        property_id = scoped_id(scope, "relationship-property", owner_id, property_name)
        row_type = property_type(row["propertyTypes"])
        property_row = {
            "id": property_id,
            "name": property_name,
            "nullable": not bool(row["mandatory"]),
            "unique": False,
            "indexed": False,
            "existence": False,
            "source_scope": scope,
        }
        if row_type is not None:
            property_row["type"] = row_type
        properties.append(property_row)
        edges.add((owner_id, "HAS_PROPERTY", property_id))
    for row in endpoints:
        relationship_id = relationship_ids[str(row["relationship_type"])]
        source_id = node_ids[(str(row["source_label"]),)]
        target_id = node_ids[(str(row["target_label"]),)]
        edges.add((relationship_id, "HAS_SOURCE_NODE", source_id))
        edges.add((relationship_id, "HAS_TARGET_NODE", target_id))

    return SchemaMap(
        source_scope=scope,
        database={
            "id": database_id,
            "name": connection.database,
            "service": "NEO4J",
            "source_scope": scope,
            "endpoints_available": endpoints_available,
        },
        schema={"id": schema_id, "name": "default", "source_scope": scope},
        nodes=tuple(nodes),
        relationships=tuple(relationships),
        properties=tuple(properties),
        edges=tuple(
            {
                "source_id": source_id,
                "kind": kind,
                "target_id": target_id,
            }
            for source_id, kind, target_id in sorted(edges)
        ),
        endpoints_available=endpoints_available,
    )


def extract_schema_map(source_driver: Any, connection: SourceNeo4jConnection) -> SchemaMap:
    """Extract and transform one source database without reading operational values."""
    metadata = read_required_schema_metadata(source_driver, connection.database)
    endpoints, endpoints_available = read_endpoints(source_driver, connection.database)
    return build_schema_map(
        connection,
        metadata,
        endpoints,
        endpoints_available=endpoints_available,
    )


def replace_schema_map(semantic_driver: Any, database: str, schema_map: SchemaMap) -> None:
    """Atomically replace just one source-scoped map in the semantic store."""
    with semantic_driver.session(database=database) as session:
        session.execute_write(_replace_schema_map, schema_map)


def _replace_schema_map(transaction: Any, schema_map: SchemaMap) -> None:
    """Write every map row in a single semantic-store transaction."""
    transaction.run(DELETE_SCOPE_QUERY, source_scope=schema_map.source_scope).consume()
    node_queries = {
        "Database": (UPSERT_DATABASE_QUERY, [schema_map.database]),
        "Schema": (UPSERT_SCHEMA_QUERY, [schema_map.schema]),
        "Node": (UPSERT_NODE_QUERY, list(schema_map.nodes)),
        "Relationship": (UPSERT_RELATIONSHIP_QUERY, list(schema_map.relationships)),
        "Property": (UPSERT_PROPERTY_QUERY, list(schema_map.properties)),
    }
    for query, rows in node_queries.values():
        if rows:
            transaction.run(query, rows=rows).consume()
    if schema_map.edges:
        transaction.run(UPSERT_EDGE_QUERY, rows=list(schema_map.edges)).consume()


def read_schema_context(semantic_driver: Any, database: str, scope: str) -> dict[str, Any]:
    """Return the persisted canonical map in a small JSON-friendly structure."""
    records, _, _ = semantic_driver.execute_query(
        query_=CONTEXT_QUERY,
        source_scope=scope,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return context_from_rows(row_data(records), scope)


def context_from_rows(rows: Sequence[Mapping[str, Any]], scope: str) -> dict[str, Any]:
    """Convert persisted map rows into the retrieval tool's JSON result."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    for row in rows:
        nodes[row["id"]] = {"kind": row["kind"], **row["metadata"]}
        if row["relationship_type"] is not None:
            edges.add((row["id"], row["relationship_type"], row["target_id"]))
    return {
        "source_scope": scope,
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "relationships": [
            {"source_id": source_id, "kind": kind, "target_id": target_id}
            for source_id, kind, target_id in sorted(edges)
        ],
    }


def register_schema_context_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    scope: str,
) -> None:
    """Register focused MCP retrieval for the persisted source-derived map."""

    @server.tool()
    async def get_neo4j_schema_context() -> dict[str, Any]:
        """
        Return the configured Finance Genie operational graph's structural schema map.

        The result contains source-derived label sets, relationship types,
        reported property names and types, and available endpoints. It contains
        no operational graph values or inferred business definitions.
        """
        rows = await neo4j_driver.execute_query(
            query_=CONTEXT_QUERY,
            parameters_={"source_scope": scope},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda result: result.data(),
        )
        return context_from_rows(rows, scope)


def main() -> None:
    """Ingest the configured Finance Genie source schema into the semantic store."""
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
        replace_schema_map(semantic_driver, semantic_database, schema_map)
    finally:
        source_driver.close()
        semantic_driver.close()

    print(
        "Ingested Neo4j schema metadata "
        f"nodes={len(schema_map.nodes)} relationships={len(schema_map.relationships)} "
        f"properties={len(schema_map.properties)} endpoints_available={schema_map.endpoints_available}."
    )


def context_main() -> None:
    """Print the persisted source-derived schema context for the configured source."""
    load_demo_env()
    assert_semantic_store_target()
    source = source_neo4j_connection()
    semantic_driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        semantic_database = require_env("NEO4J_DATABASE")
        assert_no_operational_graph_nodes(semantic_driver, semantic_database)
        context = read_schema_context(
            semantic_driver,
            semantic_database,
            source_scope(source),
        )
    finally:
        semantic_driver.close()
    print(json.dumps(context, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

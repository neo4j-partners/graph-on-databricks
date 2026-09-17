"""Load the curated Finance semantic mappings into the isolated metadata graph.

The standard glossary and lakehouse tagging model is loaded through Neocarta's
CSV connector.  This module adds the demo-specific graph-schema adapter and
explicit outbound mapping relationships without reading operational values.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parents[1]
MAPPINGS_DIR = DEMO_DIR / "mappings"
DEFAULT_MAPPING_FILE = MAPPINGS_DIR / "semantic-mappings.json"

GLOSSARY_ID = "finance_investigation"
GLOSSARY_NAME = "finance_investigation"
CATEGORY_ID = "finance_investigation.investigation_signals"
CATEGORY_NAME = "investigation_signals"

_ROOT_KEYS = {"version", "primary_concept", "source_scope", "concepts"}
_SCOPE_KEYS = {"databricks_catalog", "databricks_schema", "neo4j_database"}
_CONCEPT_KEYS = {"id", "name", "definition", "interpretation", "databricks", "neo4j"}
_DATABRICKS_KEYS = {"table", "tables", "columns", "predicate", "join_keys"}
_NEO4J_KEYS = {
    "node_labels",
    "relationship_types",
    "properties",
    "paths",
    "known_gap",
}
_NODE_PATTERN = re.compile(r"\(:([A-Za-z_][A-Za-z0-9_]*)(?:\s+\{[^}]*\})?\)")
_REL_PATTERN = re.compile(r"\[:([A-Za-z_][A-Za-z0-9_]*)\]")


class MappingValidationError(ValueError):
    """Raised when the versioned semantic mapping contract is invalid."""


@dataclass(frozen=True)
class SemanticRecords:
    """Parameterized rows derived from the validated mapping contract."""

    concepts: list[dict[str, Any]]
    table_mappings: list[dict[str, str]]
    column_mappings: list[dict[str, str]]
    graph_databases: list[dict[str, str]]
    graph_node_labels: list[dict[str, str]]
    graph_relationship_types: list[dict[str, str]]
    graph_properties: list[dict[str, str]]
    relationship_endpoints: list[dict[str, str]]
    concept_graph_databases: list[dict[str, str]]
    concept_graph_node_labels: list[dict[str, str]]
    concept_graph_relationship_types: list[dict[str, str]]
    concept_graph_properties: list[dict[str, str]]


@dataclass(frozen=True)
class SemanticLoadCounts:
    """Expected cardinalities for one idempotent semantic load."""

    concepts: int
    table_mappings: int
    column_mappings: int
    graph_databases: int
    graph_node_labels: int
    graph_relationship_types: int
    graph_properties: int
    relationship_endpoints: int
    concept_graph_asset_mappings: int


def _require_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise MappingValidationError(f"Unsupported {context} fields: {sorted(unknown)}")


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MappingValidationError(f"{context} must be a non-empty string")
    return value.strip()


def _require_string_list(value: Any, context: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise MappingValidationError(f"{context} must be a non-empty list")
    result = [_require_string(item, f"{context} item") for item in value]
    if len(set(result)) != len(result):
        raise MappingValidationError(f"{context} contains duplicate values")
    return result


def validate_mapping(mapping: Any) -> dict[str, Any]:
    """Validate and return a metadata-only semantic mapping document.

    The closed field allowlists are deliberate: they prevent source rows,
    samples, fixture identifiers, or other operational payloads from crossing
    the semantic-store boundary.
    """
    if not isinstance(mapping, dict):
        raise MappingValidationError("Semantic mapping root must be an object")
    _require_keys(mapping, _ROOT_KEYS, "root")
    if mapping.get("version") != 1:
        raise MappingValidationError("Semantic mapping version must be 1")

    scope = mapping.get("source_scope")
    if not isinstance(scope, dict):
        raise MappingValidationError("source_scope must be an object")
    _require_keys(scope, _SCOPE_KEYS, "source_scope")
    for name in sorted(_SCOPE_KEYS):
        _require_string(scope.get(name), f"source_scope.{name}")

    concepts = mapping.get("concepts")
    if not isinstance(concepts, list) or not concepts:
        raise MappingValidationError("concepts must be a non-empty list")

    concept_ids: set[str] = set()
    for index, concept in enumerate(concepts):
        context = f"concepts[{index}]"
        if not isinstance(concept, dict):
            raise MappingValidationError(f"{context} must be an object")
        _require_keys(concept, _CONCEPT_KEYS, context)
        concept_id = _require_string(concept.get("id"), f"{context}.id")
        if concept_id in concept_ids:
            raise MappingValidationError(f"Duplicate concept id: {concept_id}")
        concept_ids.add(concept_id)
        for name in ("name", "definition", "interpretation"):
            _require_string(concept.get(name), f"{context}.{name}")

        databricks = concept.get("databricks")
        if not isinstance(databricks, dict):
            raise MappingValidationError(f"{context}.databricks must be an object")
        _require_keys(databricks, _DATABRICKS_KEYS, f"{context}.databricks")
        if "table" in databricks and "tables" in databricks:
            raise MappingValidationError(f"{context}.databricks cannot define table and tables")
        tables = _databricks_tables(databricks, context)
        columns = _require_string_list(databricks.get("columns"), f"{context}.columns")
        for column in columns:
            if "." in column and column.split(".", 1)[0] not in tables:
                raise MappingValidationError(f"{context} column {column!r} is outside its tables")
            if "." not in column and len(tables) != 1:
                raise MappingValidationError(
                    f"{context} columns must be table-qualified when multiple tables are mapped"
                )
        for optional_list in ("join_keys",):
            if optional_list in databricks:
                _require_string_list(
                    databricks[optional_list], f"{context}.databricks.{optional_list}"
                )
        if "predicate" in databricks:
            _require_string(databricks["predicate"], f"{context}.databricks.predicate")

        neo4j = concept.get("neo4j")
        if not isinstance(neo4j, dict):
            raise MappingValidationError(f"{context}.neo4j must be an object")
        _require_keys(neo4j, _NEO4J_KEYS, f"{context}.neo4j")
        labels = _require_string_list(neo4j.get("node_labels"), f"{context}.neo4j.node_labels")
        relationships = _require_string_list(
            neo4j.get("relationship_types"), f"{context}.neo4j.relationship_types"
        )
        paths = _require_string_list(neo4j.get("paths"), f"{context}.neo4j.paths")
        properties = neo4j.get("properties")
        if not isinstance(properties, dict):
            raise MappingValidationError(f"{context}.neo4j.properties must be an object")
        for owner, names in properties.items():
            if owner not in labels and owner not in relationships:
                raise MappingValidationError(f"{context} property owner {owner!r} is not an asset")
            _require_string_list(names, f"{context}.neo4j.properties.{owner}")
        if "known_gap" in neo4j:
            _require_string(neo4j["known_gap"], f"{context}.neo4j.known_gap")
        _validate_paths(paths, labels, relationships, context)

    primary = _require_string(mapping.get("primary_concept"), "primary_concept")
    if primary not in concept_ids:
        raise MappingValidationError("primary_concept does not identify a declared concept")
    return mapping


def load_mapping(path: Path | str = DEFAULT_MAPPING_FILE) -> dict[str, Any]:
    """Read and validate the versioned JSON mapping contract."""
    mapping_path = Path(path)
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MappingValidationError(f"Cannot read semantic mapping {mapping_path}: {exc}") from exc
    return validate_mapping(payload)


def _databricks_tables(databricks: Mapping[str, Any], context: str = "databricks") -> list[str]:
    if "table" in databricks:
        return [_require_string(databricks["table"], f"{context}.table")]
    return _require_string_list(databricks.get("tables"), f"{context}.tables")


def _validate_paths(
    paths: Sequence[str], labels: Sequence[str], relationships: Sequence[str], context: str
) -> None:
    declared_labels = set(labels)
    declared_relationships = set(relationships)
    for path in paths:
        path_labels = {match.group(1) for match in _NODE_PATTERN.finditer(path)}
        path_relationships = {match.group(1) for match in _REL_PATTERN.finditer(path)}
        if len(path_labels) == 0 or len(path_relationships) == 0:
            raise MappingValidationError(f"{context} contains unsupported graph path: {path!r}")
        if not path_labels.issubset(declared_labels):
            raise MappingValidationError(f"{context} path references an undeclared node label")
        if not path_relationships.issubset(declared_relationships):
            raise MappingValidationError(
                f"{context} path references an undeclared relationship type"
            )


def _normalize_identifier(value: str) -> str:
    return value.lower().replace(" ", "_").replace("-", "_")


def _table_id(catalog: str, schema: str, table: str) -> str:
    return ".".join(map(_normalize_identifier, (catalog, schema, table)))


def _column_id(catalog: str, schema: str, table: str, column: str) -> str:
    return f"{_table_id(catalog, schema, table)}.{_normalize_identifier(column)}"


def _graph_database_id(database: str) -> str:
    return f"graph-database:{_normalize_identifier(database)}"


def _graph_asset_id(database: str, kind: str, name: str) -> str:
    return f"{_graph_database_id(database)}:{kind}:{name}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _split_column(column: str, tables: Sequence[str]) -> tuple[str, str]:
    if "." in column:
        return tuple(column.split(".", 1))  # type: ignore[return-value]
    return tables[0], column


def _path_endpoints(path: str) -> list[tuple[str, str, str]]:
    nodes = list(_NODE_PATTERN.finditer(path))
    endpoints: list[tuple[str, str, str]] = []
    for left, right in pairwise(nodes):
        between = path[left.end() : right.start()]
        relationship = _REL_PATTERN.search(between)
        if relationship is None:
            continue
        left_label, right_label = left.group(1), right.group(1)
        if between.lstrip().startswith("<-"):
            endpoints.append((relationship.group(1), right_label, left_label))
        else:
            endpoints.append((relationship.group(1), left_label, right_label))
    return endpoints


def build_records(mapping: Mapping[str, Any]) -> SemanticRecords:
    """Build deterministic query parameters from a validated mapping."""
    validate_mapping(mapping)
    version = mapping["version"]
    primary = mapping["primary_concept"]
    scope = mapping["source_scope"]
    catalog = scope["databricks_catalog"]
    schema = scope["databricks_schema"]
    graph_database = scope["neo4j_database"]
    database_id = _normalize_identifier(catalog)
    schema_id = f"{database_id}.{_normalize_identifier(schema)}"
    graph_database_id = _graph_database_id(graph_database)

    concepts: list[dict[str, Any]] = []
    table_mappings: list[dict[str, str]] = []
    column_mappings: list[dict[str, str]] = []
    graph_node_labels: dict[str, dict[str, str]] = {}
    graph_relationship_types: dict[str, dict[str, str]] = {}
    graph_properties: dict[str, dict[str, str]] = {}
    endpoint_rows: dict[tuple[str, str, str], dict[str, str]] = {}
    concept_graph_databases: list[dict[str, str]] = []
    concept_graph_node_labels: list[dict[str, str]] = []
    concept_graph_relationship_types: list[dict[str, str]] = []
    concept_graph_properties: list[dict[str, str]] = []

    for concept in mapping["concepts"]:
        databricks = concept["databricks"]
        neo4j = concept["neo4j"]
        tables = _databricks_tables(databricks)
        search_parts = [
            concept["name"],
            concept["definition"],
            concept["interpretation"],
            *tables,
            *databricks["columns"],
            *neo4j["node_labels"],
            *neo4j["relationship_types"],
            *neo4j["paths"],
        ]
        search_text = " | ".join(search_parts)
        concepts.append(
            {
                "id": concept["id"],
                "name": concept["name"],
                "definition": concept["definition"],
                "description": search_text,
                "interpretation": concept["interpretation"],
                "search_text": search_text,
                "is_primary": concept["id"] == primary,
                "mapping_version": version,
                "source_catalog": catalog,
                "source_schema": schema,
                "databricks_mapping": _canonical_json(databricks),
                "neo4j_mapping": _canonical_json(neo4j),
            }
        )
        for table in tables:
            table_mappings.append(
                {
                    "concept_id": concept["id"],
                    "database_id": database_id,
                    "schema_id": schema_id,
                    "table_id": _table_id(catalog, schema, table),
                }
            )
        for column in databricks["columns"]:
            table, column_name = _split_column(column, tables)
            column_mappings.append(
                {
                    "concept_id": concept["id"],
                    "database_id": database_id,
                    "schema_id": schema_id,
                    "table_id": _table_id(catalog, schema, table),
                    "column_id": _column_id(catalog, schema, table, column_name),
                }
            )

        concept_graph_databases.append(
            {"concept_id": concept["id"], "graph_database_id": graph_database_id}
        )
        for label in neo4j["node_labels"]:
            label_id = _graph_asset_id(graph_database, "node-label", label)
            graph_node_labels[label_id] = {
                "id": label_id,
                "name": label,
                "graph_database_id": graph_database_id,
            }
            concept_graph_node_labels.append({"concept_id": concept["id"], "asset_id": label_id})
        for relationship_type in neo4j["relationship_types"]:
            relationship_id = _graph_asset_id(
                graph_database, "relationship-type", relationship_type
            )
            graph_relationship_types[relationship_id] = {
                "id": relationship_id,
                "name": relationship_type,
                "graph_database_id": graph_database_id,
            }
            concept_graph_relationship_types.append(
                {"concept_id": concept["id"], "asset_id": relationship_id}
            )
        for owner, property_names in neo4j["properties"].items():
            owner_kind = "node-label" if owner in neo4j["node_labels"] else "relationship-type"
            owner_id = _graph_asset_id(graph_database, owner_kind, owner)
            for property_name in property_names:
                property_id = _graph_asset_id(
                    graph_database, "property", f"{owner_kind}:{owner}:{property_name}"
                )
                graph_properties[property_id] = {
                    "id": property_id,
                    "name": property_name,
                    "owner_id": owner_id,
                    "owner_kind": owner_kind,
                    "owner_name": owner,
                    "graph_database_id": graph_database_id,
                }
                concept_graph_properties.append(
                    {"concept_id": concept["id"], "asset_id": property_id}
                )
        for path in neo4j["paths"]:
            for relationship_type, source_label, target_label in _path_endpoints(path):
                key = relationship_type, source_label, target_label
                endpoint_rows[key] = {
                    "relationship_id": _graph_asset_id(
                        graph_database, "relationship-type", relationship_type
                    ),
                    "source_label_id": _graph_asset_id(graph_database, "node-label", source_label),
                    "target_label_id": _graph_asset_id(graph_database, "node-label", target_label),
                }

    return SemanticRecords(
        concepts=concepts,
        table_mappings=table_mappings,
        column_mappings=column_mappings,
        graph_databases=[
            {
                "id": graph_database_id,
                "name": graph_database,
                "description": "Operational Neo4j schema metadata; contains no source records.",
            }
        ],
        graph_node_labels=list(graph_node_labels.values()),
        graph_relationship_types=list(graph_relationship_types.values()),
        graph_properties=list(graph_properties.values()),
        relationship_endpoints=list(endpoint_rows.values()),
        concept_graph_databases=concept_graph_databases,
        concept_graph_node_labels=concept_graph_node_labels,
        concept_graph_relationship_types=concept_graph_relationship_types,
        concept_graph_properties=concept_graph_properties,
    )


def _read_csv_rows(
    csv_directory: Path,
    filename: str,
    expected_fields: set[str],
) -> list[dict[str, str]]:
    path = csv_directory / filename
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            actual_fields = set(reader.fieldnames or [])
            if actual_fields != expected_fields:
                raise MappingValidationError(
                    f"{filename} columns changed: expected {sorted(expected_fields)}, "
                    f"received {sorted(actual_fields)}"
                )
            return list(reader)
    except OSError as exc:
        raise MappingValidationError(f"Cannot read required Neocarta CSV {path}: {exc}") from exc


def _require_exact_csv_rows(
    actual: list[dict[str, str]],
    expected: list[dict[str, str]],
    filename: str,
) -> None:
    """Reject missing, extra, duplicated, or changed versioned CSV rows."""
    actual_rows = sorted(_canonical_json(row) for row in actual)
    expected_rows = sorted(_canonical_json(row) for row in expected)
    if actual_rows != expected_rows:
        raise MappingValidationError(f"{filename} has drifted from semantic-mappings.json")


def validate_neocarta_csvs(
    mapping: Mapping[str, Any], csv_directory: Path | str = MAPPINGS_DIR
) -> None:
    """Require the versioned Neocarta CSV inputs to exactly match the JSON contract."""
    validate_mapping(mapping)
    csv_path = Path(csv_directory)
    glossary_rows = _read_csv_rows(
        csv_path,
        "glossary_info.csv",
        {"glossary_name", "glossary_id", "name", "description"},
    )
    category_rows = _read_csv_rows(
        csv_path,
        "category_info.csv",
        {"glossary_name", "glossary_id", "category_name", "category_id", "name", "description"},
    )
    term_rows = _read_csv_rows(
        csv_path,
        "business_term_info.csv",
        {
            "glossary_name",
            "category_name",
            "category_id",
            "term_name",
            "business_term_id",
            "name",
            "description",
        },
    )
    table_rows = _read_csv_rows(
        csv_path,
        "table_term_info.csv",
        {
            "database_name",
            "schema_name",
            "table_name",
            "table_id",
            "glossary_name",
            "category_name",
            "term_name",
            "business_term_id",
        },
    )
    column_rows = _read_csv_rows(
        csv_path,
        "column_term_info.csv",
        {
            "database_name",
            "schema_name",
            "table_name",
            "column_name",
            "column_id",
            "glossary_name",
            "category_name",
            "term_name",
            "business_term_id",
        },
    )

    if len(glossary_rows) != 1 or glossary_rows[0].get("glossary_id") != GLOSSARY_ID:
        raise MappingValidationError("glossary_info.csv does not define the Finance glossary")
    if len(category_rows) != 1 or category_rows[0].get("category_id") != CATEGORY_ID:
        raise MappingValidationError("category_info.csv does not define the investigation category")

    expected_terms = [
        {
            "glossary_name": GLOSSARY_NAME,
            "category_name": CATEGORY_NAME,
            "category_id": CATEGORY_ID,
            "term_name": concept["id"],
            "business_term_id": concept["id"],
            "name": concept["name"],
            "description": concept["definition"],
        }
        for concept in mapping["concepts"]
    ]
    _require_exact_csv_rows(term_rows, expected_terms, "business_term_info.csv")

    scope = mapping["source_scope"]
    expected_tables: list[dict[str, str]] = []
    expected_columns: list[dict[str, str]] = []
    for concept in mapping["concepts"]:
        tables = _databricks_tables(concept["databricks"])
        for table in tables:
            expected_tables.append(
                {
                    "database_name": scope["databricks_catalog"],
                    "schema_name": scope["databricks_schema"],
                    "table_name": table,
                    "table_id": _table_id(
                        scope["databricks_catalog"], scope["databricks_schema"], table
                    ),
                    "glossary_name": GLOSSARY_NAME,
                    "category_name": CATEGORY_NAME,
                    "term_name": concept["id"],
                    "business_term_id": concept["id"],
                }
            )
        for column in concept["databricks"]["columns"]:
            table, column_name = _split_column(column, tables)
            expected_columns.append(
                {
                    "database_name": scope["databricks_catalog"],
                    "schema_name": scope["databricks_schema"],
                    "table_name": table,
                    "column_name": column_name,
                    "column_id": _column_id(
                        scope["databricks_catalog"],
                        scope["databricks_schema"],
                        table,
                        column_name,
                    ),
                    "glossary_name": GLOSSARY_NAME,
                    "category_name": CATEGORY_NAME,
                    "term_name": concept["id"],
                    "business_term_id": concept["id"],
                }
            )
    _require_exact_csv_rows(table_rows, expected_tables, "table_term_info.csv")
    _require_exact_csv_rows(column_rows, expected_columns, "column_term_info.csv")


def load_neocarta_csvs(
    driver: Any,
    database: str,
    csv_directory: Path | str = MAPPINGS_DIR,
    connector_factory: Callable[..., Any] | None = None,
) -> None:
    """Load standard glossary nodes and TAGGED_WITH mappings via Neocarta."""
    if connector_factory is None:
        from neocarta.connectors.csv import CSVConnector
        from neocarta.enums import NodeLabel, RelationshipType

        connector_factory = CSVConnector
        node_labels: list[Any] = [
            NodeLabel.GLOSSARY,
            NodeLabel.CATEGORY,
            NodeLabel.BUSINESS_TERM,
        ]
        relationship_types: list[Any] = [
            RelationshipType.HAS_CATEGORY,
            RelationshipType.HAS_BUSINESS_TERM,
            RelationshipType.TAGGED_WITH,
        ]
    else:
        node_labels = ["Glossary", "Category", "BusinessTerm"]
        relationship_types = ["HAS_CATEGORY", "HAS_BUSINESS_TERM", "TAGGED_WITH"]

    connector = connector_factory(
        csv_directory=str(csv_directory),
        neo4j_driver=driver,
        database_name=database,
    )
    connector.ingest(
        include_nodes=node_labels,
        include_relationships=relationship_types,
    )


_SCHEMA_QUERIES = (
    (
        "CYPHER 25 CREATE CONSTRAINT graph_database_id_constraint IF NOT EXISTS "
        "FOR (n:GraphDatabase) REQUIRE n.id IS UNIQUE"
    ),
    (
        "CYPHER 25 CREATE CONSTRAINT graph_node_label_id_constraint IF NOT EXISTS "
        "FOR (n:GraphNodeLabel) REQUIRE n.id IS UNIQUE"
    ),
    (
        "CYPHER 25 CREATE CONSTRAINT graph_relationship_type_id_constraint IF NOT EXISTS "
        "FOR (n:GraphRelationshipType) REQUIRE n.id IS UNIQUE"
    ),
    (
        "CYPHER 25 CREATE CONSTRAINT graph_property_id_constraint IF NOT EXISTS "
        "FOR (n:GraphProperty) REQUIRE n.id IS UNIQUE"
    ),
)

_CONCEPT_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (concept:BusinessTerm {id: row.id})
SET concept:BusinessConcept,
    concept.name = row.name,
    concept.definition = row.definition,
    concept.description = row.description,
    concept.interpretation = row.interpretation,
    concept.search_text = row.search_text,
    concept.is_primary = row.is_primary,
    concept.mapping_version = row.mapping_version,
    concept.source_catalog = row.source_catalog,
    concept.source_schema = row.source_schema,
    concept.databricks_mapping = row.databricks_mapping,
    concept.neo4j_mapping = row.neo4j_mapping
RETURN count(*) AS processed
"""

_TABLE_MAPPING_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (concept:BusinessConcept {id: row.concept_id})
MATCH (:Database {id: row.database_id})-[:HAS_SCHEMA]->(:Schema {id: row.schema_id})
      -[:HAS_TABLE]->(asset:Table {id: row.table_id})
MERGE (concept)-[:MAPS_TO_TABLE]->(asset)
RETURN count(*) AS processed
"""

_COLUMN_MAPPING_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (concept:BusinessConcept {id: row.concept_id})
MATCH (:Database {id: row.database_id})-[:HAS_SCHEMA]->(:Schema {id: row.schema_id})
      -[:HAS_TABLE]->(:Table {id: row.table_id})-[:HAS_COLUMN]->(asset:Column {id: row.column_id})
MERGE (concept)-[:MAPS_TO_COLUMN]->(asset)
RETURN count(*) AS processed
"""

_GRAPH_DATABASE_QUERY = """CYPHER 25
UNWIND $rows AS row
MERGE (asset:GraphDatabase {id: row.id})
SET asset.name = row.name, asset.description = row.description, asset.metadata_only = true
RETURN count(*) AS processed
"""

_GRAPH_NODE_LABEL_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (database:GraphDatabase {id: row.graph_database_id})
MERGE (asset:GraphNodeLabel {id: row.id})
SET asset.name = row.name, asset.metadata_only = true
MERGE (database)-[:HAS_NODE_LABEL]->(asset)
RETURN count(*) AS processed
"""

_GRAPH_RELATIONSHIP_TYPE_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (database:GraphDatabase {id: row.graph_database_id})
MERGE (asset:GraphRelationshipType {id: row.id})
SET asset.name = row.name, asset.metadata_only = true
MERGE (database)-[:HAS_RELATIONSHIP_TYPE]->(asset)
RETURN count(*) AS processed
"""

_GRAPH_PROPERTY_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (database:GraphDatabase {id: row.graph_database_id})
MERGE (asset:GraphProperty {id: row.id})
SET asset.name = row.name,
    asset.owner_kind = row.owner_kind,
    asset.owner_name = row.owner_name,
    asset.metadata_only = true
WITH row, asset, database
OPTIONAL MATCH (node_owner:GraphNodeLabel {id: row.owner_id})
OPTIONAL MATCH (relationship_owner:GraphRelationshipType {id: row.owner_id})
FOREACH (_ IN CASE WHEN node_owner IS NULL THEN [] ELSE [1] END |
    MERGE (node_owner)-[:HAS_PROPERTY]->(asset))
FOREACH (_ IN CASE WHEN relationship_owner IS NULL THEN [] ELSE [1] END |
    MERGE (relationship_owner)-[:HAS_PROPERTY]->(asset))
RETURN count(*) AS processed
"""

_ENDPOINT_QUERY = """CYPHER 25
UNWIND $rows AS row
MATCH (relationship:GraphRelationshipType {id: row.relationship_id})
MATCH (source:GraphNodeLabel {id: row.source_label_id})
MATCH (target:GraphNodeLabel {id: row.target_label_id})
MERGE (relationship)-[:HAS_SOURCE_LABEL]->(source)
MERGE (relationship)-[:HAS_TARGET_LABEL]->(target)
RETURN count(*) AS processed
"""


def _concept_mapping_query(asset_label: str, relationship: str) -> str:
    return f"""CYPHER 25
UNWIND $rows AS row
MATCH (concept:BusinessConcept {{id: row.concept_id}})
MATCH (asset:{asset_label} {{id: row.asset_id}})
MERGE (concept)-[:{relationship}]->(asset)
RETURN count(*) AS processed
"""


def _run_rows(driver: Any, database: str, query: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    records, _, _ = driver.execute_query(
        query_=query,
        parameters_={"rows": rows},
        database_=database,
    )
    processed = records[0]["processed"] if records else 0
    if processed != len(rows):
        raise RuntimeError(
            f"Semantic graph write matched {processed} of {len(rows)} expected metadata rows"
        )
    return processed


def _unique_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        key = _canonical_json(row)
        unique[key] = row
    return list(unique.values())


def write_graph_adapter(driver: Any, database: str, records: SemanticRecords) -> SemanticLoadCounts:
    """Write rich concepts, explicit mappings, and graph-schema metadata."""
    for query in _SCHEMA_QUERIES:
        driver.execute_query(query_=query, database_=database)

    _run_rows(driver, database, _CONCEPT_QUERY, records.concepts)
    _run_rows(driver, database, _GRAPH_DATABASE_QUERY, records.graph_databases)
    _run_rows(driver, database, _GRAPH_NODE_LABEL_QUERY, records.graph_node_labels)
    _run_rows(driver, database, _GRAPH_RELATIONSHIP_TYPE_QUERY, records.graph_relationship_types)
    _run_rows(driver, database, _GRAPH_PROPERTY_QUERY, records.graph_properties)
    _run_rows(driver, database, _ENDPOINT_QUERY, records.relationship_endpoints)
    _run_rows(driver, database, _TABLE_MAPPING_QUERY, records.table_mappings)
    _run_rows(driver, database, _COLUMN_MAPPING_QUERY, records.column_mappings)

    graph_database_links = _unique_rows(records.concept_graph_databases)
    label_links = _unique_rows(records.concept_graph_node_labels)
    relationship_links = _unique_rows(records.concept_graph_relationship_types)
    property_links = _unique_rows(records.concept_graph_properties)
    _run_rows(
        driver,
        database,
        _concept_mapping_query("GraphDatabase", "MAPS_TO_GRAPH_ASSET"),
        [
            {"concept_id": row["concept_id"], "asset_id": row["graph_database_id"]}
            for row in graph_database_links
        ],
    )
    _run_rows(
        driver,
        database,
        _concept_mapping_query("GraphNodeLabel", "MAPS_TO_GRAPH_ASSET"),
        label_links,
    )
    _run_rows(
        driver,
        database,
        _concept_mapping_query("GraphRelationshipType", "MAPS_TO_GRAPH_ASSET"),
        relationship_links,
    )
    _run_rows(
        driver,
        database,
        _concept_mapping_query("GraphProperty", "MAPS_TO_GRAPH_ASSET"),
        property_links,
    )

    return SemanticLoadCounts(
        concepts=len(records.concepts),
        table_mappings=len(records.table_mappings),
        column_mappings=len(records.column_mappings),
        graph_databases=len(records.graph_databases),
        graph_node_labels=len(records.graph_node_labels),
        graph_relationship_types=len(records.graph_relationship_types),
        graph_properties=len(records.graph_properties),
        relationship_endpoints=len(records.relationship_endpoints),
        concept_graph_asset_mappings=(
            len(graph_database_links)
            + len(label_links)
            + len(relationship_links)
            + len(property_links)
        ),
    )


def embed_business_concepts(
    driver: Any,
    database: str,
    embedding_model: str,
    *,
    batch_size: int = 100,
    connector_factory: Callable[..., Any] | None = None,
) -> int | None:
    """Embed BusinessTerm nodes and create its native-dimension vector index."""
    if not embedding_model.startswith("databricks/"):
        raise ValueError("embedding_model must use the databricks/ provider prefix")
    if connector_factory is None:
        from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector
        from neocarta.enums import NodeLabel

        connector_factory = LiteLLMEmbeddingsConnector
        business_term_label: Any = NodeLabel.BUSINESS_TERM
    else:
        business_term_label = "BusinessTerm"
    connector = connector_factory(
        neo4j_driver=driver,
        embedding_model=embedding_model,
        database_name=database,
        dimensions=None,
    )
    connector.run(node_labels=[business_term_label], batch_size=batch_size)
    return connector.dimensions


def load_semantic_graph(
    driver: Any,
    database: str,
    *,
    mapping_path: Path | str = DEFAULT_MAPPING_FILE,
    csv_directory: Path | str = MAPPINGS_DIR,
    embedding_model: str | None = None,
    csv_connector_factory: Callable[..., Any] | None = None,
    embedding_connector_factory: Callable[..., Any] | None = None,
) -> SemanticLoadCounts:
    """Load and optionally embed the complete semantic metadata graph."""
    mapping = load_mapping(mapping_path)
    validate_neocarta_csvs(mapping, csv_directory)
    load_neocarta_csvs(driver, database, csv_directory, csv_connector_factory)
    counts = write_graph_adapter(driver, database, build_records(mapping))
    if embedding_model is not None:
        embed_business_concepts(
            driver,
            database,
            embedding_model,
            connector_factory=embedding_connector_factory,
        )
    return counts

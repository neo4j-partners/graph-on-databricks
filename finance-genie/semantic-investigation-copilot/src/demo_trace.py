"""Build the deterministic, prepared-query trace for the shared-identity demo.

This module deliberately does not connect to either source system.  It accepts
the response returned by semantic retrieval, prepares two read-only source
checks, and attaches the already-recorded source-mapping evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from business_context import normalize_business_concept
from semantic_graph import MappingValidationError, validate_mapping

DEMO_ROOT = Path(__file__).parents[1]
DEFAULT_CONTEXT = DEMO_ROOT / "mappings" / "semantic-mappings.json"
DEFAULT_EVIDENCE = DEMO_ROOT / "validation" / "source-mapping-validation.json"
DEFAULT_TRACE_FILE = DEMO_ROOT / "validation" / "shared-identity-demo-trace.json"

SHARED_IDENTITY = "shared_identity"
EXPECTED_TABLE = "graph-on-databricks.graph-enriched-schema.gold_accounts"
EXPECTED_COLUMNS = (
    "account_id",
    "identity_cluster_id",
    "identity_cluster_size",
    "shared_phone_count",
    "shared_address_count",
)
EXPECTED_NODE_LABELS = frozenset({"Customer", "Account", "Phone", "Address", "BusinessTerm"})
EXPECTED_RELATIONSHIPS = frozenset(
    {
        "OWNS",
        "HAS_PHONE",
        "HAS_ADDRESS",
        "CLASSIFIED_AS",
        "DEFINED_BY",
        "GOVERNED_BY",
        "DERIVED_FROM",
    }
)
EXPECTED_PATHS = frozenset(
    {
        "(:Customer)-[:OWNS]->(:Account)",
        "(:Customer)-[:HAS_PHONE]->(:Phone)<-[:HAS_PHONE]-(:Customer)",
        "(:Customer)-[:HAS_ADDRESS]->(:Address)<-[:HAS_ADDRESS]-(:Customer)",
        (
            "(:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm)-[:DEFINED_BY]->"
            "(:BusinessRule)-[:DERIVED_FROM]->(:DataSource)"
        ),
        "(:BusinessTerm)-[:GOVERNED_BY]->(:Policy)",
    }
)
EXPECTED_PROPERTIES = {
    "Account": frozenset(EXPECTED_COLUMNS),
    "Phone": frozenset({"number"}),
    "Address": frozenset({"address"}),
    "BusinessTerm": frozenset({"name"}),
    "BusinessRule": frozenset({"name"}),
    "DataSource": frozenset({"name"}),
    "Policy": frozenset({"name"}),
    "CLASSIFIED_AS": frozenset({"cluster_id", "reason"}),
}

LAKEHOUSE_QUERY = """SELECT
  account_id,
  identity_cluster_id,
  identity_cluster_size,
  shared_phone_count,
  shared_address_count
FROM `graph-on-databricks`.`graph-enriched-schema`.`gold_accounts`
WHERE identity_cluster_id = :identity_cluster_id
  AND identity_cluster_size > 1
ORDER BY account_id"""

GRAPH_QUERY = """CYPHER 25
MATCH (customer:Customer)-[:OWNS]->(account:Account)
WHERE account.identity_cluster_id = $identity_cluster_id
  AND account.account_id IS NOT NULL
OPTIONAL MATCH (customer)-[:HAS_PHONE]->(phone:Phone)<-[:HAS_PHONE]-(phone_peer:Customer)
WHERE phone_peer <> customer
  AND phone_peer.identity_cluster_id = $identity_cluster_id
OPTIONAL MATCH (customer)-[:HAS_ADDRESS]->(address:Address)<-[:HAS_ADDRESS]-(address_peer:Customer)
WHERE address_peer <> customer
  AND address_peer.identity_cluster_id = $identity_cluster_id
WITH customer, account,
  collect(DISTINCT phone.number) AS shared_phone_numbers,
  collect(DISTINCT address.address) AS shared_addresses
MATCH (customer)-[classification:CLASSIFIED_AS]->(term:BusinessTerm)
WHERE classification.cluster_id = $identity_cluster_id
OPTIONAL MATCH (term)-[:DEFINED_BY]->(rule:BusinessRule)
OPTIONAL MATCH (rule)-[:DERIVED_FROM]->(source:DataSource)
OPTIONAL MATCH (term)-[:GOVERNED_BY]->(policy:Policy)
RETURN account.account_id AS account_id,
  account.identity_cluster_id AS identity_cluster_id,
  account.identity_cluster_size AS identity_cluster_size,
  account.shared_phone_count AS shared_phone_count,
  account.shared_address_count AS shared_address_count,
  shared_phone_numbers, shared_addresses,
  classification.reason AS classification_reason,
  term.name AS business_term,
  rule.name AS business_rule,
  collect(DISTINCT source.name) AS data_sources,
  policy.name AS policy
ORDER BY account_id"""


class DemoContractError(ValueError):
    """Raised when retrieved mappings or fixture evidence are not demo-safe."""


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object from *path*."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DemoContractError(f"Expected a JSON object in {path}")
    return value


def adapt_mapping_artifact(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the versioned mapping artifact to the retrieval response contract.

    This is an offline presenter fallback.  The live path should pass the
    response returned by ``get_business_concept_context`` directly.
    """
    try:
        validated_mapping = validate_mapping(dict(mapping))
    except MappingValidationError as error:
        raise DemoContractError(f"Invalid semantic mapping artifact: {error}") from error

    concepts = validated_mapping["concepts"]
    scope = validated_mapping["source_scope"]

    concept = next(
        (item for item in concepts if item.get("id") == SHARED_IDENTITY),
        None,
    )
    if concept is None:
        raise DemoContractError("Mapping artifact has no shared_identity concept")

    databricks = concept["databricks"]
    catalog = str(scope["databricks_catalog"])
    schema = str(scope["databricks_schema"])
    normalized = normalize_business_concept(
        {
            "id": concept["id"],
            "name": concept["name"],
            "definition": concept["definition"],
            "interpretation": concept["interpretation"],
            "source_catalog": catalog,
            "source_schema": schema,
            "databricks_mapping": databricks,
            "neo4j_mapping": {
                "database": scope["neo4j_database"],
                **concept["neo4j"],
            },
        },
        score=None,
    )

    return {
        "query": "shared identity",
        "retrieval_mode": "versioned_mapping_fallback",
        "matches": [normalized],
    }


def normalize_retrieval_response(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a retrieval response, adapting the checked-in mapping if needed."""
    if isinstance(value.get("matches"), list):
        return dict(value)
    return adapt_mapping_artifact(value)


def select_shared_identity_match(response: Mapping[str, Any]) -> dict[str, Any]:
    """Select and validate the top retrieval match for the demo phrase."""
    matches = response.get("matches")
    if not isinstance(matches, Sequence) or isinstance(matches, (str, bytes)):
        raise DemoContractError("Semantic retrieval response has no matches list")
    if not matches or not isinstance(matches[0], Mapping):
        raise DemoContractError("Semantic retrieval returned no concept matches")

    match = dict(matches[0])
    if match.get("concept_id") != SHARED_IDENTITY:
        raise DemoContractError("Top semantic match is not shared_identity")
    for field in ("name", "definition", "interpretation", "databricks", "neo4j"):
        if field not in match:
            raise DemoContractError(f"Shared identity match is missing {field}")
    return match


def _terminal_asset_name(asset: object) -> str:
    return str(asset).rsplit(".", maxsplit=1)[-1]


def _string_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DemoContractError(f"Retrieved mapping has no {field} list")
    return value


def _validate_lakehouse_mapping(mapping: Mapping[str, Any]) -> None:
    tables = _string_sequence(mapping.get("tables"), "tables")
    columns = _string_sequence(mapping.get("columns"), "columns")
    predicates = _string_sequence(mapping.get("predicates"), "predicates")
    if EXPECTED_TABLE not in tables:
        raise DemoContractError("Retrieved mapping does not contain gold_accounts")
    column_names = {_terminal_asset_name(column) for column in columns}
    missing = set(EXPECTED_COLUMNS) - column_names
    if missing:
        raise DemoContractError(
            f"Retrieved lakehouse mapping is missing columns: {sorted(missing)}"
        )
    expected_predicate = f"{EXPECTED_TABLE}.identity_cluster_size > 1"
    if not ({"identity_cluster_size > 1", expected_predicate} & set(predicates)):
        raise DemoContractError("Retrieved mapping is missing the shared-identity predicate")
    if mapping.get("catalog") != "graph-on-databricks":
        raise DemoContractError("Retrieved mapping targets an unexpected Databricks catalog")
    if mapping.get("schema") != "graph-enriched-schema":
        raise DemoContractError("Retrieved mapping targets an unexpected Databricks schema")


def _validate_graph_mapping(mapping: Mapping[str, Any]) -> None:
    labels = set(_string_sequence(mapping.get("node_labels"), "node_labels"))
    relationships = set(_string_sequence(mapping.get("relationship_types"), "relationship_types"))
    paths = set(_string_sequence(mapping.get("paths"), "paths"))
    if not EXPECTED_NODE_LABELS <= labels:
        raise DemoContractError("Retrieved graph mapping is missing shared-identity labels")
    if not EXPECTED_RELATIONSHIPS <= relationships:
        raise DemoContractError("Retrieved graph mapping is missing shared-identity relationships")
    if not EXPECTED_PATHS <= paths:
        raise DemoContractError("Retrieved graph mapping is missing shared-identity paths")
    properties = mapping.get("properties")
    if not isinstance(properties, Mapping):
        raise DemoContractError("Retrieved graph mapping has no properties object")
    for owner, expected in EXPECTED_PROPERTIES.items():
        actual = set(_string_sequence(properties.get(owner), f"{owner} properties"))
        if not expected <= actual:
            raise DemoContractError(
                f"Retrieved graph mapping is missing required {owner} properties"
            )
    if mapping.get("database") != "neo4j":
        raise DemoContractError("Retrieved graph mapping targets an unexpected database")


def prepare_lakehouse_query(mapping: Mapping[str, Any], cluster_id: int) -> dict[str, Any]:
    """Prepare the fixed, parameterized Databricks source check."""
    _validate_lakehouse_mapping(mapping)
    return {
        "target": EXPECTED_TABLE,
        "language": "sql",
        "read_only": True,
        "parameters": {"identity_cluster_id": cluster_id},
        "text": LAKEHOUSE_QUERY,
    }


def prepare_graph_query(mapping: Mapping[str, Any], cluster_id: int) -> dict[str, Any]:
    """Prepare the fixed, parameterized Neo4j source check."""
    _validate_graph_mapping(mapping)
    return {
        "target": mapping["database"],
        "language": "cypher",
        "read_only": True,
        "parameters": {"identity_cluster_id": cluster_id},
        "text": GRAPH_QUERY,
    }


def _fixture_from_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    databricks = evidence.get("databricks")
    neo4j = evidence.get("neo4j")
    if not isinstance(databricks, Mapping) or not isinstance(neo4j, Mapping):
        raise DemoContractError("Source-mapping evidence is missing source sections")
    lakehouse_fixture = databricks.get("fixture")
    graph_fixture = neo4j.get("fixture")
    if not isinstance(lakehouse_fixture, Mapping) or not isinstance(graph_fixture, Mapping):
        raise DemoContractError("Source-mapping evidence is missing fixture sections")

    comparable_fields = (
        "identity_cluster_id",
        "account_ids",
        "identity_cluster_size",
        "account_observations",
    )
    for field in comparable_fields:
        if lakehouse_fixture.get(field) != graph_fixture.get(field):
            raise DemoContractError(f"Source-mapping fixtures disagree on {field}")
    if lakehouse_fixture.get("rows_verified") != graph_fixture.get("accounts"):
        raise DemoContractError("Source-mapping fixtures disagree on row count")

    return {field: lakehouse_fixture[field] for field in comparable_fields} | {
        "rows_verified": lakehouse_fixture["rows_verified"]
    }


def build_demo_trace(
    retrieval_response: Mapping[str, Any],
    source_mapping_evidence: Mapping[str, Any],
    *,
    phrase: str = "shared identity",
) -> dict[str, Any]:
    """Build a deterministic demo trace without executing source queries."""
    response = normalize_retrieval_response(retrieval_response)
    concept = select_shared_identity_match(response)
    fixture = _fixture_from_evidence(source_mapping_evidence)
    cluster_id = int(fixture["identity_cluster_id"])

    lakehouse_mapping = concept["databricks"]
    graph_mapping = concept["neo4j"]
    lakehouse_check = prepare_lakehouse_query(lakehouse_mapping, cluster_id)
    graph_check = prepare_graph_query(graph_mapping, cluster_id)

    source_observations = fixture["account_observations"]
    return {
        "trace_version": 1,
        "request": {"phrase": phrase, "query_execution": "not_performed"},
        "retrieval": {
            "query": response.get("query", phrase),
            "mode": response.get("retrieval_mode", "unspecified"),
            "selected_match_rank": 1,
            "score": concept.get("score"),
        },
        "term": {
            "concept_id": concept["concept_id"],
            "name": concept["name"],
            "definition": concept["definition"],
            "interpretation": concept["interpretation"],
        },
        "mappings": {
            "databricks": lakehouse_mapping,
            "neo4j": graph_mapping,
        },
        "prepared_source_checks": {
            "databricks": lakehouse_check,
            "neo4j": graph_check,
        },
        "source_evidence": {
            "synthetic_fixture": True,
            "identity_cluster_id": cluster_id,
            "account_ids": fixture["account_ids"],
            "identity_cluster_size": fixture["identity_cluster_size"],
            "databricks": {
                "status": "verified_by_source_mapping_validation",
                "rows_verified": fixture["rows_verified"],
                "account_observations": source_observations,
            },
            "neo4j": {
                "status": "verified_by_source_mapping_validation",
                "accounts_verified": fixture["rows_verified"],
                "account_observations": source_observations,
            },
        },
        "limits": [
            "The source queries are prepared examples and were not executed by this demo.",
            "Semantic discovery does not grant access to Databricks or Neo4j.",
            "Shared identity is an investigation signal, not a fraud determination.",
        ],
    }


async def retrieve_demo_trace(
    retrieve: Callable[[str], Mapping[str, Any] | Awaitable[Mapping[str, Any]]],
    source_mapping_evidence: Mapping[str, Any],
    *,
    phrase: str = "shared identity",
) -> dict[str, Any]:
    """Retrieve semantic context through an injected retrieval adapter."""
    response = retrieve(phrase)
    if inspect.isawaitable(response):
        response = await response
    return build_demo_trace(response, source_mapping_evidence, phrase=phrase)


def _observation_key(row: Mapping[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        int(row["account_id"]),
        int(row["identity_cluster_id"]),
        int(row["identity_cluster_size"]),
        int(row["shared_phone_count"]),
        int(row["shared_address_count"]),
    )


def validate_fixture_results(
    lakehouse_rows: Sequence[Mapping[str, Any]],
    graph_rows: Sequence[Mapping[str, Any]],
    source_evidence: Mapping[str, Any],
) -> None:
    """Validate independently executed source results against the known fixture."""
    cluster_id = int(source_evidence["identity_cluster_id"])
    cluster_size = int(source_evidence["identity_cluster_size"])
    expected = {
        (
            int(row["account_id"]),
            cluster_id,
            cluster_size,
            int(row["shared_phone_count"]),
            int(row["shared_address_count"]),
        )
        for row in source_evidence["databricks"]["account_observations"]
    }
    for source, rows in (("Databricks", lakehouse_rows), ("Neo4j", graph_rows)):
        observed = {_observation_key(row) for row in rows}
        if len(rows) != len(expected) or observed != expected:
            raise DemoContractError(f"{source} results do not match the known fixture")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Print the prepared shared-identity demo trace.")
    parser.add_argument(
        "--context-file",
        type=Path,
        default=DEFAULT_CONTEXT,
        help="Retrieval response JSON, or the versioned mappings as an offline fallback.",
    )
    parser.add_argument(
        "--evidence-file",
        type=Path,
        default=DEFAULT_EVIDENCE,
        help="Source-mapping validation evidence JSON.",
    )
    parser.add_argument("--phrase", default="shared identity")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the versioned mapping instead of live semantic retrieval.",
    )
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--output-file", type=Path, default=DEFAULT_TRACE_FILE)
    return parser.parse_args(argv)


async def retrieve_live_context(phrase: str) -> dict[str, Any]:
    """Retrieve a concept through the same vector path exposed by the MCP tool."""
    from neo4j import AsyncGraphDatabase
    from neocarta._mcp.embeddings import create_embedder

    from business_context import get_business_concept_context
    from config import (
        assert_semantic_store_target,
        load_demo_env,
        require_env,
    )

    load_demo_env()
    assert_semantic_store_target()
    database = require_env("NEO4J_DATABASE")
    driver = AsyncGraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        embedder = create_embedder(driver, database)
        return await get_business_concept_context(
            phrase,
            driver,
            database,
            embedder,
        )
    finally:
        await driver.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Print a live semantic trace without executing its prepared source queries."""
    args = parse_args(argv)
    context = (
        load_json(args.context_file)
        if args.offline
        else asyncio.run(retrieve_live_context(args.phrase))
    )
    trace = build_demo_trace(
        context,
        load_json(args.evidence_file),
        phrase=args.phrase,
    )
    if args.write_evidence:
        args.output_file.write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(trace, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

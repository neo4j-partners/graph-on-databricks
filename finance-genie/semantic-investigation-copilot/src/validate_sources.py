"""Validate and optionally record the live cross-system source mappings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from databricks import sql
from dotenv import dotenv_values
from neo4j import GraphDatabase, RoutingControl

from config import (
    DEMO_DIR,
    databricks_http_path,
    databricks_server_hostname,
    load_demo_env,
    require_env,
)
from ingest import databricks_access_token

MAPPING_FILE = DEMO_DIR / "mappings" / "semantic-mappings.json"
EVIDENCE_FILE = DEMO_DIR / "validation" / "source-mapping-validation.json"
OPERATIONAL_ENV_FILE = DEMO_DIR.parent / ".env"
GROUND_TRUTH_FILE = DEMO_DIR.parent / "data" / "ground_truth.json"
GDS_WORKING_DIRECTORY = DEMO_DIR.parent / "enrichment-pipeline"
GDS_SCRIPT = GDS_WORKING_DIRECTORY / "validation" / "verify_gds.py"
GDS_COMMAND = "uv run --locked python validation/verify_gds.py"
JOIN_EXPRESSION = re.compile(
    r"^(?P<left_table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<left_column>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<right_table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<right_column>[A-Za-z_][A-Za-z0-9_]*)$"
)
PREDICATE_EXPRESSION = re.compile(
    r"^(?P<column>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<operator>>|=)\s*(?P<literal>[0-9]+|'[^']*')$"
)
FIXTURE_CLUSTER_ID = 367
SUPPORTED_DATABRICKS_TYPES = {"BOOLEAN", "DOUBLE", "LONG", "STRING", "TIMESTAMP"}
SAFE_PATH_PATTERNS = {
    "(:Account)-[:SIMILAR_TO]-(:Account)",
    "(:Account)-[:TRANSFERRED_TO]-(:Account)",
    "(:Account)-[:TRANSFERRED_TO]->(:Account)",
    "(:BusinessTerm)-[:GOVERNED_BY]->(:Policy)",
    "(:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm {name: 'Shared Identity Ring'})",
    (
        "(:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm)-[:DEFINED_BY]->"
        "(:BusinessRule)-[:DERIVED_FROM]->(:DataSource)"
    ),
    "(:Customer)-[:HAS_ADDRESS]->(:Address)<-[:HAS_ADDRESS]-(:Customer)",
    "(:Customer)-[:HAS_PHONE]->(:Phone)<-[:HAS_PHONE]-(:Customer)",
    "(:Customer)-[:OWNS]->(:Account)",
}


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def quote_identifier(value: str) -> str:
    """Quote a checked identifier for Databricks SQL or Cypher."""
    if not value or "\x00" in value:
        raise RuntimeError(f"Unsupported identifier in mapping contract: {value!r}")
    return f"`{value.replace('`', '``')}`"


def mapping_digest() -> str:
    """Return the SHA-256 digest of the exact mapping artifact."""
    return hashlib.sha256(MAPPING_FILE.read_bytes()).hexdigest()


def file_digest(path: Path) -> str:
    """Return the SHA-256 digest of a versioned validation input."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_predicate(expression: str) -> tuple[str, str, int | str]:
    """Parse the deliberately small predicate language used by source validation."""
    match = PREDICATE_EXPRESSION.fullmatch(expression)
    if match is None:
        raise RuntimeError(f"Unsupported Databricks predicate: {expression!r}")
    literal = match["literal"]
    value: int | str = int(literal) if literal.isdigit() else literal[1:-1]
    return match["column"], match["operator"], value


def load_fixture_contract() -> dict[str, Any]:
    """Load exact shared-identity expectations from versioned ground truth."""
    ground_truth = load_json(GROUND_TRUTH_FILE)
    fixture = ground_truth.get("kyc_story_ring")
    if fixture is None:
        raise RuntimeError(f"kyc_story_ring is missing from {GROUND_TRUTH_FILE}")
    if not isinstance(fixture, dict):
        raise TypeError(f"kyc_story_ring must be an object in {GROUND_TRUTH_FILE}")

    account_ids = [int(value) for value in fixture["account_ids"]]
    phone_counts = {account_id: 0 for account_id in account_ids}
    for members in fixture["shared_phones"].values():
        for account_id in members:
            phone_counts[int(account_id)] = len(members) - 1
    address_counts = {account_id: 0 for account_id in account_ids}
    for members in fixture["shared_address"].values():
        for account_id in members:
            address_counts[int(account_id)] = len(members) - 1

    return {
        "account_ids": sorted(account_ids),
        "identity_cluster_id": FIXTURE_CLUSTER_ID,
        "identity_cluster_size": len(account_ids),
        "shared_phone_count": phone_counts,
        "shared_address_count": address_counts,
    }


def validate_fixture_rows(
    rows: list[dict[str, Any]], fixture: dict[str, Any], source: str
) -> list[dict[str, int]]:
    """Require the exact account set, cluster size, and shared counts."""
    observations = [
        {
            "account_id": int(row["account_id"]),
            "identity_cluster_size": int(row["identity_cluster_size"]),
            "shared_phone_count": int(row["shared_phone_count"]),
            "shared_address_count": int(row["shared_address_count"]),
        }
        for row in rows
    ]
    observations.sort(key=lambda row: row["account_id"])
    actual_ids = [row["account_id"] for row in observations]
    if actual_ids != fixture["account_ids"]:
        raise RuntimeError(
            f"{source} identity cluster {FIXTURE_CLUSTER_ID} contains {actual_ids}, "
            f"expected {fixture['account_ids']}"
        )
    mismatches = []
    for row in observations:
        account_id = row["account_id"]
        expected = {
            "identity_cluster_size": fixture["identity_cluster_size"],
            "shared_phone_count": fixture["shared_phone_count"][account_id],
            "shared_address_count": fixture["shared_address_count"][account_id],
        }
        actual = {key: row[key] for key in expected}
        if actual != expected:
            mismatches.append({"account_id": account_id, "expected": expected, "actual": actual})
    if mismatches:
        raise RuntimeError(f"{source} shared-identity fixture mismatches: {mismatches}")
    return observations


def collect_databricks_contract(mapping: dict[str, Any]) -> dict[str, Any]:
    """Normalize all Databricks assets claimed by the concept mappings."""
    columns: dict[tuple[str, str], set[str]] = defaultdict(set)
    joins: dict[str, set[str]] = defaultdict(set)
    predicates: dict[tuple[str, str], set[str]] = defaultdict(set)

    for concept in mapping["concepts"]:
        concept_id = concept["id"]
        databricks = concept["databricks"]
        default_table = databricks.get("table")
        for column in databricks.get("columns", []):
            if "." in column:
                table, column_name = column.split(".", maxsplit=1)
            elif default_table:
                table, column_name = default_table, column
            else:
                raise RuntimeError(
                    f"Concept {concept_id!r} has an unqualified column without a table: {column}"
                )
            quote_identifier(table)
            quote_identifier(column_name)
            columns[(table, column_name)].add(concept_id)

        for expression in databricks.get("join_keys", []):
            match = JOIN_EXPRESSION.fullmatch(expression)
            if match is None:
                raise RuntimeError(f"Unsupported join expression: {expression!r}")
            for side in ("left", "right"):
                columns[(match[f"{side}_table"], match[f"{side}_column"])].add(concept_id)
            joins[expression].add(concept_id)

        predicate = databricks.get("predicate")
        if predicate:
            if not default_table:
                raise RuntimeError(f"Concept {concept_id!r} has a predicate without a table")
            parse_predicate(predicate)
            predicates[(default_table, predicate)].add(concept_id)

    return {"columns": columns, "joins": joins, "predicates": predicates}


def collect_neo4j_contract(mapping: dict[str, Any]) -> dict[str, Any]:
    """Normalize all Neo4j assets claimed by the concept mappings."""
    labels: dict[str, set[str]] = defaultdict(set)
    relationships: dict[str, set[str]] = defaultdict(set)
    node_properties: dict[tuple[str, str], set[str]] = defaultdict(set)
    relationship_properties: dict[tuple[str, str], set[str]] = defaultdict(set)
    paths: dict[str, set[str]] = defaultdict(set)

    for concept in mapping["concepts"]:
        concept_id = concept["id"]
        neo4j = concept["neo4j"]
        concept_relationships = set(neo4j.get("relationship_types", []))
        for label in neo4j.get("node_labels", []):
            quote_identifier(label)
            labels[label].add(concept_id)
        for relationship in concept_relationships:
            quote_identifier(relationship)
            relationships[relationship].add(concept_id)
        for entity, properties in neo4j.get("properties", {}).items():
            quote_identifier(entity)
            is_label = entity in neo4j.get("node_labels", [])
            is_relationship = entity in concept_relationships
            if is_label == is_relationship:
                raise RuntimeError(
                    f"Concept {concept_id!r} property owner {entity!r} must be declared "
                    "as exactly one node label or relationship type"
                )
            destination = relationship_properties if is_relationship else node_properties
            for property_name in properties:
                quote_identifier(property_name)
                destination[(entity, property_name)].add(concept_id)
        for path in neo4j.get("paths", []):
            if path not in SAFE_PATH_PATTERNS:
                raise RuntimeError(f"Unsupported Neo4j path pattern: {path!r}")
            paths[path].add(concept_id)

    return {
        "labels": labels,
        "relationships": relationships,
        "node_properties": node_properties,
        "relationship_properties": relationship_properties,
        "paths": paths,
    }


def cursor_rows(cursor: Any) -> list[dict[str, Any]]:
    """Return Databricks cursor rows as dictionaries."""
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def validate_databricks(mapping: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Validate mapped Databricks assets and return reviewable evidence."""
    fixture_contract = load_fixture_contract()
    catalog = mapping["source_scope"]["databricks_catalog"]
    schema = mapping["source_scope"]["databricks_schema"]
    if catalog != require_env("DATABRICKS_CATALOG") or schema != require_env("DATABRICKS_SCHEMA"):
        raise RuntimeError(
            "The mapping source scope does not match the configured Databricks source"
        )

    info_schema = f"{quote_identifier(catalog)}.information_schema.columns"
    with (
        sql.connect(
            server_hostname=databricks_server_hostname(),
            http_path=databricks_http_path(),
            access_token=databricks_access_token(),
            catalog=catalog,
            schema=schema,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            f"""
                SELECT table_name, column_name, data_type, is_nullable
                FROM {info_schema}
                WHERE table_schema = ?
                """,
            [schema],
        )
        available = {(row["table_name"], row["column_name"]): row for row in cursor_rows(cursor)}

        column_evidence = []
        missing_columns = []
        for asset, concepts in sorted(contract["columns"].items()):
            row = available.get(asset)
            if row is None:
                missing_columns.append(".".join(asset))
                continue
            column_evidence.append(
                {
                    "asset": ".".join(asset),
                    "data_type": row["data_type"],
                    "is_nullable": row["is_nullable"],
                    "concepts": sorted(concepts),
                }
            )
        if missing_columns:
            raise RuntimeError(f"Mapped Databricks columns are missing: {missing_columns}")

        join_evidence = []
        for expression, concepts in sorted(contract["joins"].items()):
            match = JOIN_EXPRESSION.fullmatch(expression)
            if match is None:
                raise RuntimeError(f"Unsupported join expression: {expression!r}")
            left_table = quote_identifier(match["left_table"])
            right_table = quote_identifier(match["right_table"])
            left_column = quote_identifier(match["left_column"])
            right_column = quote_identifier(match["right_column"])
            cursor.execute(
                f"""
                    SELECT 1
                    FROM {quote_identifier(catalog)}.{quote_identifier(schema)}.{left_table} AS lhs
                    INNER JOIN {quote_identifier(catalog)}.{quote_identifier(schema)}.{right_table} AS rhs
                      ON lhs.{left_column} = rhs.{right_column}
                    LIMIT 1
                    """
            )
            join_evidence.append(
                {
                    "expression": expression,
                    "columns_exist": True,
                    "match_exists": cursor.fetchone() is not None,
                    "concepts": sorted(concepts),
                }
            )

        predicate_evidence = []
        for (table, expression), concepts in sorted(contract["predicates"].items()):
            column, operator, value = parse_predicate(expression)
            cursor.execute(
                f"""
                    SELECT 1
                    FROM {quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(table)}
                    WHERE {quote_identifier(column)} {operator} ?
                    LIMIT 1
                """,
                [value],
            )
            predicate_evidence.append(
                {
                    "table": table,
                    "expression": expression,
                    "match_exists": cursor.fetchone() is not None,
                    "concepts": sorted(concepts),
                }
            )

        cursor.execute(
            f"""
                SELECT account_id, identity_cluster_size,
                       shared_phone_count, shared_address_count
                FROM {quote_identifier(catalog)}.{quote_identifier(schema)}.`gold_accounts`
                WHERE identity_cluster_id = ?
                ORDER BY account_id
                """,
            [FIXTURE_CLUSTER_ID],
        )
        fixture_rows = cursor_rows(cursor)

    if not all(item["match_exists"] for item in join_evidence):
        raise RuntimeError("At least one mapped Databricks join has no matching rows")
    if not all(item["match_exists"] for item in predicate_evidence):
        raise RuntimeError("At least one mapped Databricks predicate has no matching rows")
    fixture_observations = validate_fixture_rows(fixture_rows, fixture_contract, "Databricks")

    return {
        "workspace_host": require_env("DATABRICKS_HOST"),
        "catalog": catalog,
        "schema": schema,
        "verified_tables": sorted({table for table, _ in contract["columns"]}),
        "verified_columns": column_evidence,
        "verified_joins": join_evidence,
        "verified_predicates": predicate_evidence,
        "fixture": {
            "identity_cluster_id": FIXTURE_CLUSTER_ID,
            "account_ids": fixture_contract["account_ids"],
            "identity_cluster_size": fixture_contract["identity_cluster_size"],
            "rows_verified": len(fixture_observations),
            "account_observations": fixture_observations,
        },
    }


def operational_neo4j_config(mapping: dict[str, Any]) -> dict[str, str]:
    """Read only the operational Neo4j credentials from the parent project env."""
    if not OPERATIONAL_ENV_FILE.is_file():
        raise RuntimeError(f"Missing operational graph configuration: {OPERATIONAL_ENV_FILE}")
    values = dotenv_values(OPERATIONAL_ENV_FILE, interpolate=False)
    names = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    missing = [name for name in names if not str(values.get(name, "")).strip()]
    if missing:
        raise RuntimeError(f"Missing operational Neo4j settings: {missing}")
    return {
        "uri": str(values["NEO4J_URI"]),
        "username": str(values["NEO4J_USERNAME"]),
        "password": str(values["NEO4J_PASSWORD"]),
        "database": mapping["source_scope"]["neo4j_database"],
    }


def one_record(driver: Any, query: str, database: str) -> dict[str, Any]:
    """Run a Cypher query that must return exactly one record."""
    records, _, _ = driver.execute_query(
        query,
        database_=database,
        routing_=RoutingControl.READ,
    )
    if len(records) != 1:
        raise RuntimeError(f"Expected one Neo4j record, received {len(records)}")
    return records[0].data()


def validate_neo4j(mapping: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Validate mapped operational graph assets and return reviewable evidence."""
    fixture_contract = load_fixture_contract()
    config = operational_neo4j_config(mapping)
    driver = GraphDatabase.driver(config["uri"], auth=(config["username"], config["password"]))
    try:
        driver.verify_connectivity()
        label_evidence = []
        for label, concepts in sorted(contract["labels"].items()):
            row = one_record(
                driver,
                f"CYPHER 25 MATCH (node:{quote_identifier(label)}) RETURN count(node) AS count",
                config["database"],
            )
            count = int(row["count"])
            if count == 0:
                raise RuntimeError(f"Mapped Neo4j label has no nodes: {label}")
            label_evidence.append(
                {"label": label, "node_count": count, "concepts": sorted(concepts)}
            )

        relationship_evidence = []
        for relationship, concepts in sorted(contract["relationships"].items()):
            row = one_record(
                driver,
                f"CYPHER 25 MATCH ()-[relationship:{quote_identifier(relationship)}]->() "
                "RETURN count(relationship) AS count",
                config["database"],
            )
            count = int(row["count"])
            if count == 0:
                raise RuntimeError(
                    f"Mapped Neo4j relationship type has no relationships: {relationship}"
                )
            relationship_evidence.append(
                {
                    "type": relationship,
                    "relationship_count": count,
                    "concepts": sorted(concepts),
                }
            )

        property_evidence = []
        for (label, property_name), concepts in sorted(contract["node_properties"].items()):
            row = one_record(
                driver,
                f"CYPHER 25 MATCH (node:{quote_identifier(label)}) "
                f"RETURN count(node.{quote_identifier(property_name)}) AS populated_count",
                config["database"],
            )
            count = int(row["populated_count"])
            if count == 0:
                raise RuntimeError(
                    f"Mapped Neo4j property is not populated: {label}.{property_name}"
                )
            property_evidence.append(
                {
                    "entity_kind": "node",
                    "entity": label,
                    "property": property_name,
                    "populated_count": count,
                    "concepts": sorted(concepts),
                }
            )

        for (relationship, property_name), concepts in sorted(
            contract["relationship_properties"].items()
        ):
            row = one_record(
                driver,
                f"CYPHER 25 MATCH ()-[relationship:{quote_identifier(relationship)}]->() "
                f"RETURN count(relationship.{quote_identifier(property_name)}) AS populated_count",
                config["database"],
            )
            count = int(row["populated_count"])
            if count == 0:
                raise RuntimeError(
                    f"Mapped Neo4j relationship property is not populated: "
                    f"{relationship}.{property_name}"
                )
            property_evidence.append(
                {
                    "entity_kind": "relationship",
                    "entity": relationship,
                    "property": property_name,
                    "populated_count": count,
                    "concepts": sorted(concepts),
                }
            )

        path_evidence = []
        for pattern, concepts in sorted(contract["paths"].items()):
            row = one_record(
                driver,
                f"CYPHER 25 MATCH {pattern} RETURN count(*) AS match_count",
                config["database"],
            )
            count = int(row["match_count"])
            if count == 0:
                raise RuntimeError(f"Mapped Neo4j path has no matches: {pattern}")
            path_evidence.append(
                {
                    "pattern": pattern,
                    "match_count": count,
                    "concepts": sorted(concepts),
                }
            )

        fixture_records, _, _ = driver.execute_query(
            """CYPHER 25
            MATCH (account:Account)
            WHERE account.identity_cluster_id = $identity_cluster_id
            RETURN account.account_id AS account_id,
                   account.identity_cluster_size AS identity_cluster_size,
                   account.shared_phone_count AS shared_phone_count,
                   account.shared_address_count AS shared_address_count
            ORDER BY account.account_id
            """,
            parameters_={"identity_cluster_id": FIXTURE_CLUSTER_ID},
            database_=config["database"],
            routing_=RoutingControl.READ,
        )
    finally:
        driver.close()

    fixture_observations = validate_fixture_rows(
        [record.data() for record in fixture_records], fixture_contract, "Neo4j"
    )

    return {
        "database": config["database"],
        "verified_node_labels": label_evidence,
        "verified_relationship_types": relationship_evidence,
        "verified_properties": property_evidence,
        "verified_paths": path_evidence,
        "fixture": {
            "identity_cluster_id": FIXTURE_CLUSTER_ID,
            "accounts": len(fixture_observations),
            "account_ids": fixture_contract["account_ids"],
            "identity_cluster_size": fixture_contract["identity_cluster_size"],
            "account_observations": fixture_observations,
        },
        "known_gaps": [
            concept["neo4j"]["known_gap"]
            for concept in mapping["concepts"]
            if "known_gap" in concept["neo4j"]
        ],
    }


def run_gds_validation() -> dict[str, Any]:
    """Run and observe the independent operational GDS/KYC acceptance gate."""
    command = ["uv", "run", "--locked", "python", "validation/verify_gds.py"]
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    completed = subprocess.run(
        command,
        cwd=GDS_WORKING_DIRECTORY,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"GDS/KYC validation exited with status {completed.returncode}")
    result = re.search(
        r"Result:\s+PASS\s+(?P<passed>[0-9]+)/(?P<total>[0-9]+) checks passed", completed.stdout
    )
    if result is None or (int(result["passed"]), int(result["total"])) != (9, 9):
        raise RuntimeError("GDS/KYC validation did not report the expected 9/9 pass")
    return {
        "working_directory": "enrichment-pipeline",
        "command": GDS_COMMAND,
        "script_sha256": file_digest(GDS_SCRIPT),
        "status": "passed",
        "executed_at": datetime.now(UTC).isoformat(),
        "checks_passed": 9,
        "checks_total": 9,
    }


def required_evidence_keys(mapping: dict[str, Any]) -> dict[str, set[Any]]:
    """Return normalized mapping keys used by the committed-evidence contract test."""
    databricks = collect_databricks_contract(mapping)
    neo4j = collect_neo4j_contract(mapping)
    return {
        "databricks_columns": set(databricks["columns"]),
        "databricks_joins": set(databricks["joins"]),
        "databricks_predicates": set(databricks["predicates"]),
        "neo4j_labels": set(neo4j["labels"]),
        "neo4j_relationships": set(neo4j["relationships"]),
        "neo4j_node_properties": set(neo4j["node_properties"]),
        "neo4j_relationship_properties": set(neo4j["relationship_properties"]),
        "neo4j_paths": set(neo4j["paths"]),
    }


def recorded_evidence_key_lists(evidence: dict[str, Any]) -> dict[str, list[Any]]:
    """Return normalized key lists contained in the source-mapping evidence."""
    properties = evidence["neo4j"]["verified_properties"]
    return {
        "databricks_columns": [
            tuple(item["asset"].split(".", maxsplit=1))
            for item in evidence["databricks"]["verified_columns"]
        ],
        "databricks_joins": [
            item["expression"] for item in evidence["databricks"]["verified_joins"]
        ],
        "databricks_predicates": [
            (item["table"], item["expression"])
            for item in evidence["databricks"]["verified_predicates"]
        ],
        "neo4j_labels": [item["label"] for item in evidence["neo4j"]["verified_node_labels"]],
        "neo4j_relationships": [
            item["type"] for item in evidence["neo4j"]["verified_relationship_types"]
        ],
        "neo4j_node_properties": [
            (item["entity"], item["property"])
            for item in properties
            if item["entity_kind"] == "node"
        ],
        "neo4j_relationship_properties": [
            (item["entity"], item["property"])
            for item in properties
            if item["entity_kind"] == "relationship"
        ],
        "neo4j_paths": [item["pattern"] for item in evidence["neo4j"]["verified_paths"]],
    }


def recorded_evidence_keys(evidence: dict[str, Any]) -> dict[str, set[Any]]:
    """Return normalized key sets contained in the source-mapping evidence."""
    return {
        section: set(values) for section, values in recorded_evidence_key_lists(evidence).items()
    }


def validate_evidence_coverage(mapping: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Require the evidence artifact to cover every claim in the mapping artifact."""
    if evidence.get("validation") != "source_mappings" or evidence.get("status") != "complete":
        raise RuntimeError("Source-mapping evidence must have complete status")
    source_scope = mapping["source_scope"]
    evidence_scope = (
        evidence["databricks"]["catalog"],
        evidence["databricks"]["schema"],
        evidence["neo4j"]["database"],
    )
    mapping_scope = (
        source_scope["databricks_catalog"],
        source_scope["databricks_schema"],
        source_scope["neo4j_database"],
    )
    if evidence_scope != mapping_scope:
        raise RuntimeError(
            f"The source scope in source-mapping evidence {evidence_scope} "
            f"does not match {mapping_scope}"
        )
    contract = evidence["mapping_contract"]
    if contract["concepts_verified"] != len(mapping["concepts"]):
        raise RuntimeError("Source-mapping evidence concept count does not match the mapping")
    if contract["primary_concept"] != mapping["primary_concept"]:
        raise RuntimeError("Source-mapping evidence primary concept does not match the mapping")

    observed_checks = {
        "Databricks columns": all(
            item.get("data_type") in SUPPORTED_DATABRICKS_TYPES
            and item.get("is_nullable") in {"YES", "NO"}
            for item in evidence["databricks"]["verified_columns"]
        ),
        "Databricks joins": all(
            item.get("columns_exist") is True and item.get("match_exists") is True
            for item in evidence["databricks"]["verified_joins"]
        ),
        "Databricks predicates": all(
            item.get("match_exists") is True
            for item in evidence["databricks"]["verified_predicates"]
        ),
        "Neo4j labels": all(
            item.get("node_count", 0) > 0 for item in evidence["neo4j"]["verified_node_labels"]
        ),
        "Neo4j relationships": all(
            item.get("relationship_count", 0) > 0
            for item in evidence["neo4j"]["verified_relationship_types"]
        ),
        "Neo4j properties": all(
            item.get("populated_count", 0) > 0 for item in evidence["neo4j"]["verified_properties"]
        ),
        "Neo4j paths": all(
            item.get("match_count", 0) > 0 for item in evidence["neo4j"]["verified_paths"]
        ),
    }
    failed_checks = [name for name, passed in observed_checks.items() if not passed]
    if failed_checks:
        raise RuntimeError(f"Source-mapping evidence contains failed observations: {failed_checks}")

    node_counts = {
        item["label"]: item["node_count"] for item in evidence["neo4j"]["verified_node_labels"]
    }
    relationship_counts = {
        item["type"]: item["relationship_count"]
        for item in evidence["neo4j"]["verified_relationship_types"]
    }
    inconsistent_properties = [
        f"{item['entity']}.{item['property']}"
        for item in evidence["neo4j"]["verified_properties"]
        if item["populated_count"]
        > (
            node_counts[item["entity"]]
            if item["entity_kind"] == "node"
            else relationship_counts[item["entity"]]
        )
    ]
    if inconsistent_properties:
        raise RuntimeError(
            "Source-mapping evidence property counts exceed their entity counts: "
            f"{inconsistent_properties}"
        )

    fixture_contract = load_fixture_contract()
    databricks_fixture = evidence["databricks"]["fixture"]
    neo4j_fixture = evidence["neo4j"]["fixture"]
    expected_ids = fixture_contract["account_ids"]
    fixture_checks = {
        "Databricks account IDs": databricks_fixture.get("account_ids") == expected_ids,
        "Neo4j account IDs": neo4j_fixture.get("account_ids") == expected_ids,
        "cross-source account IDs": databricks_fixture.get("account_ids")
        == neo4j_fixture.get("account_ids"),
        "Databricks cluster size": databricks_fixture.get("identity_cluster_size")
        == fixture_contract["identity_cluster_size"],
        "Neo4j cluster size": neo4j_fixture.get("identity_cluster_size")
        == fixture_contract["identity_cluster_size"],
        "Databricks fixture rows": databricks_fixture.get("rows_verified") == len(expected_ids),
        "Neo4j fixture rows": neo4j_fixture.get("accounts") == len(expected_ids),
        "fixture observations": databricks_fixture.get("account_observations")
        == neo4j_fixture.get("account_observations"),
    }
    expected_observations = [
        {
            "account_id": account_id,
            "identity_cluster_size": fixture_contract["identity_cluster_size"],
            "shared_phone_count": fixture_contract["shared_phone_count"][account_id],
            "shared_address_count": fixture_contract["shared_address_count"][account_id],
        }
        for account_id in expected_ids
    ]
    fixture_checks["ground-truth observations"] = (
        databricks_fixture.get("account_observations") == expected_observations
    )
    failed_fixture_checks = [name for name, passed in fixture_checks.items() if not passed]
    if failed_fixture_checks:
        raise RuntimeError(
            f"Source-mapping evidence contains invalid fixture data: {failed_fixture_checks}"
        )

    gds = evidence["neo4j"]["existing_validation"]
    recorded_at = datetime.fromisoformat(evidence["recorded_at"])
    gds_executed_at = datetime.fromisoformat(gds["executed_at"])
    elapsed = recorded_at - gds_executed_at
    if (
        gds.get("status") != "passed"
        or gds.get("working_directory") != "enrichment-pipeline"
        or gds.get("command") != GDS_COMMAND
        or gds.get("script_sha256") != file_digest(GDS_SCRIPT)
        or gds.get("checks_passed") != 9
        or gds.get("checks_total") != 9
        or recorded_at.utcoffset() != timedelta(0)
        or gds_executed_at.utcoffset() != timedelta(0)
        or elapsed < timedelta(0)
        or elapsed > timedelta(minutes=15)
        or evidence["evidence_date"] != recorded_at.date().isoformat()
    ):
        raise RuntimeError("Source-mapping evidence contains an invalid GDS/KYC attestation")

    required = required_evidence_keys(mapping)
    recorded_lists = recorded_evidence_key_lists(evidence)
    recorded = recorded_evidence_keys(evidence)
    duplicates = {
        section: len(values) - len(set(values))
        for section, values in recorded_lists.items()
        if len(values) != len(set(values))
    }
    if duplicates:
        raise RuntimeError(f"Source-mapping evidence contains duplicate claims: {duplicates}")
    differences = {
        section: {
            "missing": sorted(expected.difference(recorded[section])),
            "unexpected": sorted(recorded[section].difference(expected)),
        }
        for section, expected in required.items()
        if expected != recorded[section]
    }
    if differences:
        raise RuntimeError(
            f"Source-mapping evidence does not exactly match the mapping contract: {differences}"
        )
    if evidence["mapping_contract"]["mapping_sha256"] != mapping_digest():
        raise RuntimeError("Source-mapping evidence uses a different mapping revision")


def build_evidence(
    mapping: dict[str, Any],
    databricks: dict[str, Any],
    neo4j: dict[str, Any],
    gds_validation: dict[str, Any],
) -> dict[str, Any]:
    """Build the versioned source-mapping evidence artifact."""
    recorded_at = datetime.now(UTC)
    return {
        "validation": "source_mappings",
        "status": "complete",
        "evidence_version": 2,
        "evidence_date": recorded_at.date().isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "databricks": databricks,
        "neo4j": {
            **neo4j,
            "existing_validation": gds_validation,
        },
        "mapping_contract": {
            "concepts_verified": len(mapping["concepts"]),
            "primary_concept": mapping["primary_concept"],
            "artifact": "../mappings/semantic-mappings.json",
            "mapping_sha256": mapping_digest(),
            "graph_asset_decision": "../mappings/graph-asset-representation.json",
            "validation_command": "uv run finance-semantic-validate-sources",
            "record_command": "make record-sources",
        },
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help=f"replace {EVIDENCE_FILE.relative_to(DEMO_DIR)} after validation passes",
    )
    return parser.parse_args()


def main() -> None:
    """Validate both live sources and print or persist the resulting evidence."""
    args = parse_args()
    mapping = load_json(MAPPING_FILE)
    gds_validation = run_gds_validation()
    load_demo_env()
    databricks_contract = collect_databricks_contract(mapping)
    neo4j_contract = collect_neo4j_contract(mapping)
    databricks_evidence = validate_databricks(mapping, databricks_contract)
    neo4j_evidence = validate_neo4j(mapping, neo4j_contract)
    if (
        databricks_evidence["fixture"]["account_observations"]
        != neo4j_evidence["fixture"]["account_observations"]
    ):
        raise RuntimeError("Databricks and Neo4j shared-identity fixture values differ")
    evidence = build_evidence(mapping, databricks_evidence, neo4j_evidence, gds_validation)
    validate_evidence_coverage(mapping, evidence)

    if args.write_evidence:
        EVIDENCE_FILE.write_text(
            json.dumps(evidence, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": "passed", "evidence": str(EVIDENCE_FILE)}, indent=2))
    else:
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()

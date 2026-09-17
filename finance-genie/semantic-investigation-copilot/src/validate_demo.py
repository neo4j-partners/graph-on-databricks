"""Execute fixed source checks and validate the shared-identity fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from databricks import sql
from neo4j import GraphDatabase, RoutingControl

from config import DEMO_DIR, databricks_http_path, databricks_server_hostname, load_demo_env
from demo_trace import (
    DEFAULT_EVIDENCE,
    build_demo_trace,
    load_json,
    retrieve_live_context,
    validate_fixture_results,
)
from ingest import databricks_access_token
from validate_sources import cursor_rows, operational_neo4j_config

EVIDENCE_FILE = DEMO_DIR / "validation" / "shared-identity-source-validation.json"


def execute_lakehouse_check(check: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Execute the fixed read-only Databricks query from the demo trace."""
    statement = check["text"].replace(":identity_cluster_id", "?")
    cluster_id = check["parameters"]["identity_cluster_id"]
    with (
        sql.connect(
            server_hostname=databricks_server_hostname(),
            http_path=databricks_http_path(),
            access_token=databricks_access_token(),
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(statement, [cluster_id])
        return cursor_rows(cursor)


def execute_graph_check(check: Mapping[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute the fixed read-only Cypher query against the operational graph."""
    config = operational_neo4j_config(mapping)
    driver = GraphDatabase.driver(
        config["uri"],
        auth=(config["username"], config["password"]),
    )
    try:
        records, _, _ = driver.execute_query(
            check["text"],
            parameters_=check["parameters"],
            database_=config["database"],
            routing_=RoutingControl.READ,
        )
        return [record.data() for record in records]
    finally:
        driver.close()


def validate(*, write_evidence: bool = False) -> dict[str, Any]:
    """Run semantic retrieval and both prepared source checks."""
    load_demo_env()
    mapping = load_json(DEMO_DIR / "mappings" / "semantic-mappings.json")
    source_evidence = load_json(DEFAULT_EVIDENCE)
    context = asyncio.run(retrieve_live_context("shared identity"))
    trace = build_demo_trace(context, source_evidence)
    checks = trace["prepared_source_checks"]

    lakehouse_rows = execute_lakehouse_check(checks["databricks"])
    graph_rows = execute_graph_check(checks["neo4j"], mapping)
    validate_fixture_results(lakehouse_rows, graph_rows, trace["source_evidence"])

    result = {
        "validation": "shared_identity_sources",
        "status": "complete",
        "evidence_date": datetime.now(UTC).date().isoformat(),
        "recorded_at": datetime.now(UTC).isoformat(),
        "phrase": "shared identity",
        "retrieval_mode": trace["retrieval"]["mode"],
        "selected_concept": trace["term"]["concept_id"],
        "identity_cluster_id": trace["source_evidence"]["identity_cluster_id"],
        "account_ids": trace["source_evidence"]["account_ids"],
        "databricks_rows": len(lakehouse_rows),
        "neo4j_rows": len(graph_rows),
        "prepared_queries_executed": True,
        "generated_query_execution": False,
        "custom_application": False,
        "synthetic_data": True,
        "validation_command": "uv run finance-semantic-validate-demo",
    }
    if write_evidence:
        EVIDENCE_FILE.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    """Validate the shared-identity source checks and print JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    print(json.dumps(validate(write_evidence=args.write_evidence), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

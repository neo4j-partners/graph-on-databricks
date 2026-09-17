"""Unit tests for the prepared-only shared-identity demo trace."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from demo_trace import (
    DemoContractError,
    adapt_mapping_artifact,
    build_demo_trace,
    prepare_graph_query,
    prepare_lakehouse_query,
    retrieve_demo_trace,
    validate_fixture_results,
)

ROOT = Path(__file__).parents[1]
MAPPINGS = ROOT / "mappings" / "semantic-mappings.json"
EVIDENCE = ROOT / "validation" / "source-mapping-validation.json"
EXPECTED_ACCOUNTS = [368, 927, 1033, 1696, 2184, 2216, 2612, 3003]
WRITE_KEYWORDS = {"CREATE", "DELETE", "DROP", "INSERT", "LOAD", "MERGE", "SET", "UPDATE"}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture
def response() -> dict:
    return adapt_mapping_artifact(load(MAPPINGS))


@pytest.fixture
def evidence() -> dict:
    return load(EVIDENCE)


def test_build_trace_is_deterministic_and_complete(response: dict, evidence: dict) -> None:
    first = build_demo_trace(response, evidence)
    second = build_demo_trace(response, evidence)

    assert first == second
    assert first["term"] == {
        "concept_id": "shared_identity",
        "name": "Shared identity",
        "definition": (
            "Customers connected into one identity cluster through a shared phone "
            "number or mailing address."
        ),
        "interpretation": "An investigation signal, not a determination of fraud.",
    }
    assert first["mappings"]["databricks"]["tables"] == [
        "graph-on-databricks.graph-enriched-schema.gold_accounts"
    ]
    assert "Customer" in first["mappings"]["neo4j"]["node_labels"]
    assert first["source_evidence"]["account_ids"] == EXPECTED_ACCOUNTS
    assert first["source_evidence"]["identity_cluster_id"] == 367
    assert first["source_evidence"]["identity_cluster_size"] == 8
    assert first["request"]["query_execution"] == "not_performed"


def test_offline_mapping_uses_the_live_retrieval_contract(response: dict) -> None:
    databricks = response["matches"][0]["databricks"]

    assert databricks["join_keys"] == [
        (
            "graph-on-databricks.graph-enriched-schema.gold_accounts.account_id = "
            "graph-on-databricks.graph-enriched-schema.account_links.dst_account_id"
        ),
        (
            "graph-on-databricks.graph-enriched-schema.gold_accounts.account_id = "
            "graph-on-databricks.graph-enriched-schema.account_links.src_account_id"
        ),
        (
            "graph-on-databricks.graph-enriched-schema.gold_accounts.account_id = "
            "graph-on-databricks.graph-enriched-schema.accounts.account_id"
        ),
    ]
    assert databricks["predicates"] == [
        "graph-on-databricks.graph-enriched-schema.gold_accounts.identity_cluster_size > 1"
    ]


def test_offline_mapping_rejects_contract_drift() -> None:
    mapping = load(MAPPINGS)
    changed = copy.deepcopy(mapping)
    changed["concepts"][0]["databricks"]["source_rows"] = [{"account_id": 368}]

    with pytest.raises(DemoContractError, match="Invalid semantic mapping artifact"):
        adapt_mapping_artifact(changed)


def test_prepared_queries_are_parameterized_and_read_only(response: dict, evidence: dict) -> None:
    concept = response["matches"][0]
    sql = prepare_lakehouse_query(concept["databricks"], 367)
    cypher = prepare_graph_query(concept["neo4j"], 367)

    assert sql["parameters"] == {"identity_cluster_id": 367}
    assert ":identity_cluster_id" in sql["text"]
    assert "367" not in sql["text"]
    assert sql["text"].lstrip().startswith("SELECT")
    assert cypher["parameters"] == {"identity_cluster_id": 367}
    assert "$identity_cluster_id" in cypher["text"]
    assert "367" not in cypher["text"]
    assert cypher["text"].lstrip().startswith("CYPHER 25\nMATCH")
    for query in (sql, cypher):
        assert query["read_only"] is True
        words = set(query["text"].upper().replace("(", " ").split())
        assert not WRITE_KEYWORDS & words


def test_queries_require_the_returned_verified_mappings(response: dict) -> None:
    lakehouse = dict(response["matches"][0]["databricks"])
    lakehouse["tables"] = ["malicious.other.table"]
    with pytest.raises(DemoContractError, match="gold_accounts"):
        prepare_lakehouse_query(lakehouse, 367)

    graph = dict(response["matches"][0]["neo4j"])
    graph["relationship_types"] = ["OWNS"]
    with pytest.raises(DemoContractError, match="relationships"):
        prepare_graph_query(graph, 367)


def test_accepts_catalog_qualified_retrieval_predicate(response: dict) -> None:
    lakehouse = response["matches"][0]["databricks"]
    lakehouse["predicates"] = [
        "graph-on-databricks.graph-enriched-schema.gold_accounts.identity_cluster_size > 1"
    ]

    query = prepare_lakehouse_query(lakehouse, 367)

    assert query["parameters"] == {"identity_cluster_id": 367}


def test_fixture_validation_accepts_both_known_source_results(evidence: dict) -> None:
    trace = build_demo_trace(load(MAPPINGS), evidence)
    rows = [
        {
            **row,
            "identity_cluster_id": trace["source_evidence"]["identity_cluster_id"],
        }
        for row in trace["source_evidence"]["databricks"]["account_observations"]
    ]

    validate_fixture_results(rows, rows, trace["source_evidence"])


def test_fixture_validation_rejects_incomplete_source_results(evidence: dict) -> None:
    trace = build_demo_trace(load(MAPPINGS), evidence)
    rows = [
        {
            **row,
            "identity_cluster_id": trace["source_evidence"]["identity_cluster_id"],
        }
        for row in trace["source_evidence"]["databricks"]["account_observations"]
    ]

    with pytest.raises(DemoContractError, match="Neo4j"):
        validate_fixture_results(rows, rows[:-1], trace["source_evidence"])


def test_retrieval_is_injectable_for_async_adapter(response: dict, evidence: dict) -> None:
    phrases: list[str] = []

    async def retrieve(phrase: str) -> dict:
        phrases.append(phrase)
        return response

    trace = asyncio.run(retrieve_demo_trace(retrieve, evidence))

    assert phrases == ["shared identity"]
    assert trace["retrieval"]["selected_match_rank"] == 1
    assert trace["term"]["concept_id"] == "shared_identity"


def test_top_retrieval_match_must_be_shared_identity(response: dict, evidence: dict) -> None:
    response["matches"][0]["concept_id"] = "high_risk"

    with pytest.raises(DemoContractError, match="Top semantic match"):
        build_demo_trace(response, evidence)

"""Tests for metadata-only business-concept retrieval."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from business_context import (
    BUSINESS_TERM_VECTOR_INDEX,
    LEXICAL_SEARCH_CYPHER,
    VECTOR_SEARCH_CYPHER,
    get_business_concept_context,
    register,
)


def concept(
    concept_id: str = "shared_identity",
    *,
    score: float = 0.94,
    databricks: dict[str, Any] | None = None,
    neo4j: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one semantic-store result row."""
    databricks = databricks or {
        "table": "gold_accounts",
        "columns": ["identity_cluster_size", "account_id"],
        "predicate": "identity_cluster_size > 1",
        "join_keys": ["gold_accounts.account_id = accounts.account_id"],
    }
    neo4j = neo4j or {
        "node_labels": ["Phone", "Customer", "Account"],
        "relationship_types": ["OWNS", "HAS_PHONE"],
        "properties": {
            "Customer": ["identity_cluster_size", "customer_id"],
            "Account": ["account_id"],
        },
        "paths": [
            "(:Customer)-[:HAS_PHONE]->(:Phone)<-[:HAS_PHONE]-(:Customer)",
            "(:Customer)-[:OWNS]->(:Account)",
        ],
    }
    return {
        "concept": {
            "id": concept_id,
            "name": concept_id.replace("_", " ").title(),
            "definition": "Customers connected through a shared identifier.",
            "interpretation": "An investigation signal, not a fraud determination.",
            "source_catalog": "graph-on-databricks",
            "source_schema": "graph-enriched-schema",
            "databricks_mapping": json.dumps(databricks),
            "neo4j_mapping": json.dumps(neo4j),
        },
        "score": score,
    }


class StubDriver:
    """Async-driver stub that records queries and returns per-mode rows."""

    def __init__(
        self,
        *,
        vector_rows: list[dict[str, Any]] | None = None,
        lexical_rows: list[dict[str, Any]] | None = None,
        vector_error: Exception | None = None,
    ) -> None:
        self.vector_rows = vector_rows or []
        self.lexical_rows = lexical_rows or []
        self.vector_error = vector_error
        self.calls: list[dict[str, Any]] = []

    async def execute_query(self, query_: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"query": query_, **kwargs})
        if query_ == VECTOR_SEARCH_CYPHER:
            if self.vector_error:
                raise self.vector_error
            return self.vector_rows
        if query_ == LEXICAL_SEARCH_CYPHER:
            return self.lexical_rows
        raise AssertionError("unexpected query")


class StubEmbedder:
    """Embedding-provider stub."""

    def __init__(self, vector: list[float] | None = None, error: Exception | None = None) -> None:
        self.vector = vector or [0.1, 0.2, 0.3]
        self.error = error
        self.calls: list[str] = []

    async def _create_embedding_async(self, text_content: str) -> list[float]:
        self.calls.append(text_content)
        if self.error:
            raise self.error
        return self.vector


class StubServer:
    """FastMCP registration stub that captures decorated tools."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(function: Any) -> Any:
            self.tools[function.__name__] = function
            return function

        return decorator


def test_prefers_vector_search_and_returns_qualified_json_context() -> None:
    driver = StubDriver(vector_rows=[concept()])
    embedder = StubEmbedder()

    result = asyncio.run(
        get_business_concept_context(
            "shared identity",
            driver,
            "neo4j",
            embedder,
        )
    )

    assert result["retrieval_mode"] == "vector"
    assert embedder.calls == ["shared identity"]
    assert len(driver.calls) == 1
    parameters = driver.calls[0]["parameters_"]
    assert BUSINESS_TERM_VECTOR_INDEX in driver.calls[0]["query"]
    assert parameters["embedding"] == [0.1, 0.2, 0.3]
    match = result["matches"][0]
    assert match["databricks"]["tables"] == [
        "graph-on-databricks.graph-enriched-schema.gold_accounts"
    ]
    assert match["databricks"]["columns"] == [
        "graph-on-databricks.graph-enriched-schema.gold_accounts.account_id",
        "graph-on-databricks.graph-enriched-schema.gold_accounts.identity_cluster_size",
    ]
    assert match["databricks"]["join_keys"] == [
        (
            "graph-on-databricks.graph-enriched-schema.gold_accounts.account_id = "
            "graph-on-databricks.graph-enriched-schema.accounts.account_id"
        )
    ]
    assert match["databricks"]["predicates"] == [
        "graph-on-databricks.graph-enriched-schema.gold_accounts.identity_cluster_size > 1"
    ]
    assert match["neo4j"]["node_labels"] == ["Account", "Customer", "Phone"]
    json.dumps(result)


def test_lexical_search_is_parameterized_and_does_not_query_source_data() -> None:
    malicious_phrase = "shared identity' MATCH (n) DETACH DELETE n //"
    driver = StubDriver(lexical_rows=[concept()])

    result = asyncio.run(get_business_concept_context(malicious_phrase, driver, "neo4j"))

    assert result["retrieval_mode"] == "lexical"
    call = driver.calls[0]
    assert malicious_phrase not in call["query"]
    assert call["parameters_"]["tokens"] == [
        "delete",
        "detach",
        "identity",
        "match",
        "n",
        "shared",
    ]
    assert "BusinessConcept" in call["query"]
    assert "Customer" not in call["query"]
    assert "Account" not in call["query"]


@pytest.mark.parametrize(
    "embedder,vector_error",
    [
        (StubEmbedder(error=RuntimeError("endpoint unavailable")), None),
        (StubEmbedder(), RuntimeError("index unavailable")),
    ],
)
def test_embedding_or_vector_failure_falls_back_to_lexical(
    embedder: StubEmbedder,
    vector_error: Exception | None,
) -> None:
    driver = StubDriver(lexical_rows=[concept()], vector_error=vector_error)

    result = asyncio.run(
        get_business_concept_context(
            "shared identity",
            driver,
            "neo4j",
            embedder,
        )
    )

    assert result["retrieval_mode"] == "lexical"
    assert driver.calls[-1]["query"] == LEXICAL_SEARCH_CYPHER


def test_empty_vector_results_fall_back_to_lexical() -> None:
    driver = StubDriver(lexical_rows=[concept()])

    result = asyncio.run(
        get_business_concept_context(
            "shared identity",
            driver,
            "neo4j",
            StubEmbedder(),
        )
    )

    assert result["retrieval_mode"] == "lexical"
    assert [call["query"] for call in driver.calls] == [
        VECTOR_SEARCH_CYPHER,
        LEXICAL_SEARCH_CYPHER,
    ]


def test_results_are_sorted_deterministically() -> None:
    driver = StubDriver(
        lexical_rows=[
            concept("transfer_exposure", score=0.5),
            concept("fraud_ring_candidate", score=0.8),
            concept("shared_identity", score=0.8),
        ]
    )

    result = asyncio.run(get_business_concept_context("risk", driver, "neo4j", max_results=2))

    assert [item["concept_id"] for item in result["matches"]] == [
        "fraud_ring_candidate",
        "shared_identity",
    ]


def test_multiple_tables_and_known_gap_are_preserved() -> None:
    databricks = {
        "tables": ["gold_fraud_ring_communities", "gold_accounts"],
        "columns": [
            "gold_accounts.community_id",
            "gold_fraud_ring_communities.is_ring_candidate",
        ],
        "join_keys": ["gold_accounts.community_id = gold_fraud_ring_communities.community_id"],
    }
    neo4j = {
        "node_labels": ["Account"],
        "relationship_types": ["SIMILAR_TO"],
        "properties": {"Account": ["community_id"]},
        "paths": ["(:Account)-[:SIMILAR_TO]-(:Account)"],
        "known_gap": "Classification metadata is lakehouse-derived.",
    }
    driver = StubDriver(
        lexical_rows=[concept("fraud_ring_candidate", databricks=databricks, neo4j=neo4j)]
    )

    result = asyncio.run(get_business_concept_context("fraud ring", driver, "neo4j"))

    match = result["matches"][0]
    assert match["databricks"]["tables"] == [
        "graph-on-databricks.graph-enriched-schema.gold_accounts",
        "graph-on-databricks.graph-enriched-schema.gold_fraud_ring_communities",
    ]
    assert match["neo4j"]["known_gap"] == "Classification metadata is lakehouse-derived."


@pytest.mark.parametrize(
    ("text_content", "max_results", "message"),
    [
        ("", 5, "non-empty"),
        ("x" * 501, 5, "at most 500"),
        ("shared identity", 0, "between 1 and 20"),
        ("shared identity", True, "must be an integer"),
    ],
)
def test_rejects_invalid_inputs(
    text_content: str,
    max_results: int,
    message: str,
) -> None:
    error_type = TypeError if isinstance(max_results, bool) else ValueError
    with pytest.raises(error_type, match=message):
        asyncio.run(
            get_business_concept_context(
                text_content,
                StubDriver(),
                "neo4j",
                max_results=max_results,
            )
        )


def test_invalid_mapping_json_surfaces_store_corruption() -> None:
    row = concept()
    row["concept"]["databricks_mapping"] = "not-json"
    driver = StubDriver(lexical_rows=[row])

    with pytest.raises(ValueError, match="databricks_mapping is not valid JSON"):
        asyncio.run(get_business_concept_context("shared identity", driver, "neo4j"))


def test_register_exposes_the_expected_mcp_tool() -> None:
    server = StubServer()
    driver = StubDriver(lexical_rows=[concept()])

    register(server, driver, "neo4j")
    result = asyncio.run(server.tools["get_business_concept_context"]("shared identity", 1))

    assert result["matches"][0]["concept_id"] == "shared_identity"
    assert result["retrieval_mode"] == "lexical"

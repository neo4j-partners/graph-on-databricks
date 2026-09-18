"""Tests for the semantic-map-to-Databricks CLI workflow."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest

import query_semantic_map
from mcp_retrieval import RetrievalTrace, ToolCall


def retrieval_trace(
    *,
    tables: tuple[str, ...] = ("gold_accounts",),
    columns: tuple[str, ...] = ("identity_cluster_id",),
) -> RetrievalTrace:
    """Build a compact hybrid retrieval trace for CLI rendering tests."""
    return RetrievalTrace(
        table_search=ToolCall(
            tool_name="get_context_by_table_hybrid_search",
            arguments={},
            result=[],
            names=tables,
        ),
        column_search=ToolCall(
            tool_name="get_context_by_column_hybrid_search",
            arguments={},
            result=[],
            names=columns,
        ),
        schema_context=ToolCall(
            tool_name="get_neo4j_schema_context",
            arguments={},
            result={},
            names=("Account", "TRANSFERRED_TO"),
        ),
    )


def test_retrieved_names_include_columns_embedded_in_table_search() -> None:
    trace = RetrievalTrace(
        table_search=ToolCall(
            tool_name="get_context_by_table_full_text_search",
            arguments={},
            result=[
                {
                    "table_name": "gold_accounts",
                    "columns": [
                        {"column_name": "account_id"},
                        {"column_name": "is_ring_community"},
                    ],
                }
            ],
            names=("gold_accounts",),
        ),
        column_search=ToolCall(
            tool_name="get_context_by_column_full_text_search",
            arguments={},
            result=[],
            names=(),
        ),
        schema_context=ToolCall(
            tool_name="get_neo4j_schema_context",
            arguments={},
            result={},
            names=("Account",),
        ),
    )

    assert trace.retrieved_names() == {
        "gold_accounts",
        "account_id",
        "is_ring_community",
        "Account",
    }


def test_mcp_startup_instructions_name_the_persistent_server_command() -> None:
    from mcp_retrieval import mcp_startup_instructions

    message = mcp_startup_instructions("http://127.0.0.1:8000/mcp")

    assert "NeoCarta MCP is unavailable" in message
    assert "make mcp" in message
    assert "separate terminal" in message


def test_require_grounded_identifiers_accepts_retrieved_names() -> None:
    rows = query_semantic_map.require_grounded_identifiers(
        [
            ("gold_accounts", "table_search"),
            ("risk_score", "column_search"),
        ],
        {"gold_accounts", "risk_score"},
    )

    assert [row.retrieved for row in rows] == [True, True]


def test_require_grounded_identifiers_rejects_unknown_names() -> None:
    with pytest.raises(RuntimeError, match="invented_column"):
        query_semantic_map.require_grounded_identifiers(
            [("invented_column", "column_search")],
            {"risk_score"},
        )


def test_execute_sql_polls_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[dict[str, Any]] = [
        {"statement_id": "statement-1", "status": {"state": "PENDING"}},
        {
            "statement_id": "statement-1",
            "status": {"state": "SUCCEEDED"},
            "manifest": {"schema": {"columns": []}},
            "result": {"data_array": []},
        },
    ]
    calls: list[tuple[str, str, str, dict[str, Any] | None]] = []

    def fake_api(
        method: str,
        path: str,
        *,
        profile: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls.append((method, path, profile, payload))
        return responses.pop(0)

    monkeypatch.setattr(query_semantic_map, "databricks_api", fake_api)
    monkeypatch.setattr(query_semantic_map.time, "sleep", lambda _: None)

    response = query_semantic_map.execute_sql(
        "SELECT 1",
        profile="demo",
        warehouse_id="warehouse-1",
        catalog="catalog-1",
        schema="schema-1",
    )

    assert response["status"]["state"] == "SUCCEEDED"
    assert calls[0][0:3] == (
        "post",
        "/api/2.0/sql/statements",
        "demo",
    )
    assert calls[0][3] == {
        "warehouse_id": "warehouse-1",
        "catalog": "catalog-1",
        "schema": "schema-1",
        "statement": "SELECT 1",
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
        "row_limit": 10,
        "byte_limit": 1_000_000,
        "wait_timeout": "50s",
        "on_wait_timeout": "CONTINUE",
    }
    assert calls[1] == (
        "get",
        "/api/2.0/sql/statements/statement-1",
        "demo",
        None,
    )


def test_result_rows_names_inline_values() -> None:
    response = {
        "manifest": {
            "schema": {
                "columns": [
                    {"name": "account_id"},
                    {"name": "risk_score"},
                ]
            }
        },
        "result": {"data_array": [["8842", "3.42"]]},
    }

    assert query_semantic_map.result_rows(response) == [
        {"account_id": "8842", "risk_score": "3.42"}
    ]


def test_result_rows_rejects_schema_mismatch() -> None:
    response = {
        "manifest": {"schema": {"columns": [{"name": "account_id"}]}},
        "result": {"data_array": [["8842", "extra-value"]]},
    }

    with pytest.raises(RuntimeError, match="did not match"):
        query_semantic_map.result_rows(response)


def test_configure_databricks_profile_uses_one_authentication_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABRICKS_TOKEN", "direct-token")

    profile = query_semantic_map.configure_databricks_profile("demo-profile")

    assert profile == "demo-profile"
    assert query_semantic_map.os.environ["DATABRICKS_PROFILE"] == "demo-profile"
    assert query_semantic_map.os.environ["DATABRICKS_CONFIG_PROFILE"] == "demo-profile"
    assert "DATABRICKS_TOKEN" not in query_semantic_map.os.environ


def test_console_always_colors_section_headings() -> None:
    stream = StringIO()
    console = query_semantic_map.Console(stream=stream)

    console.section(2, "Running semantic retrieval tests")

    rendered = stream.getvalue()
    assert "\033[1;36m" in rendered
    assert "2. Running semantic retrieval tests" in rendered
    assert rendered.endswith("\033[0m\n")


def test_search_strategy_names_hybrid_components() -> None:
    assert (
        query_semantic_map.search_strategy("get_context_by_table_hybrid_search")
        == "hybrid (vector + full-text)"
    )
    assert (
        query_semantic_map.search_strategy("get_context_by_column_full_text_search") == "full-text"
    )


def test_showcase_runs_literal_conceptual_and_hybrid_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions: list[str] = []

    def fake_retrieval(
        question: str,
        catalog: str,
        schema: str,
        *,
        mcp_url: str,
    ) -> RetrievalTrace:
        questions.append(question)
        assert catalog == "catalog"
        assert schema == "schema"
        assert mcp_url == "http://mcp.test/mcp"
        return retrieval_trace()

    monkeypatch.setattr(query_semantic_map, "run_retrieval", fake_retrieval)
    stream = StringIO()

    next_section = query_semantic_map.run_semantic_showcase(
        catalog="catalog",
        schema="schema",
        mcp_url="http://mcp.test/mcp",
        console=query_semantic_map.Console(stream=stream),
        section_number=1,
    )

    assert questions == [case.query for case in query_semantic_map.SHOWCASE_CASES]
    assert next_section == 3
    rendered = stream.getvalue()
    assert rendered.count("PASS") == 3
    assert "\033[1;32m" in rendered
    assert "full-text signal inside hybrid search" in rendered
    assert "vector similarity signal inside hybrid search" in rendered
    assert "hybrid fusion" in rendered

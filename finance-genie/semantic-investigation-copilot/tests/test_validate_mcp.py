"""Tests for catalog-qualified MCP validation helpers."""

from __future__ import annotations

import pytest

from validate_mcp import records_for_source, select_search_tool


def test_records_for_source_requires_catalog_and_schema() -> None:
    records = [
        {
            "database_name": "graph-on-databricks",
            "schema_name": "graph-enriched-schema",
            "table_name": "gold_accounts",
        },
        {
            "database_name": "other-catalog",
            "schema_name": "graph-enriched-schema",
            "table_name": "gold_accounts",
        },
        {
            "database_name": "graph-on-databricks",
            "schema_name": "other-schema",
            "table_name": "gold_accounts",
        },
    ]

    assert records_for_source(records, "graph-on-databricks", "graph-enriched-schema") == [
        records[0]
    ]


def test_select_search_tool_prefers_hybrid() -> None:
    tools = {
        "get_context_by_table_full_text_search",
        "get_context_by_table_vector_search",
        "get_context_by_table_hybrid_search",
    }

    assert select_search_tool(tools, "table") == "get_context_by_table_hybrid_search"


def test_select_search_tool_falls_back_to_available_strategy() -> None:
    tools = {"get_context_by_column_full_text_search"}

    assert select_search_tool(tools, "column") == "get_context_by_column_full_text_search"


def test_select_search_tool_requires_registered_strategy() -> None:
    with pytest.raises(RuntimeError, match="table semantic-search tool"):
        select_search_tool(set(), "table")

"""Tests for catalog-qualified MCP validation helpers."""

from __future__ import annotations

from validate_mcp import records_for_source


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

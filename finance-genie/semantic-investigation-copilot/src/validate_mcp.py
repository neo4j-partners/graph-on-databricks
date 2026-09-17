"""Validate Neocarta through its real stdio MCP entry point."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import DEMO_DIR, load_demo_env, require_env, source_neo4j_connection
from runtime_contract import EXPECTED_TABLES, KNOWN_COLUMN, KNOWN_TABLE


def parse_tool_payload(result: Any) -> Any:
    """Parse the first JSON text payload returned by an MCP tool."""
    for content in result.content:
        text = getattr(content, "text", None)
        if text:
            return json.loads(text)
    return None


def parse_tool_result(result: Any) -> list[dict[str, Any]]:
    """Parse the list payload returned by a Neocarta catalog tool."""
    payload = parse_tool_payload(result)
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise TypeError("Neocarta MCP tool returned a non-list payload")
    return payload


def records_for_source(
    records: list[dict[str, Any]], catalog: str, schema: str
) -> list[dict[str, Any]]:
    """Return records explicitly qualified to the configured source."""
    return [
        record
        for record in records
        if record.get("database_name") == catalog and record.get("schema_name") == schema
    ]


async def validate() -> dict[str, Any]:
    """Launch the stdio server and validate catalog and full-text retrieval."""
    load_demo_env()
    catalog_name = require_env("DATABRICKS_CATALOG")
    schema_name = require_env("DATABRICKS_SCHEMA")
    source_database = source_neo4j_connection().database
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        cwd=DEMO_DIR,
        env=dict(os.environ),
    )

    async with (
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed_tools = await session.list_tools()
        tool_names = sorted(tool.name for tool in listed_tools.tools)

        expected_tools = {
            "get_context_by_column_full_text_search",
            "get_context_by_table_full_text_search",
            "get_full_metadata_schema",
            "get_neo4j_schema_context",
            "list_schemas",
            "list_tables_by_schema",
        }
        missing_tools = expected_tools.difference(tool_names)
        if missing_tools:
            raise RuntimeError(f"Required MCP tools were not registered: {sorted(missing_tools)}")
        if "get_business_concept_context" in tool_names:
            raise RuntimeError("Custom business-context retrieval must not be registered")

        schema_context = parse_tool_payload(await session.call_tool("get_neo4j_schema_context", {}))
        if not isinstance(schema_context, dict) or not schema_context.get("nodes"):
            raise RuntimeError("MCP Neo4j schema-context retrieval returned no canonical metadata")

        schemas = parse_tool_result(await session.call_tool("list_schemas", {}))
        schema_sources = {(record["database_name"], record["schema_name"]) for record in schemas}
        expected_sources = {
            (catalog_name, schema_name),
            (source_database, "default"),
        }
        if schema_sources != expected_sources:
            raise RuntimeError(
                f"MCP schema inventory changed: expected {expected_sources}, "
                f"received {schema_sources}"
            )

        tables = parse_tool_result(
            await session.call_tool(
                "list_tables_by_schema",
                {"schema_name": schema_name},
            )
        )
        if len(tables) != 1 or tables[0].get("schema_name") != schema_name:
            raise RuntimeError("MCP table inventory did not return exactly the configured schema")
        table_names = set(tables[0].get("table_names", []))
        if table_names != EXPECTED_TABLES:
            raise RuntimeError("MCP table inventory does not match the runtime contract")

        full_schema = parse_tool_result(await session.call_tool("get_full_metadata_schema", {}))
        qualified_schema = records_for_source(full_schema, catalog_name, schema_name)
        qualified_table_names = {record["table_name"] for record in qualified_schema}
        if len(qualified_schema) != len(full_schema) or qualified_table_names != EXPECTED_TABLES:
            raise RuntimeError("MCP full-schema results were incomplete or not catalog-qualified")

        table_context = parse_tool_result(
            await session.call_tool(
                "get_context_by_table_full_text_search",
                {"text_content": KNOWN_TABLE, "max_tables": 5},
            )
        )
        qualified_table_context = records_for_source(table_context, catalog_name, schema_name)
        table_hits = {record["table_name"] for record in qualified_table_context}
        if KNOWN_TABLE not in table_hits:
            raise RuntimeError(
                f"MCP table full-text lookup did not find catalog-qualified {KNOWN_TABLE}"
            )

        column_context = parse_tool_result(
            await session.call_tool(
                "get_context_by_column_full_text_search",
                {"text_content": KNOWN_COLUMN, "max_tables": 5},
            )
        )
        qualified_column_context = records_for_source(column_context, catalog_name, schema_name)
        column_hits = {
            column["column_name"]
            for record in qualified_column_context
            for column in record.get("columns", [])
        }
        if KNOWN_COLUMN not in column_hits:
            raise RuntimeError(
                f"MCP column full-text lookup did not find catalog-qualified {KNOWN_COLUMN}"
            )

    return {
        "status": "passed",
        "transport": "stdio",
        "registered_tools": tool_names,
        "catalog": catalog_name,
        "schema": schema_name,
        "neo4j_schema": {"database": source_database, "schema": "default"},
        "catalog_table_count": len(table_names),
        "full_schema_table_count": len(qualified_schema),
        "neo4j_schema_node_count": len(schema_context["nodes"]),
        "table_full_text_hit": KNOWN_TABLE,
        "column_full_text_hit": KNOWN_COLUMN,
    }


def main() -> None:
    """Run validation and print a machine-readable result."""
    print(json.dumps(asyncio.run(validate()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

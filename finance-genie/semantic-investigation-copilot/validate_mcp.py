"""Validate Neocarta through its real stdio MCP entry point."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import DEMO_DIR, load_demo_env, require_env


def parse_tool_result(result: Any) -> list[dict[str, Any]]:
    """Parse the JSON text returned by a Neocarta MCP tool."""
    for content in result.content:
        text = getattr(content, "text", None)
        if text:
            payload = json.loads(text)
            if not isinstance(payload, list):
                raise RuntimeError("Neocarta MCP tool returned a non-list payload")
            return payload
    return []


async def validate() -> dict[str, Any]:
    """Launch the stdio server and validate catalog and full-text retrieval."""
    load_demo_env()
    schema_name = require_env("DATABRICKS_SCHEMA")
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(DEMO_DIR / "serve_mcp.py")],
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
            "list_schemas",
            "list_tables_by_schema",
        }
        missing_tools = expected_tools.difference(tool_names)
        if missing_tools:
            raise RuntimeError(f"Required MCP tools were not registered: {sorted(missing_tools)}")

        schemas = parse_tool_result(await session.call_tool("list_schemas", {}))
        schema_names = {record["schema_name"] for record in schemas}
        if schema_name not in schema_names:
            raise RuntimeError(f"Configured schema {schema_name!r} was not returned by MCP")

        tables = parse_tool_result(
            await session.call_tool(
                "list_tables_by_schema",
                {"schema_name": schema_name},
            )
        )
        table_names = {
            table_name for record in tables for table_name in record.get("table_names", [])
        }
        if "gold_accounts" not in table_names:
            raise RuntimeError("MCP catalog lookup did not return gold_accounts")

        table_context = parse_tool_result(
            await session.call_tool(
                "get_context_by_table_full_text_search",
                {"text_content": "gold_accounts", "max_tables": 5},
            )
        )
        table_hits = {record["table_name"] for record in table_context}
        if "gold_accounts" not in table_hits:
            raise RuntimeError("MCP table full-text lookup did not find gold_accounts")

        column_context = parse_tool_result(
            await session.call_tool(
                "get_context_by_column_full_text_search",
                {"text_content": "identity_cluster_id", "max_tables": 5},
            )
        )
        column_hits = {
            column["column_name"]
            for record in column_context
            for column in record.get("columns", [])
        }
        if "identity_cluster_id" not in column_hits:
            raise RuntimeError("MCP column full-text lookup did not find identity_cluster_id")

    return {
        "status": "passed",
        "transport": "stdio",
        "registered_tools": tool_names,
        "schema": schema_name,
        "catalog_table_count": len(table_names),
        "table_full_text_hit": "gold_accounts",
        "column_full_text_hit": "identity_cluster_id",
        "embedding_calls": 0,
    }


def main() -> None:
    """Run validation and print a machine-readable result."""
    print(json.dumps(asyncio.run(validate()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

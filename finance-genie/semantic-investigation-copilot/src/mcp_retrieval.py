"""One-shot retrieval from the separately running NeoCarta MCP server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from validate_mcp import (
    parse_tool_payload,
    parse_tool_result,
    records_for_source,
    select_search_tool,
)

DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp"


class SemanticMcpUnavailableError(RuntimeError):
    """Raised when the persistent NeoCarta MCP server cannot be reached."""


def mcp_startup_instructions(mcp_url: str) -> str:
    """Return the actionable recovery text for an unavailable MCP endpoint."""
    return (
        f"NeoCarta MCP is unavailable at {mcp_url}. Start it in a separate terminal:\n"
        "  make mcp\n"
        "Leave that terminal running, then run this query again."
    )


@dataclass(frozen=True)
class ToolCall:
    """One MCP tool invocation, what it returned, and the names it retrieved."""

    tool_name: str
    arguments: dict[str, Any]
    result: Any
    names: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalTrace:
    """The three tool calls one Ask click runs against the semantic store."""

    table_search: ToolCall
    column_search: ToolCall
    schema_context: ToolCall

    def retrieved_names(self) -> set[str]:
        """Flatten every identifier retrieved across all three tool calls."""
        return (
            _catalog_identifiers(self.table_search.result)
            | _catalog_identifiers(self.column_search.result)
            | set(self.schema_context.names)
        )


def _table_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({record["table_name"] for record in records}))


def _column_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {column["column_name"] for record in records for column in record.get("columns", [])}
        )
    )


def _catalog_identifiers(result: Any) -> set[str]:
    """Return every table and column identifier present in a catalog tool result."""
    if not isinstance(result, list):
        return set()

    names: set[str] = set()
    for record in result:
        if not isinstance(record, dict):
            continue
        table_name = record.get("table_name")
        if isinstance(table_name, str) and table_name:
            names.add(table_name)
        for column in record.get("columns", []):
            if not isinstance(column, dict):
                continue
            column_name = column.get("column_name")
            if isinstance(column_name, str) and column_name:
                names.add(column_name)
    return names


def _schema_names(context: dict[str, Any] | None) -> tuple[str, ...]:
    names: set[str] = set()
    for node in (context or {}).get("nodes", []):
        if node.get("kind") == "Node" and node.get("label"):
            names.add(str(node["label"]))
        elif node.get("kind") == "Relationship" and node.get("type"):
            names.add(str(node["type"]))
    return tuple(sorted(names))


async def _run_retrieval(question: str, catalog: str, schema: str, mcp_url: str) -> RetrievalTrace:
    try:
        async with (
            streamable_http_client(mcp_url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listed_tools = await session.list_tools()
            tool_names = {tool.name for tool in listed_tools.tools}
            table_search_tool = select_search_tool(tool_names, "table")
            column_search_tool = select_search_tool(tool_names, "column")

            table_arguments = {"text_content": question, "max_tables": 5}
            table_records = records_for_source(
                parse_tool_result(await session.call_tool(table_search_tool, table_arguments)),
                catalog,
                schema,
            )

            column_arguments = {"text_content": question, "max_tables": 5}
            column_records = records_for_source(
                parse_tool_result(await session.call_tool(column_search_tool, column_arguments)),
                catalog,
                schema,
            )

            schema_arguments: dict[str, Any] = {}
            schema_context = parse_tool_payload(
                await session.call_tool("get_neo4j_schema_context", schema_arguments)
            )
    except* httpx.HTTPError as error:
        raise SemanticMcpUnavailableError(mcp_startup_instructions(mcp_url)) from error

    return RetrievalTrace(
        table_search=ToolCall(
            table_search_tool,
            table_arguments,
            table_records,
            _table_names(table_records),
        ),
        column_search=ToolCall(
            column_search_tool,
            column_arguments,
            column_records,
            _column_names(column_records),
        ),
        schema_context=ToolCall(
            "get_neo4j_schema_context",
            schema_arguments,
            schema_context,
            _schema_names(schema_context),
        ),
    )


def run_retrieval(
    question: str,
    catalog: str,
    schema: str,
    *,
    mcp_url: str = DEFAULT_MCP_URL,
) -> RetrievalTrace:
    """Run one retrieval against the persistent MCP server in a fresh event loop."""
    return asyncio.run(_run_retrieval(question, catalog, schema, mcp_url))

"""Start the NeoCarta MCP server with the demo-local environment."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Literal

from config import assert_semantic_store_target, load_demo_env, source_neo4j_connection
from neo4j_schema_map import register_schema_context_tool, source_scope

DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000


async def run_server(*, transport: Literal["stdio", "streamable-http"], port: int) -> None:
    """Create and run Neocarta's standard catalog server."""
    from neo4j import AsyncGraphDatabase, NotificationMinimumSeverity
    from neocarta._mcp.embeddings import create_embedder
    from neocarta._mcp.server import create_mcp_server
    from neocarta._mcp.settings import mcp_server_settings

    # Neocarta intentionally probes optional OSI, value, and aspect schema
    # elements. Neo4j logs the expected absences as full-query warnings.
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    driver = AsyncGraphDatabase.driver(
        uri=mcp_server_settings.neo4j_uri,
        auth=(
            mcp_server_settings.neo4j_username,
            mcp_server_settings.neo4j_password,
        ),
        warn_notification_severity=NotificationMinimumSeverity.OFF,
    )
    try:
        database = mcp_server_settings.neo4j_database
        embedder = create_embedder(driver, database)
        server = await create_mcp_server(driver, database, embedder)
        register_schema_context_tool(
            server,
            driver,
            database,
            source_scope(source_neo4j_connection()),
        )
        if transport == "stdio":
            await server.run_stdio_async()
        else:
            await server.run_http_async(
                transport="streamable-http",
                host=DEFAULT_MCP_HOST,
                port=port,
            )
    finally:
        await driver.close()


def main() -> None:
    """Load the explicit environment, then run the extended MCP server."""
    parser = argparse.ArgumentParser(description="Run the Finance Genie NeoCarta MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to run; stdio is the default for MCP clients that launch it.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MCP_PORT,
        help="Loopback HTTP port for --transport streamable-http (default: 8000).",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    load_demo_env()
    assert_semantic_store_target()
    if args.transport == "streamable-http":
        print(
            f"NeoCarta MCP is listening at http://{DEFAULT_MCP_HOST}:{args.port}/mcp",
            file=sys.stderr,
        )
    asyncio.run(run_server(transport=args.transport, port=args.port))


if __name__ == "__main__":
    main()

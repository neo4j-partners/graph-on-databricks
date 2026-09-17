"""Start Neocarta's standard stdio MCP server with the demo-local environment."""

from __future__ import annotations

import asyncio
import logging

from config import assert_semantic_store_target, load_demo_env, source_neo4j_connection
from neo4j_schema_map import register_schema_context_tool, source_scope


async def run_server() -> None:
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
        await server.run_stdio_async()
    finally:
        await driver.close()


def main() -> None:
    """Load the explicit environment, then run the extended stdio server."""
    load_demo_env()
    assert_semantic_store_target()
    asyncio.run(run_server())


if __name__ == "__main__":
    main()

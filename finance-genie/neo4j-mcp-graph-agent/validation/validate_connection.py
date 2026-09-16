"""Validate that the UC HTTP connection exists and is MCP-enabled."""

from __future__ import annotations

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

from _common import fail, load_settings, ok


def has_mcp_flag(connection) -> bool:
    options = {
        k.lower(): str(v).lower()
        for k, v in (getattr(connection, "options", None) or {}).items()
    }
    properties = {
        k.lower(): str(v).lower()
        for k, v in (getattr(connection, "properties", None) or {}).items()
    }
    return (
        options.get("is_mcp_connection") == "true"
        or properties.get("is_mcp_connection") == "true"
    )


def main() -> None:
    settings = load_settings()
    profile = settings.databricks_profile
    ws = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    try:
        connection = ws.connections.get(settings.uc_connection_name)
    except NotFound:
        fail(f"connection not found: {settings.uc_connection_name}")

    connection_type = getattr(connection.connection_type, "value", connection.connection_type)
    if connection_type != "HTTP":
        fail(f"connection is {connection_type!r}, expected HTTP")
    if not has_mcp_flag(connection):
        fail("connection exists, but is_mcp_connection is not true")

    ok(f"connection is MCP-enabled: {settings.uc_connection_name}")


if __name__ == "__main__":
    main()

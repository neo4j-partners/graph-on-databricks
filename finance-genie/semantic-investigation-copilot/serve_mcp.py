"""Start Neocarta's stdio MCP server with the demo-local environment."""

from __future__ import annotations

from config import assert_local_semantic_store, load_demo_env


def main() -> None:
    """Load the explicit demo environment before importing MCP settings."""
    load_demo_env()
    assert_local_semantic_store()

    from neocarta._mcp.server import run

    run()


if __name__ == "__main__":
    main()

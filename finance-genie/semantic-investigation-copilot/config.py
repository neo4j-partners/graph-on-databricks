"""Configuration helpers for the local Finance Neocarta prototype."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

DEMO_DIR = Path(__file__).resolve().parent
ENV_FILE = DEMO_DIR / ".env"


def load_demo_env() -> Path:
    """Load the demo-local environment file as the prototype's source of truth."""
    if not ENV_FILE.is_file():
        raise RuntimeError(f"Missing {ENV_FILE}. Copy .env.example and fill in local values.")
    load_dotenv(ENV_FILE, override=True)
    return ENV_FILE


def require_env(name: str) -> str:
    """Return a required environment value or raise a concise configuration error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def databricks_server_hostname() -> str:
    """Return the SQL connector hostname from an explicit value or workspace URL."""
    explicit = os.getenv("DATABRICKS_SERVER_HOSTNAME", "").strip()
    if explicit:
        return explicit

    host = require_env("DATABRICKS_HOST")
    parsed = urlparse(host if "://" in host else f"https://{host}")
    if not parsed.hostname:
        raise RuntimeError("DATABRICKS_HOST does not contain a valid hostname")
    return parsed.hostname


def databricks_http_path() -> str:
    """Return the SQL warehouse HTTP path from an explicit value or warehouse ID."""
    explicit = os.getenv("DATABRICKS_HTTP_PATH", "").strip()
    if explicit:
        return explicit
    return f"/sql/1.0/warehouses/{require_env('DATABRICKS_WAREHOUSE_ID')}"


def assert_local_semantic_store() -> None:
    """Refuse writes unless the configured semantic store resolves to loopback."""
    parsed = urlparse(require_env("NEO4J_URI"))
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "Phase 2 ingestion only writes to a loopback Neo4j URI. "
            "Use the dedicated local semantic store."
        )

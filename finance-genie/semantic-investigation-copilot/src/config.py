"""Configuration helpers for the isolated Finance Neocarta prototype."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

DEMO_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = DEMO_DIR / ".env"
ENV_CONTRACT_NAMES = frozenset(
    {
        "DATABRICKS_CATALOG",
        "DATABRICKS_HOST",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_PROFILE",
        "DATABRICKS_SCHEMA",
        "DATABRICKS_SERVER_HOSTNAME",
        "DATABRICKS_TOKEN",
        "DATABRICKS_WAREHOUSE_ID",
        "EMBEDDING_MODEL",
        "NEO4J_DATABASE",
        "NEO4J_PASSWORD",
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEOCARTA_ALLOW_REMOTE_STORE",
    }
)
AMBIENT_CONNECTION_NAMES = frozenset(
    {
        "DATABRICKS_API_BASE",
        "DATABRICKS_API_KEY",
        "DATABRICKS_CONFIG_PROFILE",
        "EMBEDDING_DIMENSIONS",
    }
)
OPERATIONAL_GRAPH_LABELS = ["Account", "Customer", "Phone", "Address"]
OPERATIONAL_GRAPH_QUERY = """CYPHER 25
MATCH (node)
WHERE any(node_label IN labels(node) WHERE node_label IN $operational_labels)
RETURN count(node) AS operational_node_count
"""


def load_demo_env() -> Path:
    """Load the demo-local environment file as the prototype's source of truth."""
    if not ENV_FILE.is_file():
        raise RuntimeError(f"Missing {ENV_FILE}. Copy .env.example and fill in local values.")

    values = dotenv_values(ENV_FILE, interpolate=False)
    unknown_names = set(values).difference(ENV_CONTRACT_NAMES)
    if unknown_names:
        raise RuntimeError(f"Unsupported variables in {ENV_FILE}: {sorted(unknown_names)}")

    for name in ENV_CONTRACT_NAMES | AMBIENT_CONNECTION_NAMES:
        os.environ.pop(name, None)
    for name, value in values.items():
        if value is not None:
            os.environ[name] = value

    profile = os.getenv("DATABRICKS_PROFILE", "").strip()
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
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


def assert_semantic_store_target() -> None:
    """Require loopback or an explicitly approved dedicated remote store."""
    parsed = urlparse(require_env("NEO4J_URI"))
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return

    remote_approved = os.getenv("NEOCARTA_ALLOW_REMOTE_STORE", "").strip().lower()
    if remote_approved not in {"1", "true", "yes"}:
        raise RuntimeError(
            "Remote semantic-store writes require NEOCARTA_ALLOW_REMOTE_STORE=true. "
            "Only approve a dedicated metadata store, never the operational graph."
        )


def assert_no_operational_graph_nodes(driver, database: str) -> None:
    """Refuse a target containing core Finance Genie operational node labels."""
    records, _, _ = driver.execute_query(
        OPERATIONAL_GRAPH_QUERY,
        operational_labels=OPERATIONAL_GRAPH_LABELS,
        database_=database,
    )
    if records and records[0]["operational_node_count"]:
        raise RuntimeError(
            "The semantic-store target contains Finance Genie operational nodes. "
            "Use a dedicated Neo4j instance or database."
        )

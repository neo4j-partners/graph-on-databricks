"""Tests for prototype configuration resolution and write isolation."""

from __future__ import annotations

import pytest

import config
from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    databricks_http_path,
    databricks_server_hostname,
    load_demo_env,
    optional_bool_env,
    source_neo4j_connection,
)


class StubDriver:
    """Return a configured operational-node count for isolation tests."""

    def __init__(self, count: int) -> None:
        self.count = count

    def execute_query(self, *args, **kwargs):
        return ([{"operational_node_count": self.count}], None, None)


def test_derives_databricks_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_SERVER_HOSTNAME", raising=False)
    monkeypatch.delenv("DATABRICKS_HTTP_PATH", raising=False)
    monkeypatch.setenv("DATABRICKS_HOST", "https://dbc-example.cloud.databricks.com/")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "warehouse-123")

    assert databricks_server_hostname() == "dbc-example.cloud.databricks.com"
    assert databricks_http_path() == "/sql/1.0/warehouses/warehouse-123"


def test_rejects_nonlocal_semantic_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://operational.example.com")
    monkeypatch.delenv("NEOCARTA_ALLOW_REMOTE_STORE", raising=False)

    with pytest.raises(RuntimeError, match="NEOCARTA_ALLOW_REMOTE_STORE"):
        assert_semantic_store_target()


def test_optional_bool_env_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_INGEST_GOVERNED_TAGS", raising=False)
    assert not optional_bool_env("DATABRICKS_INGEST_GOVERNED_TAGS")

    monkeypatch.setenv("DATABRICKS_INGEST_GOVERNED_TAGS", "yes")
    assert optional_bool_env("DATABRICKS_INGEST_GOVERNED_TAGS")

    monkeypatch.setenv("DATABRICKS_INGEST_GOVERNED_TAGS", "sometimes")
    with pytest.raises(RuntimeError, match="must be one of"):
        optional_bool_env("DATABRICKS_INGEST_GOVERNED_TAGS")


def test_accepts_local_semantic_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:17687")

    assert_semantic_store_target()


def test_accepts_approved_remote_semantic_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://semantic.example.com")
    monkeypatch.setenv("NEOCARTA_ALLOW_REMOTE_STORE", "true")

    assert_semantic_store_target()


def test_rejects_operational_source_equal_to_semantic_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_env = tmp_path / "source.env"
    source_env.write_text(
        "NEO4J_URI=bolt://127.0.0.1:17687\n"
        "NEO4J_USERNAME=reader\n"
        "NEO4J_PASSWORD=secret\n"
        "NEO4J_DATABASE=neo4j\n"
    )
    monkeypatch.setattr(config, "SOURCE_ENV_FILE", source_env)
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:17687")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")

    with pytest.raises(RuntimeError, match="same Neo4j database"):
        source_neo4j_connection()


def test_demo_env_overrides_ambient_values(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NEO4J_URI=bolt://127.0.0.1:17687\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://operational.example.com")

    load_demo_env()

    assert config.require_env("NEO4J_URI") == "bolt://127.0.0.1:17687"


def test_demo_env_clears_optional_ambient_connection_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABRICKS_HOST=https://dbc-example.cloud.databricks.com\n"
        "DATABRICKS_PROFILE=demo-profile\n"
    )
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    for name in (
        "DATABRICKS_API_BASE",
        "DATABRICKS_API_KEY",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_SERVER_HOSTNAME",
        "DATABRICKS_TOKEN",
        "EMBEDDING_DIMENSIONS",
    ):
        monkeypatch.setenv(name, "ambient-value")

    load_demo_env()

    for name in (
        "DATABRICKS_API_BASE",
        "DATABRICKS_API_KEY",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_SERVER_HOSTNAME",
        "DATABRICKS_TOKEN",
        "EMBEDDING_DIMENSIONS",
    ):
        assert name not in config.os.environ
    assert config.os.environ["DATABRICKS_CONFIG_PROFILE"] == "demo-profile"


def test_demo_env_rejects_unknown_variables(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("UNKNOWN_SETTING=value\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    with pytest.raises(RuntimeError, match="UNKNOWN_SETTING"):
        load_demo_env()


def test_accepts_metadata_only_graph() -> None:
    assert_no_operational_graph_nodes(StubDriver(0), "neo4j")


def test_rejects_operational_graph() -> None:
    with pytest.raises(RuntimeError, match="operational nodes"):
        assert_no_operational_graph_nodes(StubDriver(1), "neo4j")

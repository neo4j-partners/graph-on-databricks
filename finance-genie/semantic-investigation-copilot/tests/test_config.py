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


def test_accepts_local_semantic_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:17687")

    assert_semantic_store_target()


def test_accepts_approved_remote_semantic_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://semantic.example.com")
    monkeypatch.setenv("NEOCARTA_ALLOW_REMOTE_STORE", "true")

    assert_semantic_store_target()


def test_demo_env_overrides_ambient_values(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NEO4J_URI=bolt://127.0.0.1:17687\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://operational.example.com")

    load_demo_env()

    assert config.require_env("NEO4J_URI") == "bolt://127.0.0.1:17687"


def test_accepts_metadata_only_graph() -> None:
    assert_no_operational_graph_nodes(StubDriver(0), "neo4j")


def test_rejects_operational_graph() -> None:
    with pytest.raises(RuntimeError, match="operational nodes"):
        assert_no_operational_graph_nodes(StubDriver(1), "neo4j")

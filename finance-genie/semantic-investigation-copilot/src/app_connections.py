"""Cached connection probes for the app's three read-only sources.

Each probe is wrapped in `st.cache_resource` so it runs once per process, not
once per Streamlit rerun. A probe never raises: failure is a returned state,
so a page whose source is unreachable can say so in place while the other
pages stay usable.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st
from databricks import sql as databricks_sql
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    databricks_http_path,
    databricks_server_hostname,
    require_env,
    source_neo4j_connection,
)
from ingest import databricks_access_token


@dataclass(frozen=True)
class WarehouseCredentials:
    """Everything needed to open a fresh SQL warehouse connection, or a failure."""

    ok: bool
    error: str = ""
    server_hostname: str = ""
    http_path: str = ""
    access_token: str = ""
    catalog: str = ""
    schema: str = ""


@dataclass(frozen=True)
class GraphConnection:
    """A cached, read-only Neo4j driver for one source, or a failure reason."""

    ok: bool
    error: str = ""
    driver: Driver | None = None
    database: str = ""
    host: str = ""


@st.cache_resource(show_spinner="Connecting to the SQL warehouse…")
def warehouse_credentials() -> WarehouseCredentials:
    """Probe the SQL warehouse once per process and cache the credentials or failure."""
    try:
        credentials = WarehouseCredentials(
            ok=False,
            server_hostname=databricks_server_hostname(),
            http_path=databricks_http_path(),
            access_token=databricks_access_token(),
            catalog=require_env("DATABRICKS_CATALOG"),
            schema=require_env("DATABRICKS_SCHEMA"),
        )
        with (
            databricks_sql.connect(
                server_hostname=credentials.server_hostname,
                http_path=credentials.http_path,
                access_token=credentials.access_token,
                catalog=credentials.catalog,
                schema=credentials.schema,
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1")
            cursor.fetchall()
    except (RuntimeError, ValueError, OSError) as error:
        return WarehouseCredentials(ok=False, error=str(error))
    return WarehouseCredentials(
        ok=True,
        server_hostname=credentials.server_hostname,
        http_path=credentials.http_path,
        access_token=credentials.access_token,
        catalog=credentials.catalog,
        schema=credentials.schema,
    )


def open_warehouse_connection(credentials: WarehouseCredentials):
    """Open a fresh SQL warehouse connection for one query. Not cached."""
    return databricks_sql.connect(
        server_hostname=credentials.server_hostname,
        http_path=credentials.http_path,
        access_token=credentials.access_token,
        catalog=credentials.catalog,
        schema=credentials.schema,
    )


@st.cache_resource(show_spinner="Connecting to the operational graph…")
def operational_graph_connection() -> GraphConnection:
    """Open and cache one read-only driver to the Finance Genie operational graph."""
    try:
        connection = source_neo4j_connection()
        driver = GraphDatabase.driver(
            connection.uri, auth=(connection.username, connection.password)
        )
        driver.verify_connectivity()
    except (RuntimeError, Neo4jError) as error:
        return GraphConnection(ok=False, error=str(error))
    return GraphConnection(ok=True, driver=driver, database=connection.database, host=connection.uri)


@st.cache_resource(show_spinner="Connecting to the NeoCarta semantic store…")
def semantic_store_connection() -> GraphConnection:
    """Open and cache one read-only driver to the NeoCarta semantic store."""
    try:
        assert_semantic_store_target()
        uri = require_env("NEO4J_URI")
        database = require_env("NEO4J_DATABASE")
        driver = GraphDatabase.driver(
            uri, auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD"))
        )
        driver.verify_connectivity()
        assert_no_operational_graph_nodes(driver, database)
    except (RuntimeError, Neo4jError) as error:
        return GraphConnection(ok=False, error=str(error))
    return GraphConnection(ok=True, driver=driver, database=database, host=uri)

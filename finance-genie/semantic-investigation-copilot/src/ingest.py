"""Ingest Finance Genie Unity Catalog metadata into the semantic graph."""

from __future__ import annotations

import os

from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from neo4j import GraphDatabase
from neocarta.connectors.databricks import DatabricksSchemaConnector, DatabricksTagsConnector

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    databricks_http_path,
    databricks_server_hostname,
    load_demo_env,
    optional_bool_env,
    require_env,
)


def databricks_access_token() -> str:
    """Return a PAT when supplied, otherwise obtain a token from the local profile."""
    token = os.getenv("DATABRICKS_TOKEN", "").strip()
    if token:
        return token

    profile = require_env("DATABRICKS_PROFILE")
    config = Config(profile=profile, host=require_env("DATABRICKS_HOST"))
    authorization = config.authenticate().get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise RuntimeError(f"Databricks profile {profile!r} did not provide a bearer token")
    return token


def ingest_governed_tag_definitions(
    *,
    neo4j_driver: object,
    database_name: str,
    access_token: str,
) -> bool:
    """Ingest governed-tag definitions when the demo source uses them."""
    if not optional_bool_env("DATABRICKS_INGEST_GOVERNED_TAGS"):
        return False

    workspace_client = WorkspaceClient(
        host=require_env("DATABRICKS_HOST"),
        token=access_token,
    )
    connector = DatabricksTagsConnector(
        workspace_client=workspace_client,
        neo4j_driver=neo4j_driver,
        database_name=database_name,
    )
    connector.ingest()
    return True


def main() -> None:
    """Run a metadata-only ingest for one configured Unity Catalog schema."""
    load_demo_env()
    assert_semantic_store_target()

    catalog = require_env("DATABRICKS_CATALOG")
    schema = require_env("DATABRICKS_SCHEMA")
    neo4j_database = require_env("NEO4J_DATABASE")
    access_token = databricks_access_token()

    driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        driver.verify_connectivity()
        assert_no_operational_graph_nodes(driver, neo4j_database)
        with sql.connect(
            server_hostname=databricks_server_hostname(),
            http_path=databricks_http_path(),
            access_token=access_token,
            catalog=catalog,
            schema=schema,
        ) as connection:
            connector = DatabricksSchemaConnector(
                connection=connection,
                catalog=catalog,
                neo4j_driver=driver,
                database_name=neo4j_database,
                value_sample_limit=0,
            )
            connector.ingest(schema=schema)
        tag_definitions_ingested = ingest_governed_tag_definitions(
            neo4j_driver=driver,
            database_name=neo4j_database,
            access_token=access_token,
        )
    finally:
        driver.close()

    print(f"Ingested metadata for {catalog}.{schema} with value sampling disabled.")
    if tag_definitions_ingested:
        print("Ingested Databricks governed-tag definitions.")


if __name__ == "__main__":
    main()

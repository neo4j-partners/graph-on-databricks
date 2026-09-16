"""Ingest Finance Genie Unity Catalog metadata into the local semantic graph."""

from __future__ import annotations

import os

from databricks import sql
from databricks.sdk.core import Config
from neo4j import GraphDatabase
from neocarta.connectors.databricks import DatabricksSchemaConnector

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    databricks_http_path,
    databricks_server_hostname,
    load_demo_env,
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


def main() -> None:
    """Run a metadata-only ingest for one configured Unity Catalog schema."""
    load_demo_env()
    assert_semantic_store_target()

    catalog = require_env("DATABRICKS_CATALOG")
    schema = require_env("DATABRICKS_SCHEMA")
    neo4j_database = require_env("NEO4J_DATABASE")

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
            access_token=databricks_access_token(),
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
    finally:
        driver.close()

    print(f"Ingested metadata for {catalog}.{schema} with value sampling disabled.")


if __name__ == "__main__":
    main()

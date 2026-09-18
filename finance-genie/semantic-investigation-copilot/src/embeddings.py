"""Create and store NeoCarta embeddings for semantic metadata."""

from __future__ import annotations

from neo4j import Driver, GraphDatabase
from neocarta import NodeLabel
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

from config import (
    assert_no_operational_graph_nodes,
    assert_semantic_store_target,
    load_demo_env,
    require_env,
)

EMBEDDED_NODE_LABELS = [NodeLabel.TABLE, NodeLabel.COLUMN]


def create_embeddings(driver: Driver, database_name: str) -> None:
    """Embed unprocessed table and column metadata and persist the vectors."""
    connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=driver,
        embedding_model=require_env("EMBEDDING_MODEL"),
        database_name=database_name,
    )
    connector.run(node_labels=EMBEDDED_NODE_LABELS)


def main() -> None:
    """Backfill missing semantic-map embeddings in the configured Neo4j store."""
    load_demo_env()
    assert_semantic_store_target()
    database_name = require_env("NEO4J_DATABASE")
    driver = GraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        driver.verify_connectivity()
        assert_no_operational_graph_nodes(driver, database_name)
        create_embeddings(driver, database_name)
    finally:
        driver.close()

    print("Stored embeddings for NeoCarta table and column metadata.")


if __name__ == "__main__":
    main()

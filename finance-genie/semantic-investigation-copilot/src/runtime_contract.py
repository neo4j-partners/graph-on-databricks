"""Expected base metadata-store contents for the fixed Finance Genie demo."""

from __future__ import annotations

EXPECTED_NODE_COUNTS = {
    "__neocarta_graph__": 1,
    "Database": 1,
    "Schema": 1,
    "Table": 17,
    "Column": 172,
    "Value": 0,
}

EXPECTED_RELATIONSHIP_COUNTS = {
    "HAS_SCHEMA": 1,
    "HAS_TABLE": 17,
    "HAS_COLUMN": 172,
    "HAS_VALUE": 0,
    "REFERENCES": 6,
}

EXPECTED_TABLES = frozenset(
    {
        "account_graph_features",
        "account_labels",
        "account_links",
        "account_links_large",
        "accounts",
        "client_retrieval",
        "client_staging_graph_rag",
        "client_staging_no_context",
        "client_staging_schema_dump",
        "customers",
        "dbxcarta_run_summary",
        "gold_account_similarity_pairs",
        "gold_accounts",
        "gold_fraud_ring_communities",
        "merchants",
        "training_dataset",
        "transactions",
    }
)

EXPECTED_INDEXES = {
    "column_full_text_index": ("FULLTEXT", "ONLINE"),
    "column_id_constraint": ("RANGE", "ONLINE"),
    "column_name_index": ("RANGE", "ONLINE"),
    "column_vector_index": ("VECTOR", "ONLINE"),
    "database_id_constraint": ("RANGE", "ONLINE"),
    "database_name_index": ("RANGE", "ONLINE"),
    "schema_full_text_index": ("FULLTEXT", "ONLINE"),
    "schema_id_constraint": ("RANGE", "ONLINE"),
    "schema_name_index": ("RANGE", "ONLINE"),
    "table_full_text_index": ("FULLTEXT", "ONLINE"),
    "table_id_constraint": ("RANGE", "ONLINE"),
    "table_name_index": ("RANGE", "ONLINE"),
    "table_vector_index": ("VECTOR", "ONLINE"),
}

EXPECTED_VECTOR_INDEXES = {
    "column_vector_index": "Column",
    "table_vector_index": "Table",
}

EXPECTED_CONSTRAINTS = {
    "column_id_constraint": ("NODE_KEY", "NODE", ("Column",), ("id",)),
    "database_id_constraint": ("NODE_KEY", "NODE", ("Database",), ("id",)),
    "schema_id_constraint": ("NODE_KEY", "NODE", ("Schema",), ("id",)),
    "table_id_constraint": ("NODE_KEY", "NODE", ("Table",), ("id",)),
    "value_id_constraint": ("NODE_KEY", "NODE", ("Value",), ("id",)),
}

KNOWN_TABLE = "gold_accounts"
KNOWN_COLUMN = "identity_cluster_id"

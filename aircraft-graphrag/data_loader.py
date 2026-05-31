"""Dependency-light helpers: data loading and the Neo4j connection.

This module imports only the ``neo4j`` driver and the standard library, so the
loader notebooks (01 ETL, 02 GDS) can use it without installing
``neo4j-graphrag`` or ``mlflow``. The heavier helpers (Databricks model
wrappers, SimpleKGPipeline) live in ``data_utils``, which re-exports everything
here for the retriever notebooks.
"""

import csv
import io
import urllib.request
from pathlib import Path
from typing import Dict, List

from neo4j import GraphDatabase


# =============================================================================
# Data Loading (DATA_SOURCE switch)
# =============================================================================
#
# Three ways to reach the committed data/ directory:
#   "github"  -> read raw files straight from the public repo (default, zero setup)
#   "local"   -> read from a local clone (./data relative to the notebook)
#   "volume"  -> read from a Unity Catalog volume you have populated
#
# Loading from a raw GitHub URL fetches over the public internet, so it suits a
# public sample dataset and demo workspaces. For private data or locked-down
# workspaces, switch to "local" or "volume".

GITHUB_DATA_BASE = (
    "https://raw.githubusercontent.com/neo4j-partners/"
    "graph-on-databricks/main/aircraft-graphrag/data"
)
LOCAL_DATA_DIR = "data"
# Example volume path. Override via load_csv(..., volume_path=...) if yours differs.
VOLUME_DATA_PATH = "/Volumes/main/default/aircraft_graphrag"


def resolve_data_base(
    source: str = "github",
    *,
    local_dir: str = LOCAL_DATA_DIR,
    volume_path: str = VOLUME_DATA_PATH,
) -> str:
    """Return the base location for data files for the chosen source."""
    if source == "github":
        return GITHUB_DATA_BASE
    if source == "local":
        return local_dir
    if source == "volume":
        return volume_path
    raise ValueError(f"Unknown DATA_SOURCE '{source}'. Use 'github', 'local', or 'volume'.")


def _read_bytes(base: str, filename: str, source: str) -> bytes:
    """Read raw bytes for a file from the resolved base location."""
    if source == "github":
        with urllib.request.urlopen(f"{base}/{filename}") as response:
            return response.read()
    return (Path(base) / filename).read_bytes()


def load_csv(
    filename: str,
    source: str = "github",
    *,
    local_dir: str = LOCAL_DATA_DIR,
    volume_path: str = VOLUME_DATA_PATH,
) -> List[Dict[str, str]]:
    """Load a CSV from the data directory as a list of row dicts.

    Returns plain dicts (not a DataFrame) because the loader notebooks feed the
    rows straight into Neo4j with ``UNWIND``. Column names are preserved exactly
    as written in the CSV header, including the Neo4j import markers such as
    ``:ID(Aircraft)`` and ``:START_ID(Flight)``.
    """
    base = resolve_data_base(source, local_dir=local_dir, volume_path=volume_path)
    raw = _read_bytes(base, filename, source).decode("utf-8")
    return list(csv.DictReader(io.StringIO(raw)))


def load_text(
    filename: str,
    source: str = "github",
    *,
    local_dir: str = LOCAL_DATA_DIR,
    volume_path: str = VOLUME_DATA_PATH,
) -> str:
    """Load a text file (a maintenance manual) from the data directory."""
    base = resolve_data_base(source, local_dir=local_dir, volume_path=volume_path)
    return _read_bytes(base, filename, source).decode("utf-8").strip()


# =============================================================================
# Neo4j Connection
# =============================================================================

class Neo4jConnection:
    """Manages a Neo4j driver connection used across the notebooks."""

    def __init__(self, uri: str, username: str, password: str):
        self.uri = uri
        self.username = username
        self.password = password
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    def verify(self) -> "Neo4jConnection":
        """Verify connectivity and return self for chaining."""
        self.driver.verify_connectivity()
        print("Connected to Neo4j successfully!")
        return self

    def clear_chunks(self) -> "Neo4jConnection":
        """Remove enrichment nodes (Document, Chunk, OperatingLimit, pipeline internals).

        Preserves the aircraft topology loaded by notebook 01. Batched to avoid
        transaction timeouts.
        """
        labels = ["Chunk", "Document", "OperatingLimit", "__Entity__", "__KGBuilder__"]
        deleted_total = 0
        for label in labels:
            while True:
                records, _, _ = self.driver.execute_query(
                    f"MATCH (n:{label}) WITH n LIMIT 500 DETACH DELETE n RETURN count(*) AS deleted"
                )
                count = records[0]["deleted"]
                deleted_total += count
                if count == 0:
                    break
        print(f"Cleared {deleted_total} enrichment nodes (Document, Chunk, OperatingLimit)")
        return self

    def get_graph_stats(self) -> "Neo4jConnection":
        """Print node counts by label."""
        records, _, _ = self.driver.execute_query("""
            MATCH (n)
            UNWIND labels(n) AS label
            RETURN label, count(*) AS count
            ORDER BY label
        """)
        print("=== Graph Statistics ===")
        for record in records:
            print(f"  {record['label']}: {record['count']}")
        return self

    def close(self) -> None:
        """Close the database connection."""
        self.driver.close()
        print("Connection closed.")

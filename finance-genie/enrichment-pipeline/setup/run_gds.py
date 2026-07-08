# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "neo4j>=5.20",
#     "python-dotenv>=1.0",
#     "graphdatascience>=1.12",
#     "pandas>=2.0",
# ]
# ///
"""Official one-shot GDS setup for the graph-fraud-analyst Databricks App.

Run this once after ingesting account data into Aura. It writes the node
properties the deployed app and the gold pull read via live Cypher:

    :Account.risk_score              (PageRank)
    :Account.community_id            (Louvain)
    :Account.betweenness_centrality  (Betweenness, sampled)
    :Account.similarity_score        (max JACCARD over :SIMILAR_TO)
    :Account.identity_cluster_id     (WCC over the customer identity graph)
    :Account.identity_cluster_size   (customers per identity cluster)
    :Account.shared_phone_count      (other customers sharing the holder phone)
    :Account.shared_address_count    (other customers sharing the holder address)

By default the script is idempotent: if these properties already exist and
are populated on every :Account node, it exits 0 with a no-op message. Pass
--force to recompute and overwrite.

Run from enrichment-pipeline/:

    uv run setup/run_gds.py            # idempotent, skip if already populated
    uv run setup/run_gds.py --force    # always recompute

The heavy lifting is delegated to validation/run_gds.py so the algorithm
parameters (sampling sizes, similarity thresholds, etc.) stay defined in one
place.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

_HERE = Path(__file__).resolve().parent
_VALIDATION_DIR = _HERE.parent / "validation"
sys.path.insert(0, str(_VALIDATION_DIR))

from _common import fail, header, load_env, ok  # noqa: E402

REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
REQUIRED_PROPERTIES = (
    "risk_score",
    "community_id",
    "betweenness_centrality",
    "similarity_score",
    "identity_cluster_id",
    "identity_cluster_size",
    "shared_phone_count",
    "shared_address_count",
)


def _account_property_coverage(driver) -> dict[str, int]:
    """Return per-property counts of non-null values across :Account nodes."""
    cypher = """
    MATCH (a:Account)
    RETURN count(a)                       AS total,
           count(a.risk_score)            AS risk_score,
           count(a.community_id)          AS community_id,
           count(a.betweenness_centrality) AS betweenness_centrality,
           count(a.similarity_score)      AS similarity_score,
           count(a.identity_cluster_id)   AS identity_cluster_id,
           count(a.identity_cluster_size) AS identity_cluster_size,
           count(a.shared_phone_count)    AS shared_phone_count,
           count(a.shared_address_count)  AS shared_address_count
    """
    with driver.session() as s:
        return dict(s.run(cypher).single())


def _already_populated(coverage: dict[str, int]) -> bool:
    total = coverage["total"]
    if total == 0:
        return False
    return all(coverage[p] == total for p in REQUIRED_PROPERTIES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute GDS properties even if they are already populated.",
    )
    args = parser.parse_args()

    load_env(REQUIRED_VARS)
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]

    header("Checking current property coverage on :Account")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
    except AuthError as e:
        fail(f"Neo4j auth failed: {e}")
    except ServiceUnavailable as e:
        fail(f"Cannot reach Neo4j at {uri}: {e}")

    try:
        coverage = _account_property_coverage(driver)
    finally:
        driver.close()

    total = coverage["total"]
    print(f"      :Account nodes: {total:,}")
    for prop in REQUIRED_PROPERTIES:
        n = coverage[prop]
        marker = "OK   " if n == total and total > 0 else "MISS "
        print(f"      {marker} {prop}: {n:,}/{total:,}")

    if total == 0:
        fail(
            "No :Account nodes found. Run jobs/02_neo4j_ingest.py first "
            "to load CSV data into Neo4j."
        )

    if _already_populated(coverage) and not args.force:
        ok(
            "All GDS properties present on every :Account node. No-op. "
            "Pass --force to recompute."
        )
        return

    if args.force:
        print("\n--force set, recomputing GDS properties...")
    else:
        print("\nGDS properties missing or partial, running full pipeline...")

    # Delegate to the canonical pipeline. validation/run_gds.py is the single
    # source of truth for the algorithm parameters.
    run_gds_path = _VALIDATION_DIR / "run_gds.py"
    if not run_gds_path.exists():
        fail(f"validation/run_gds.py not found at {run_gds_path}")

    import runpy

    runpy.run_path(str(run_gds_path), run_name="__main__")


if __name__ == "__main__":
    main()

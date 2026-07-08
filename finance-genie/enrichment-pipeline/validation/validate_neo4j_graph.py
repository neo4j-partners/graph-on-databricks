# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "neo4j>=5.20",
#     "python-dotenv>=1.0",
# ]
# ///
"""Validate the graph that Databricks ingested into Neo4j Aura.

Checks the graph against ground_truth.json (which records ring membership
and anchor merchants for the data that was actually uploaded):

  1. Node counts    :Account == 25,000, :Merchant == 7,500
  2. Edge counts    TRANSACTED_WITH ~250,000 (±5%); TRANSFERRED_TO above a sanity floor
                    (the Neo4j Spark Connector dedupes duplicate src/dst pairs,
                    so CSV row count is not the Neo4j edge count)
  3. Ring density   Within-ring TRANSFERRED_TO density >> background density
  4. Ring anchors   Ring members visit anchor merchants at elevated rate

Run from this directory:

    uv run validate_neo4j_graph.py

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from _common import fail, load_env, ok

REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")

EXPECTED_ACCOUNTS = 25_000
EXPECTED_MERCHANTS = 7_500
EXPECTED_TRANSACTED = 250_000
EDGE_COUNT_TOLERANCE = 0.05  # allow ±5% for stochastic generation

# TRANSFERRED_TO count is NOT compared to the CSV row count. The Neo4j Spark
# Connector writes relationships with `save.strategy=keys`, which dedupes
# duplicate (src, dst) pairs into a single edge. `account_links.csv` contains
# 300,000 sampled pairs but only ~223,000 are unique, so the ingested edge
# count is systematically lower than the CSV row count. The density-ratio and
# anchor-visit checks below are the actual structural signal gates — those
# would fail if the ingest were broken, independent of raw edge count.
TRANSFERRED_MIN = 100_000  # sanity floor; catches an empty or near-empty ingest

DENSITY_RATIO_MIN = 100.0
ANCHOR_VISIT_RATIO_MIN = 2.0


def load_ground_truth(script_dir: Path) -> dict:
    gt_path = script_dir.parent.parent / "data" / "ground_truth.json"
    if not gt_path.is_file():
        fail(f"ground_truth.json not found at {gt_path}")
    return json.loads(gt_path.read_text())


def connect(uri: str, user: str, password: str):
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except AuthError as e:
        fail(f"authentication failed: {e}")
    except ServiceUnavailable as e:
        fail(f"cannot reach Neo4j at {uri}: {e}")
    except Exception as e:
        fail(f"driver error: {e}")


def check_node_counts(session) -> list[str]:
    problems: list[str] = []

    n_account = session.run("MATCH (a:Account) RETURN count(a) AS n").single()["n"]
    n_merchant = session.run("MATCH (m:Merchant) RETURN count(m) AS n").single()["n"]

    if n_account == EXPECTED_ACCOUNTS:
        ok(f":Account count = {n_account:,}")
    else:
        problems.append(f":Account count = {n_account:,}, expected {EXPECTED_ACCOUNTS:,}")

    if n_merchant == EXPECTED_MERCHANTS:
        ok(f":Merchant count = {n_merchant:,}")
    else:
        problems.append(f":Merchant count = {n_merchant:,}, expected {EXPECTED_MERCHANTS:,}")

    return problems


def check_edge_counts(session) -> tuple[list[str], int]:
    problems: list[str] = []

    n_tx = session.run(
        "MATCH ()-[r:TRANSACTED_WITH]->() RETURN count(r) AS n"
    ).single()["n"]
    n_p2p = session.run(
        "MATCH ()-[r:TRANSFERRED_TO]->() RETURN count(r) AS n"
    ).single()["n"]

    if abs(n_tx - EXPECTED_TRANSACTED) / EXPECTED_TRANSACTED <= EDGE_COUNT_TOLERANCE:
        ok(f":TRANSACTED_WITH count = {n_tx:,}")
    else:
        problems.append(
            f":TRANSACTED_WITH count = {n_tx:,}, expected ~{EXPECTED_TRANSACTED:,} (±5%)"
        )

    # TRANSFERRED_TO is keyed on (src, dst) by the Neo4j Spark Connector, so
    # the ingested count is the number of unique pairs — not the CSV row count.
    # The sanity floor catches only an empty or near-empty ingest.
    if n_p2p >= TRANSFERRED_MIN:
        ok(f":TRANSFERRED_TO count = {n_p2p:,} (unique pairs; CSV has more due to dedup)")
    else:
        problems.append(
            f":TRANSFERRED_TO count = {n_p2p:,} is below sanity floor {TRANSFERRED_MIN:,}"
        )

    return problems, n_p2p


def check_ring_density(session, gt: dict, total_p2p: int) -> list[str]:
    problems: list[str] = []

    rings = gt["rings"]
    ring_sizes = [len(r["account_ids"]) for r in rings]
    total_ring_accounts = sum(ring_sizes)

    per_ring_counts: list[int] = []
    total_within_ring = 0

    for r in rings:
        ring_id = r["ring_id"]
        members = [int(a) for a in r["account_ids"]]
        rec = session.run(
            """
            MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account)
            WHERE a.account_id IN $members AND b.account_id IN $members
            RETURN count(r) AS n
            """,
            members=members,
        ).single()
        n = rec["n"]
        per_ring_counts.append(n)
        total_within_ring += n
        print(f"      ring {ring_id}: {n:,} within-ring TRANSFERRED_TO edges")

    background = total_p2p - total_within_ring

    within_possible_directed = sum(sz * (sz - 1) for sz in ring_sizes)
    background_possible = EXPECTED_ACCOUNTS * (EXPECTED_ACCOUNTS - 1) - within_possible_directed

    within_density = (
        total_within_ring / within_possible_directed if within_possible_directed else 0.0
    )
    background_density = (
        background / background_possible if background_possible else 0.0
    )
    ratio = within_density / background_density if background_density else float("inf")

    print(
        f"      within-ring density: {within_density:.6f}  "
        f"background density: {background_density:.8f}  "
        f"ratio: {ratio:.1f}"
    )

    if ratio >= DENSITY_RATIO_MIN:
        ok(
            f"within-ring density ratio {ratio:.1f}× background "
            f"(>= {DENSITY_RATIO_MIN:g})"
        )
    else:
        problems.append(
            f"within-ring density ratio {ratio:.1f}× is below {DENSITY_RATIO_MIN:g}×. "
            f"Ring topology is not dense in Neo4j — PageRank and Louvain cannot "
            f"surface ring members. Check TRANSFERRED_TO ingest."
        )

    if total_within_ring == 0:
        problems.append(
            "zero within-ring TRANSFERRED_TO edges — the P2P graph was ingested "
            "without any intra-ring transfers. Check account_links CSV and ingest step."
        )

    return problems


def check_ring_anchors(session, gt: dict) -> list[str]:
    problems: list[str] = []

    rings = gt["rings"]

    for r in rings:
        ring_id = r["ring_id"]
        members = [int(a) for a in r["account_ids"]]
        anchors = [int(m["merchant_id"]) for m in r["anchor_merchants"]]

        rec = session.run(
            """
            MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
            WHERE a.account_id IN $members
            WITH count(t) AS total_txns,
                 sum(CASE WHEN m.merchant_id IN $anchors THEN 1 ELSE 0 END) AS anchor_txns
            RETURN total_txns, anchor_txns
            """,
            members=members,
            anchors=anchors,
        ).single()

        total_txns = rec["total_txns"]
        anchor_txns = rec["anchor_txns"]
        ring_anchor_rate = anchor_txns / total_txns if total_txns else 0.0

        baseline_rate = len(anchors) / EXPECTED_MERCHANTS
        ratio = ring_anchor_rate / baseline_rate if baseline_rate else float("inf")

        print(
            f"      ring {ring_id}: {anchor_txns:,}/{total_txns:,} txns at anchors "
            f"= {ring_anchor_rate:.3%}  (baseline {baseline_rate:.3%}, {ratio:.1f}×)"
        )

        if ratio < ANCHOR_VISIT_RATIO_MIN:
            problems.append(
                f"ring {ring_id}: anchor visit ratio {ratio:.1f}× is below "
                f"{ANCHOR_VISIT_RATIO_MIN}× — ring members are not preferentially "
                f"visiting their anchor merchants in Neo4j."
            )

    if not problems:
        ok(f"all {len(rings)} rings visit their anchors at >= {ANCHOR_VISIT_RATIO_MIN}× baseline")

    return problems


def main() -> None:
    load_env(REQUIRED_VARS)
    script_dir = Path(__file__).parent
    gt = load_ground_truth(script_dir)
    n_rings = len(gt["rings"])
    n_fraud = gt["summary"]["total_fraud_accounts"]
    ok(
        f"ground_truth.json loaded: {n_rings} rings, {n_fraud:,} fraud accounts, "
        f"{gt['summary']['anchor_merchants_per_ring']} anchors/ring"
    )

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]

    driver = connect(uri, user, password)
    ok(f"connected to {uri}")

    problems: list[str] = []
    try:
        with driver.session() as session:
            print("\n[1/4] Node counts")
            problems += check_node_counts(session)

            print("\n[2/4] Edge counts")
            edge_problems, total_p2p = check_edge_counts(session)
            problems += edge_problems

            print("\n[3/4] Within-ring P2P density")
            problems += check_ring_density(session, gt, total_p2p)

            print("\n[4/4] Ring anchor-merchant visits")
            problems += check_ring_anchors(session, gt)
    finally:
        driver.close()

    print()
    if problems:
        print(f"FAIL  {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("PASS  Neo4j graph matches ground truth.")


if __name__ == "__main__":
    main()

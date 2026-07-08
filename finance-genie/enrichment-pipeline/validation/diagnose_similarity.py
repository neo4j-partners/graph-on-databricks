# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "graphdatascience>=1.8",
#     "python-dotenv>=1.0",
# ]
# ///
"""Diagnostic distributions for the Node Similarity feature in Neo4j.

Prints percentile distributions for:
  1. similarity_score property on Account nodes (the MAX Jaccard per account)
  2. similarity_score property on :SIMILAR_TO edges (the raw pair scores)
  3. TRANSACTED_WITH degree per Account (how many merchants each account visited)

Use this to understand the noise floor vs. ring signal before tuning
generator parameters or GDS settings.

Run from this directory:

    uv run diagnose_similarity.py

Exits 0 unless the Neo4j connection fails — this is diagnostic-only,
no pass/fail thresholds.
"""

from __future__ import annotations

import os
import sys

from graphdatascience import GraphDataScience

from _common import load_env


REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")


def load_neo4j_creds() -> tuple[str, str, str]:
    load_env(REQUIRED_VARS)
    return (
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )


def connect(uri: str, user: str, password: str) -> GraphDataScience:
    try:
        gds = GraphDataScience(uri, auth=(user, password), aura_ds=True)
        gds.run_cypher("RETURN 1")
        return gds
    except Exception as e:
        print(f"FAIL  cannot connect to Neo4j at {uri}: {e}")
        sys.exit(1)


def print_row(label: str, row) -> None:
    """Print one percentile row from a single-row DataFrame."""
    print(f"  {label}")
    cols = list(row.index)
    vals = list(row.values)
    parts = []
    for c, v in zip(cols, vals):
        if v is None:
            parts.append(f"{c}=None")
        elif isinstance(v, float):
            parts.append(f"{c}={v:.4f}")
        else:
            parts.append(f"{c}={v:,}")
    print("    " + "  ".join(parts))


def diagnose_account_similarity_scores(gds: GraphDataScience) -> None:
    print("\n[1/3] Account.similarity_score distribution (per-account MAX Jaccard)")
    result = gds.run_cypher(
        """
        MATCH (a:Account)
        WHERE a.similarity_score IS NOT NULL
        RETURN
          count(a)                                    AS n,
          avg(a.similarity_score)                     AS avg,
          percentileCont(a.similarity_score, 0.10)   AS p10,
          percentileCont(a.similarity_score, 0.25)   AS p25,
          percentileCont(a.similarity_score, 0.50)   AS p50,
          percentileCont(a.similarity_score, 0.75)   AS p75,
          percentileCont(a.similarity_score, 0.90)   AS p90,
          percentileCont(a.similarity_score, 0.99)   AS p99,
          max(a.similarity_score)                     AS max_val
        """
    )
    if result.empty:
        print("  (no accounts with similarity_score — GDS has not run yet)")
        return
    print_row("all accounts", result.iloc[0])


def diagnose_edge_similarity_scores(gds: GraphDataScience) -> None:
    print("\n[2/3] SIMILAR_TO edge.similarity_score distribution (raw pair Jaccard)")
    count_row = gds.run_cypher(
        "MATCH ()-[s:SIMILAR_TO]->() RETURN count(s) AS n"
    ).iloc[0]
    n_edges = int(count_row["n"])
    print(f"  total :SIMILAR_TO edges: {n_edges:,}")
    if n_edges == 0:
        print("  (no edges — NodeSimilarity has not written yet)")
        return

    result = gds.run_cypher(
        """
        MATCH ()-[s:SIMILAR_TO]->()
        RETURN
          count(s)                                    AS n,
          avg(s.similarity_score)                     AS avg,
          percentileCont(s.similarity_score, 0.10)   AS p10,
          percentileCont(s.similarity_score, 0.25)   AS p25,
          percentileCont(s.similarity_score, 0.50)   AS p50,
          percentileCont(s.similarity_score, 0.75)   AS p75,
          percentileCont(s.similarity_score, 0.90)   AS p90,
          percentileCont(s.similarity_score, 0.99)   AS p99,
          max(s.similarity_score)                     AS max_val
        """
    )
    print_row("all edges", result.iloc[0])


def diagnose_transaction_degree(gds: GraphDataScience) -> None:
    print("\n[3/3] Account TRANSACTED_WITH degree distribution (merchants visited per account)")
    result = gds.run_cypher(
        """
        MATCH (a:Account)
        OPTIONAL MATCH (a)-[t:TRANSACTED_WITH]->()
        WITH a, count(t) AS deg
        RETURN
          count(a)                        AS n_accounts,
          avg(deg)                        AS avg_deg,
          min(deg)                        AS min_deg,
          percentileCont(deg, 0.05)       AS p05,
          percentileCont(deg, 0.25)       AS p25,
          percentileCont(deg, 0.50)       AS p50,
          percentileCont(deg, 0.75)       AS p75,
          percentileCont(deg, 0.95)       AS p95,
          max(deg)                        AS max_deg,
          sum(CASE WHEN deg = 0 THEN 1 ELSE 0 END) AS zero_degree
        """
    )
    if result.empty:
        print("  (no results)")
        return
    row = result.iloc[0]
    print(f"  n_accounts={int(row['n_accounts']):,}  zero_degree={int(row['zero_degree']):,}")
    print(
        f"  min={int(row['min_deg'])}  p05={row['p05']:.0f}  p25={row['p25']:.0f}"
        f"  p50={row['p50']:.0f}  p75={row['p75']:.0f}  p95={row['p95']:.0f}"
        f"  max={int(row['max_deg'])}  avg={row['avg_deg']:.1f}"
    )


def diagnose_fraud_vs_normal(gds: GraphDataScience) -> None:
    """Break down similarity scores for fraud vs. normal accounts using ring membership."""
    print("\n[bonus] Fraud vs. normal similarity_score breakdown")

    import json
    from pathlib import Path

    gt_path = Path(__file__).parent.parent.parent / "data" / "ground_truth.json"
    if not gt_path.is_file():
        print(f"  (skipping — ground_truth.json not found at {gt_path})")
        return

    gt = json.loads(gt_path.read_text())
    fraud_ids = [int(a) for ring in gt["rings"] for a in ring["account_ids"]]
    print(f"  fraud accounts: {len(fraud_ids):,}  rings: {len(gt['rings'])}")

    result = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.similarity_score IS NOT NULL
        RETURN
          avg(CASE WHEN a.account_id IN $fraud_ids     THEN a.similarity_score END) AS fraud_avg,
          avg(CASE WHEN NOT a.account_id IN $fraud_ids THEN a.similarity_score END) AS normal_avg,
          percentileCont(
            CASE WHEN a.account_id IN $fraud_ids THEN a.similarity_score END, 0.50
          ) AS fraud_p50,
          percentileCont(
            CASE WHEN NOT a.account_id IN $fraud_ids THEN a.similarity_score END, 0.50
          ) AS normal_p50,
          max(CASE WHEN a.account_id IN $fraud_ids     THEN a.similarity_score END) AS fraud_max,
          max(CASE WHEN NOT a.account_id IN $fraud_ids THEN a.similarity_score END) AS normal_max
        """,
        {"fraud_ids": fraud_ids},
    )
    if result.empty:
        print("  (no results)")
        return
    row = result.iloc[0]
    fraud_avg = row["fraud_avg"] or 0.0
    normal_avg = row["normal_avg"] or 0.0
    ratio = fraud_avg / normal_avg if normal_avg else float("inf")
    print(
        f"  fraud:  avg={fraud_avg:.4f}  p50={row['fraud_p50']:.4f}  max={row['fraud_max']:.4f}"
    )
    print(
        f"  normal: avg={normal_avg:.4f}  p50={row['normal_p50']:.4f}  max={row['normal_max']:.4f}"
    )
    print(f"  fraud/normal avg ratio = {ratio:.2f}×  (Criterion A target: >= 2.0×)")
    if ratio >= 2.0:
        print("  PASS  Criterion A")
    else:
        print(f"  FAIL  Criterion A — ratio {ratio:.2f}× < 2.0×")


def main() -> None:
    uri, user, password = load_neo4j_creds()
    gds = connect(uri, user, password)
    print(f"connected to {uri}")

    diagnose_account_similarity_scores(gds)
    diagnose_edge_similarity_scores(gds)
    diagnose_transaction_degree(gds)
    diagnose_fraud_vs_normal(gds)

    print()


if __name__ == "__main__":
    main()

"""Phase 5 graph analytics for the supplier-risk-graph demo.

Runs two analytics passes over the graph with the graphdatascience Python client
and writes the results back into Neo4j so they join the same provenance story as
the rule-based classifications:

  1. Supplier risk exposure (extends Q4). Aggregates the supply network
     Supplier-[:SUPPLIES]->BusinessUnit and computes each business unit's
     exposure as the mean riskScore of the suppliers feeding it. This is a
     one-hop aggregation, so a plain Cypher avg() computes it exactly, no GDS
     algorithm required. Surfaces BU-03, exposed through four mid-band suppliers
     that the flat riskScore >= 70 filter misses. Written back as a
     supplierExposureScore property on every BusinessUnit node.

  2. Customer similarity (extends Q5/Q6). The one genuine GDS algorithm: runs
     gds.knn over the payment-behavior features (avgDaysLate, overdueShare,
     churnRisk, profitabilityTrend, the categorical fields encoded numerically;
     upsellScore deliberately excluded) to build the similarity graph, then
     surfaces the non-flagged customers with the highest similarity to any member
     of the rule-defined risky cohort. The four nearest are classified as Risky
     Customer (TERM-04) with a source:'gds' CLASSIFIED_AS edge. The candidates
     emerge from the kNN run, not a planted set.

Q4 exposure is asserted against data/ground_truth.json so a drift fails loud.
Q5/Q6 has no exact-value ground truth: the answer emerges from the deterministic
kNN run and is checked only for shape (four non-flagged candidates, each with a
risky neighbor). Deterministic given the fixed-seed data. Re-runnable: the
similarity projection is dropped on entry and exit, and prior source:'gds' edges
are cleared before the similarity write-back.

Run from the project directory after load.py:

    uv run gds.py

Connection settings come from .env (see .env.sample): NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from graphdatascience import GraphDataScience

HERE = Path(__file__).parent

SIMILARITY_GRAPH = "customerSimilarity"

RISKY_TERM_ID = "TERM-04"  # Risky Customer
GDS_SOURCE = "gds"
EVALUATED_AT = "2026-07-01T00:00:00Z"  # frozen as-of, matches the planted edges
LATE_DAYS_THRESHOLD = 60  # Q5 last-3-invoices rule, identifies the risky cohort
N_SIMILAR = 4  # candidates to surface near the risky cohort
KNN_TOP_K = 10  # neighbors per node; wide enough to link candidates to the cohort


def require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def header(title: str) -> None:
    print(f"\n=== {title} ===")


def drop_graph(gds: GraphDataScience, name: str) -> None:
    gds.run_cypher("CALL gds.graph.drop($name, false) YIELD graphName", params={"name": name})


def compute_exposure(gds: GraphDataScience) -> list[dict[str, Any]]:
    """Algorithm 1: mean supplier risk per BusinessUnit.

    Each business unit's exposure is the mean riskScore of the suppliers feeding
    it over the SUPPLIES edges. This is a one-hop aggregation, so a single Cypher
    query with sum, count, and max computes the ranking rows exactly. The mean is
    the metric that surfaces BU-03: several mid-band suppliers give it a high
    average even though no single score crosses the flat riskScore >= 70 filter.
    """
    header("Algorithm 1: supplier risk exposure (Q4)")
    rows = gds.run_cypher(
        """
        MATCH (s:Supplier)-[:SUPPLIES]->(b:BusinessUnit)
        RETURN b.id AS bu, b.name AS name,
               sum(s.riskScore) AS total_risk,
               count(s) AS supplier_count,
               max(s.riskScore) AS max_supplier_risk
        """
    )

    exposure = sorted(
        (
            {
                "business_unit_id": r["bu"],
                "name": r["name"],
                "supplier_count": int(r["supplier_count"]),
                "avg_supplier_risk": round(
                    float(r["total_risk"]) / int(r["supplier_count"]), 1
                ),
                "max_supplier_risk": int(r["max_supplier_risk"]),
            }
            for _, r in rows.iterrows()
        ),
        key=lambda r: r["avg_supplier_risk"],
        reverse=True,
    )

    print("  BusinessUnit exposure ranking (mean supplying-supplier riskScore):")
    for rank, row in enumerate(exposure, start=1):
        print(
            f"    {rank}. {row['business_unit_id']} {row['name']:<20} "
            f"exposure={row['avg_supplier_risk']:>5}  "
            f"suppliers={row['supplier_count']:>2}  max={row['max_supplier_risk']}"
        )
    return exposure


def write_exposure(gds: GraphDataScience, exposure: list[dict[str, Any]]) -> None:
    rows = [
        {"bu": r["business_unit_id"], "score": float(r["avg_supplier_risk"])}
        for r in exposure
    ]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (b:BusinessUnit {id: row.bu})
        SET b.supplierExposureScore = row.score
        RETURN count(b) AS written
        """,
        params={"rows": rows},
    )
    print(f"  wrote supplierExposureScore to {int(result['written'].iloc[0])} BusinessUnit nodes")


def find_risky_cohort(gds: GraphDataScience) -> list[str]:
    """Customers whose last three invoices are each more than 60 days late."""
    df = gds.run_cypher(
        """
        MATCH (c:Customer)-[:HAS_INVOICE]->(i:Invoice)
        WITH c, i ORDER BY i.dueDate DESC
        WITH c, collect(i)[..3] AS last3
        WHERE size(last3) = 3 AND all(x IN last3 WHERE x.daysLate > $late)
        RETURN c.id AS cid ORDER BY cid
        """,
        params={"late": LATE_DAYS_THRESHOLD},
    )
    return [r["cid"] for _, r in df.iterrows()]


def compute_similarity(gds: GraphDataScience, risky: list[str]) -> list[dict[str, Any]]:
    """Algorithm 2: GDS kNN similarity, ranked to the risky cohort.

    Projects the customers with their encoded payment-behavior features, runs
    gds.knn to build the similarity graph, then ranks the non-flagged customers
    by their highest similarity to any member of the rule-defined risky cohort.
    The four nearest are the emergent Q5/Q6 candidates: they come out of the kNN
    run, not a planted set.
    """
    header("Algorithm 2: customer similarity (Q5/Q6)")
    print(f"  risky cohort (last-3-invoices rule): {', '.join(risky)}")

    names = {
        r["id"]: r["name"]
        for _, r in gds.run_cypher("MATCH (c:Customer) RETURN c.id AS id, c.name AS name").iterrows()
    }

    drop_graph(gds, SIMILARITY_GRAPH)
    gds.graph.cypher.project(
        """
        MATCH (c:Customer)
        RETURN gds.graph.project(
            $graph_name, c, null,
            {sourceNodeProperties: {features: [
                CASE WHEN c.avgDaysLate / 100.0 > 1.0 THEN 1.0 ELSE c.avgDaysLate / 100.0 END,
                c.overdueShare,
                CASE c.churnRisk WHEN 'low' THEN 0.0 WHEN 'medium' THEN 0.5 ELSE 1.0 END,
                CASE c.profitabilityTrend WHEN 'improving' THEN 0.0 WHEN 'stable' THEN 0.5 ELSE 1.0 END
            ]}, targetNodeProperties: null}
        )
        """,
        database=gds.database(),
        graph_name=SIMILARITY_GRAPH,
    )
    # kNN similarity graph over the encoded features. concurrency=1, full
    # sampling, and a fixed seed make it deterministic; Euclidean similarity is
    # normalized by GDS to (0, 1], higher meaning more alike.
    neighbors = gds.run_cypher(
        """
        CALL gds.knn.stream($graph, {
            nodeProperties: {features: 'EUCLIDEAN'},
            topK: $top_k, sampleRate: 1.0, randomSeed: 42, concurrency: 1
        })
        YIELD node1, node2, similarity
        RETURN gds.util.asNode(node1).id AS c1, gds.util.asNode(node2).id AS c2, similarity
        """,
        params={"graph": SIMILARITY_GRAPH, "top_k": KNN_TOP_K},
    )
    drop_graph(gds, SIMILARITY_GRAPH)
    print(f"  kNN produced {len(neighbors)} neighbor pairs over 4 encoded features")

    # Each non-flagged customer's highest similarity to any risky member. kNN
    # pairs are directed per source's top-K, so scan both endpoints.
    risky_set = set(risky)
    best: dict[str, float] = {}
    for _, row in neighbors.iterrows():
        c1, c2, sim = row["c1"], row["c2"], float(row["similarity"])
        if c1 in risky_set and c2 not in risky_set:
            candidate = c2
        elif c2 in risky_set and c1 not in risky_set:
            candidate = c1
        else:
            continue
        if sim > best.get(candidate, 0.0):
            best[candidate] = sim

    nearest = sorted(best, key=lambda cid: (-best[cid], cid))[:N_SIMILAR]
    candidates = [
        {
            "customer_id": cid,
            "name": names[cid],
            "similarity_to_risky": round(best[cid], 4),
        }
        for cid in nearest
    ]

    print("  Non-flagged customers most similar to the risky cohort (GDS kNN):")
    for rank, row in enumerate(candidates, start=1):
        print(
            f"    {rank}. {row['customer_id']} {row['name']:<20} "
            f"similarity={row['similarity_to_risky']}"
        )
    return candidates


def write_similarity(gds: GraphDataScience, candidates: list[dict[str, Any]]) -> None:
    cleared = gds.run_cypher(
        """
        MATCH (:Customer)-[r:CLASSIFIED_AS {source: $source}]->(:BusinessTerm)
        DELETE r RETURN count(r) AS deleted
        """,
        params={"source": GDS_SOURCE},
    )
    print(f"  cleared {int(cleared['deleted'].iloc[0])} prior source:'gds' classifications")

    rows = [
        # score: kNN similarity to the nearest risky member, higher is more alike.
        {"cid": c["customer_id"], "score": c["similarity_to_risky"]}
        for c in candidates
    ]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.cid})
        MATCH (t:BusinessTerm {id: $term})
        MERGE (c)-[r:CLASSIFIED_AS {source: $source}]->(t)
        SET r.algorithm = 'knn',
            r.score = row.score,
            r.evaluatedAt = datetime($evaluated_at),
            r.reason = 'GDS kNN: among the known risky cohort''s nearest neighbors; not yet tripping the last-3-invoices rule'
        RETURN count(r) AS written
        """,
        params={
            "rows": rows,
            "term": RISKY_TERM_ID,
            "source": GDS_SOURCE,
            "evaluated_at": EVALUATED_AT,
        },
    )
    print(
        f"  wrote {int(result['written'].iloc[0])} CLASSIFIED_AS edges "
        f"(Customer)-[:CLASSIFIED_AS {{source:'gds'}}]->(:BusinessTerm {RISKY_TERM_ID})"
    )


def assert_exposure(exposure: list[dict[str, Any]], ground_truth: dict[str, Any]) -> None:
    expected = ground_truth["gds_q4_supplier_exposure_by_business_unit"]
    if exposure != expected:
        sys.exit(
            "Q4 exposure drifted from ground_truth.\n"
            f"  computed: {exposure}\n  expected: {expected}"
        )
    top = exposure[0]["business_unit_id"]
    if top != ground_truth["gds_q4_exposed_business_unit"]:
        sys.exit(f"Q4 top BU {top} != expected {ground_truth['gds_q4_exposed_business_unit']}")
    print(f"  assert OK: exposure ranking matches ground_truth, {top} on top")


def assert_similarity(candidates: list[dict[str, Any]], risky: list[str]) -> None:
    """Shape check: N_SIMILAR non-flagged candidates, each with a risky neighbor.

    The candidates are emergent from the kNN run, so there is no exact-value
    ground truth to compare against. This guards only against gross breakage.
    """
    risky_set = set(risky)
    if len(candidates) != N_SIMILAR:
        sys.exit(f"Q5 expected {N_SIMILAR} candidates, got {len(candidates)}: {candidates}")
    flagged = [c["customer_id"] for c in candidates if c["customer_id"] in risky_set]
    if flagged:
        sys.exit(f"Q5 candidates include rule-flagged customers: {flagged}")
    unlinked = [c["customer_id"] for c in candidates if not c["similarity_to_risky"] > 0.0]
    if unlinked:
        sys.exit(f"Q5 candidates have no similarity to the risky cohort: {unlinked}")
    ids = ", ".join(c["customer_id"] for c in candidates)
    print(f"  assert OK: {N_SIMILAR} non-flagged candidates, each near the risky cohort ({ids})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="directory holding ground_truth.json (default: data/)",
    )
    args = parser.parse_args()

    ground_truth = json.loads((args.data_dir / "ground_truth.json").read_text())

    load_dotenv(HERE / ".env")
    uri = require_env("NEO4J_URI")
    auth = (require_env("NEO4J_USERNAME", "neo4j"), require_env("NEO4J_PASSWORD"))
    database = require_env("NEO4J_DATABASE", "neo4j")

    gds = GraphDataScience(uri, auth=auth, database=database)
    with gds:
        print(f"Connected to {uri} (database={database}), GDS client v{gds.version()}")

        exposure = compute_exposure(gds)
        assert_exposure(exposure, ground_truth)
        write_exposure(gds, exposure)

        risky = find_risky_cohort(gds)
        candidates = compute_similarity(gds, risky)
        assert_similarity(candidates, risky)
        write_similarity(gds, candidates)

    print("\nGDS analytics complete: Q4 exposure and Q5 similarity written back to Neo4j.")


if __name__ == "__main__":
    main()

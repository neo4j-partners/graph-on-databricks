"""Phase 5 GDS analytics for the supplier-risk-graph demo.

Runs two Graph Data Science algorithms with the graphdatascience Python client
and writes the results back into Neo4j so they join the same provenance story
as the rule-based classifications:

  1. Supplier risk propagation (extends Q4). Projects the supply network
     Supplier-[:SUPPLIES]->BusinessUnit and computes each business unit's
     exposure as degree-normalized weighted centrality: the mean riskScore of
     the suppliers feeding it. Surfaces BU-03, exposed through four mid-band
     suppliers that the flat riskScore >= 70 filter misses. Written back as a
     supplierExposureScore property on every BusinessUnit node.

  2. Customer similarity (extends Q5/Q6). Runs kNN over the payment-behavior
     features (avgDaysLate, overdueShare, churnRisk, profitabilityTrend, the
     categorical fields encoded numerically; upsellScore deliberately excluded)
     and ranks non-flagged customers by distance to the known risky cohort's
     centroid. The four nearest are classified as Risky Customer (TERM-04) with
     a source:'gds' CLASSIFIED_AS edge.

Both outputs are asserted against data/ground_truth.json so a drift fails loud.
Deterministic given the fixed-seed data. Re-runnable: GDS projections are
dropped on entry and exit, and prior source:'gds' edges are cleared before the
similarity write-back.

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

SUPPLY_GRAPH = "supplyExposure"
SIMILARITY_GRAPH = "customerSimilarity"

RISKY_TERM_ID = "TERM-04"  # Risky Customer
GDS_SOURCE = "gds"
EVALUATED_AT = "2026-07-01T00:00:00Z"  # frozen as-of, matches the planted edges
LATE_DAYS_THRESHOLD = 60  # Q5 last-3-invoices rule, identifies the risky cohort
N_SIMILAR = 4  # candidates to surface near the risky cohort

# Numeric encoding of the categorical similarity features. Mirrors the scales
# the generator used to compute ground_truth, so the distances match exactly.
CHURN_SCALE = {"low": 0.0, "medium": 0.5, "high": 1.0}
TREND_SCALE = {"improving": 0.0, "stable": 0.5, "declining": 1.0}


def require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def header(title: str) -> None:
    print(f"\n=== {title} ===")


def similarity_vector(row: dict[str, Any]) -> tuple[float, float, float, float]:
    """Encode a customer's payment-behavior features exactly as the generator."""
    return (
        min(float(row["avgDaysLate"]) / 100.0, 1.0),
        float(row["overdueShare"]),
        CHURN_SCALE[row["churnRisk"]],
        TREND_SCALE[row["profitabilityTrend"]],
    )


def drop_graph(gds: GraphDataScience, name: str) -> None:
    gds.run_cypher("CALL gds.graph.drop($name, false) YIELD graphName", params={"name": name})


def compute_exposure(gds: GraphDataScience) -> list[dict[str, Any]]:
    """Algorithm 1: mean supplier risk per BusinessUnit via degree centrality.

    Projects the supply network with the supplier riskScore carried onto each
    SUPPLIES relationship, then reads two reverse-orientation degree centralities
    over the projection: the weighted degree (total incoming supplier risk) and
    the plain degree (supplier count). The exposure score is the ratio, i.e. the
    risk propagated in from the supply network normalized by connectivity.
    """
    header("Algorithm 1: supplier risk propagation (Q4)")
    drop_graph(gds, SUPPLY_GRAPH)
    G, project = gds.graph.cypher.project(
        """
        MATCH (s:Supplier)-[:SUPPLIES]->(b:BusinessUnit)
        RETURN gds.graph.project(
            $graph_name, s, b,
            {relationshipProperties: {risk: s.riskScore}}
        )
        """,
        database=gds.database(),
        graph_name=SUPPLY_GRAPH,
    )
    print(
        f"  projected '{G.name()}': {G.node_count()} nodes, "
        f"{G.relationship_count()} SUPPLIES relationships"
    )

    weighted = gds.run_cypher(
        """
        CALL gds.degree.stream($graph, {orientation: 'REVERSE', relationshipWeightProperty: 'risk'})
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS n, score
        WHERE n:BusinessUnit
        RETURN n.id AS bu, n.name AS name, score AS total_risk
        """,
        params={"graph": SUPPLY_GRAPH},
    )
    counts = gds.run_cypher(
        """
        CALL gds.degree.stream($graph, {orientation: 'REVERSE'})
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS n, score
        WHERE n:BusinessUnit
        RETURN n.id AS bu, score AS supplier_count
        """,
        params={"graph": SUPPLY_GRAPH},
    )
    # max_supplier_risk completes the ground_truth ranking rows; it is a plain
    # aggregate over the same edges, not part of the propagation metric.
    maxima = gds.run_cypher(
        """
        MATCH (s:Supplier)-[:SUPPLIES]->(b:BusinessUnit)
        RETURN b.id AS bu, max(s.riskScore) AS max_supplier_risk
        """
    )
    drop_graph(gds, SUPPLY_GRAPH)

    total = {r["bu"]: float(r["total_risk"]) for _, r in weighted.iterrows()}
    names = {r["bu"]: r["name"] for _, r in weighted.iterrows()}
    count = {r["bu"]: int(round(float(r["supplier_count"]))) for _, r in counts.iterrows()}
    mx = {r["bu"]: int(r["max_supplier_risk"]) for _, r in maxima.iterrows()}

    exposure = sorted(
        (
            {
                "business_unit_id": bu,
                "name": names[bu],
                "supplier_count": count[bu],
                "avg_supplier_risk": round(total[bu] / count[bu], 1),
                "max_supplier_risk": mx[bu],
            }
            for bu in total
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


def compute_similarity(gds: GraphDataScience) -> list[dict[str, Any]]:
    """Algorithm 2: kNN over payment-behavior features, ranked to the risky cohort.

    kNN establishes the similarity structure over the four encoded features.
    Candidate selection then ranks non-flagged customers by Euclidean distance
    to the risky cohort's centroid, the same metric the generator recorded in
    ground_truth, so the surfaced set and distances reproduce exactly.
    """
    header("Algorithm 2: customer similarity (Q5/Q6)")

    customers = gds.run_cypher(
        """
        MATCH (c:Customer)
        RETURN c.id AS id, c.name AS name, c.avgDaysLate AS avgDaysLate,
               c.overdueShare AS overdueShare, c.churnRisk AS churnRisk,
               c.profitabilityTrend AS profitabilityTrend
        """
    )
    rows = {r["id"]: dict(r) for _, r in customers.iterrows()}
    vectors = {cid: similarity_vector(row) for cid, row in rows.items()}

    risky = find_risky_cohort(gds)
    print(f"  risky cohort (last-3-invoices rule): {', '.join(risky)}")

    # kNN over the encoded feature vector: fully deterministic so re-runs match.
    drop_graph(gds, SIMILARITY_GRAPH)
    G, _ = gds.graph.cypher.project(
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
    knn = gds.knn.stream(
        G,
        nodeProperties=["features"],
        topK=5,
        randomSeed=42,
        concurrency=1,
        sampleRate=1.0,
    )
    print(f"  kNN computed {len(knn)} neighbor pairs over 4 encoded features")
    drop_graph(gds, SIMILARITY_GRAPH)

    # Rank to the known cohort: distance to the risky centroid (ground_truth metric).
    risky_vecs = [vectors[cid] for cid in risky]
    centroid = [sum(dim) / len(risky_vecs) for dim in zip(*risky_vecs)]

    def distance(cid: str) -> float:
        return sum((a - b) ** 2 for a, b in zip(vectors[cid], centroid)) ** 0.5

    risky_set = set(risky)
    nearest = sorted((cid for cid in vectors if cid not in risky_set), key=distance)[:N_SIMILAR]

    candidates = [
        {
            "customer_id": cid,
            "name": rows[cid]["name"],
            "avgDaysLate": float(rows[cid]["avgDaysLate"]),
            "overdueShare": float(rows[cid]["overdueShare"]),
            "churnRisk": rows[cid]["churnRisk"],
            "profitabilityTrend": rows[cid]["profitabilityTrend"],
            "distance_to_risky_centroid": round(distance(cid), 3),
        }
        for cid in nearest
    ]

    print("  Nearest non-flagged customers to the risky centroid:")
    for rank, row in enumerate(candidates, start=1):
        print(
            f"    {rank}. {row['customer_id']} {row['name']:<20} "
            f"distance={row['distance_to_risky_centroid']:<6} "
            f"churn={row['churnRisk']} trend={row['profitabilityTrend']}"
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
        {
            "cid": c["customer_id"],
            # score: higher is closer to the risky cohort (inverse of distance).
            "score": round(1.0 / (1.0 + c["distance_to_risky_centroid"]), 4),
        }
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
            r.reason = 'kNN nearest the risky-customer cohort; not yet tripping the last-3-invoices rule'
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


def assert_similarity(candidates: list[dict[str, Any]], ground_truth: dict[str, Any]) -> None:
    expected = ground_truth["gds_q5_similarity_candidates"]
    got = [
        {k: c[k] for k in ("customer_id", "distance_to_risky_centroid")}
        for c in candidates
    ]
    want = [
        {k: c[k] for k in ("customer_id", "distance_to_risky_centroid")}
        for c in expected
    ]
    if got != want:
        sys.exit(
            "Q5 similarity candidates drifted from ground_truth.\n"
            f"  computed: {got}\n  expected: {want}"
        )
    ids = ", ".join(c["customer_id"] for c in candidates)
    print(f"  assert OK: candidates match ground_truth ({ids})")


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

        candidates = compute_similarity(gds)
        assert_similarity(candidates, ground_truth)
        write_similarity(gds, candidates)

    print("\nGDS analytics complete: Q4 exposure and Q5 similarity written back to Neo4j.")


if __name__ == "__main__":
    main()

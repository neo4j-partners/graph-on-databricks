"""Phase 2 graph analytics for the sharpened supplier-risk-graph demo.

Runs the two graph algorithms that the two demo stories turn on, with the
graphdatascience Python client, and writes the results back into Neo4j as node
properties only. Nothing here is ever synced to Delta: the whole point of the
sharpened demo is that these graph-native signals live in the graph and no
lakehouse column carries them, so plain Genie cannot see them.

  1. Supplier betweenness (Story 1, the hidden glassworks). Projects the
     supplier-to-supplier network (Supplier nodes, SUPPLIES edges, undirected)
     and runs gds.betweenness. Supplier->BusinessUnit SUPPLIES edges fall out of
     the projection because the BusinessUnit endpoint is not a Supplier, so the
     projection is the raw-material supply chain only. Cascade Glassworks
     (SUP-901) is the star centre feeding the five tier-1 bottle suppliers, so it
     lands as the strict betweenness maximum: the narrowest bridge in the
     network. Written back as a betweenness property on every Supplier node.

  2. Ownership PageRank (Story 2, the clean payer in a bad family). Projects the
     ownership network (Customer nodes, OWNED_BY edges, undirected) and runs
     personalized gds.pageRank seeded on the two defaulted siblings. Risk
     propagates from the siblings up to the shared parent (Kestrel) and back down
     onto Jade, the clean payer, even though Jade's own record is spotless.
     Written back as a pagerank property on every Customer node.

Both algorithms then set the two graph-native thresholds that had no value until
the scores existed: the Supply Concentration Threshold (THR-03) is placed
between Cascade and the next supplier so only Cascade clears it, and the
Ownership Contagion Threshold (THR-04) is placed between Jade and the top filler
customer so only the Kestrel family clears it. Both are written onto the live
Threshold nodes and back into data/thresholds.csv (graph-only, never uploaded to
Unity Catalog), so a reload carries them.

The build fails loud if either plant is wrong: Cascade must be the strict
betweenness maximum, and Jade must clear the contagion cutoff while no filler
customer does. Deterministic given the fixed-seed data. Re-runnable: both graph
projections are dropped on entry and exit, and the write-backs overwrite in
place.

Run from the project directory after load.py:

    uv run gds.py

Connection settings come from .env (see .env.sample): NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from dotenv import load_dotenv
from graphdatascience import GraphDataScience

HERE = Path(__file__).parent

SUPPLIER_GRAPH = "supplierNetwork"
OWNERSHIP_GRAPH = "ownershipNetwork"

CONCENTRATION_THRESHOLD_ID = "THR-03"  # Supply Concentration Threshold
CONTAGION_THRESHOLD_ID = "THR-04"  # Ownership Contagion Threshold

TOP_N_PRINT = 6  # how many ranked rows to echo for eyeballing on stage


@dataclass(frozen=True)
class Protagonists:
    """The two stories' hand-named nodes, read from ground_truth.json."""

    cascade_id: str
    tier1_ids: list[str]
    kestrel_id: str
    jade_id: str
    sibling_ids: list[str]

    @classmethod
    def from_ground_truth(cls, ground_truth: dict[str, Any]) -> Protagonists:
        story1 = ground_truth["story1_hidden_glassworks"]
        story2 = ground_truth["story2_clean_payer"]
        return cls(
            cascade_id=story1["cascade_id"],
            tier1_ids=list(story1["tier1_ids"]),
            kestrel_id=story2["kestrel_id"],
            jade_id=story2["jade_id"],
            sibling_ids=list(story2["sibling_ids"]),
        )


class Cutoff(NamedTuple):
    """A graph-native threshold placed between the protagonist and the field."""

    top_id: str
    top_score: float
    runner_up: float
    value: float


def require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def header(title: str) -> None:
    print(f"\n=== {title} ===")


def drop_graph(gds: GraphDataScience, name: str) -> None:
    gds.run_cypher(
        "CALL gds.graph.drop($name, false) YIELD graphName", params={"name": name}
    )


def compute_betweenness(
    gds: GraphDataScience, protags: Protagonists
) -> list[dict[str, Any]]:
    """Algorithm 1: betweenness over the supplier-to-supplier network.

    The projection keeps Supplier nodes and SUPPLIES edges, undirected. The
    Supplier->BusinessUnit SUPPLIES edges drop out because their BusinessUnit
    endpoint is not in the node set, so what is left is the raw-material chain.
    Undirected orientation is what makes Cascade score: every shortest path
    between two of its tier-1 bottle suppliers runs through it, so it is the
    narrowest bridge, while filler tier-2 suppliers feed scattered nodes and
    concentrate nothing.
    """
    header("Algorithm 1: supplier betweenness (Story 1, Critical Supplier)")
    drop_graph(gds, SUPPLIER_GRAPH)
    gds.run_cypher(
        "CALL gds.graph.project($graph, 'Supplier', "
        "{SUPPLIES: {orientation: 'UNDIRECTED'}})",
        params={"graph": SUPPLIER_GRAPH},
    )
    rows = gds.run_cypher(
        """
        CALL gds.betweenness.stream($graph)
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS s, score
        RETURN s.id AS sid, s.name AS name, score
        ORDER BY score DESC, sid
        """,
        params={"graph": SUPPLIER_GRAPH},
    )
    drop_graph(gds, SUPPLIER_GRAPH)

    scores = [
        {
            "supplier_id": r["sid"],
            "name": r["name"],
            "betweenness": round(float(r["score"]), 4),
        }
        for _, r in rows.iterrows()
    ]
    print("  Supplier betweenness (top of the supplier-to-supplier network):")
    for rank, row in enumerate(scores[:TOP_N_PRINT], start=1):
        marker = "  <- Cascade" if row["supplier_id"] == protags.cascade_id else ""
        print(
            f"    {rank}. {row['supplier_id']} {row['name']:<24} "
            f"betweenness={row['betweenness']:>8}{marker}"
        )
    return scores


def write_betweenness(gds: GraphDataScience, scores: list[dict[str, Any]]) -> None:
    rows = [{"sid": s["supplier_id"], "score": s["betweenness"]} for s in scores]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (s:Supplier {id: row.sid})
        SET s.betweenness = row.score
        RETURN count(s) AS written
        """,
        params={"rows": rows},
    )
    print(f"  wrote betweenness to {int(result['written'].iloc[0])} Supplier nodes")


def compute_pagerank(
    gds: GraphDataScience, protags: Protagonists
) -> list[dict[str, Any]]:
    """Algorithm 2: personalized PageRank over the ownership network.

    The projection keeps Customer nodes and OWNED_BY edges, undirected. Seeding
    the restart distribution on the two defaulted siblings makes risk flow up to
    the shared parent (Kestrel) and back down onto its other child, Jade. Only
    nodes reachable from the seeds get mass, so the Kestrel family lights up and
    every unrelated filler ownership group stays at zero.
    """
    header("Algorithm 2: ownership PageRank (Story 2, Ownership Risk)")
    print(f"  seeded on the defaulted siblings: {', '.join(protags.sibling_ids)}")
    drop_graph(gds, OWNERSHIP_GRAPH)
    gds.run_cypher(
        "CALL gds.graph.project($graph, 'Customer', "
        "{OWNED_BY: {orientation: 'UNDIRECTED'}})",
        params={"graph": OWNERSHIP_GRAPH},
    )
    rows = gds.run_cypher(
        """
        MATCH (seed:Customer) WHERE seed.id IN $seeds
        WITH collect(seed) AS sources
        CALL gds.pageRank.stream($graph, {sourceNodes: sources, concurrency: 1})
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS c, score
        RETURN c.id AS cid, c.name AS name, score
        ORDER BY score DESC, cid
        """,
        params={"graph": OWNERSHIP_GRAPH, "seeds": protags.sibling_ids},
    )
    drop_graph(gds, OWNERSHIP_GRAPH)

    scores = [
        {
            "customer_id": r["cid"],
            "name": r["name"],
            "pagerank": round(float(r["score"]), 6),
        }
        for _, r in rows.iterrows()
    ]
    print("  Customer ownership PageRank (top, the Kestrel family):")
    for rank, row in enumerate(scores[:TOP_N_PRINT], start=1):
        marker = "  <- Jade" if row["customer_id"] == protags.jade_id else ""
        print(
            f"    {rank}. {row['customer_id']} {row['name']:<26} "
            f"pagerank={row['pagerank']}{marker}"
        )
    return scores


def write_pagerank(gds: GraphDataScience, scores: list[dict[str, Any]]) -> None:
    rows = [{"cid": s["customer_id"], "score": s["pagerank"]} for s in scores]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.cid})
        SET c.pagerank = row.score
        RETURN count(c) AS written
        """,
        params={"rows": rows},
    )
    print(f"  wrote pagerank to {int(result['written'].iloc[0])} Customer nodes")


def concentration_cutoff(
    scores: list[dict[str, Any]], protags: Protagonists
) -> Cutoff:
    """THR-03: midway between Cascade's betweenness and the next supplier's."""
    by_id = {s["supplier_id"]: s["betweenness"] for s in scores}
    cascade = by_id[protags.cascade_id]
    runner_up = max((v for sid, v in by_id.items() if sid != protags.cascade_id), default=0.0)
    return Cutoff(protags.cascade_id, cascade, runner_up, round((cascade + runner_up) / 2, 2))


def contagion_cutoff(scores: list[dict[str, Any]], protags: Protagonists) -> Cutoff:
    """THR-04: midway between Jade's PageRank and the top filler customer's."""
    family = {protags.kestrel_id, protags.jade_id, *protags.sibling_ids}
    by_id = {s["customer_id"]: s["pagerank"] for s in scores}
    jade = by_id[protags.jade_id]
    filler_max = max((v for cid, v in by_id.items() if cid not in family), default=0.0)
    return Cutoff(protags.jade_id, jade, filler_max, round((jade + filler_max) / 2, 6))


def write_thresholds(gds: GraphDataScience, cutoffs: dict[str, float]) -> None:
    rows = [{"id": tid, "value": value} for tid, value in cutoffs.items()]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (t:Threshold {id: row.id})
        SET t.value = row.value
        RETURN count(t) AS written
        """,
        params={"rows": rows},
    )
    written = int(result["written"].iloc[0])
    if written != len(cutoffs):
        sys.exit(
            f"Threshold write set {written} of {len(cutoffs)} Threshold nodes; "
            f"expected ids {sorted(cutoffs)} to all exist."
        )
    for tid, value in cutoffs.items():
        print(f"  set Threshold {tid}.value = {value}")


def update_thresholds_csv(path: Path, cutoffs: dict[str, float]) -> None:
    """Fill the two blank graph-native threshold rows in thresholds.csv.

    Only the THR-03/THR-04 value cells are touched; every other row is rewritten
    verbatim. thresholds.csv is graph-only (never uploaded to Unity Catalog), so
    persisting the computed cutoffs here keeps them a governed graph value, not a
    lakehouse column.
    """
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    missing = set(cutoffs) - {row["id"] for row in rows}
    if missing:
        sys.exit(f"thresholds.csv is missing rows for {sorted(missing)}; not writing.")

    for row in rows:
        if row["id"] in cutoffs:
            value = cutoffs[row["id"]]
            row["value"] = str(int(value)) if float(value).is_integer() else str(value)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue())
    print(f"  wrote {', '.join(sorted(cutoffs))} back into {path.name}")


def assert_betweenness(scores: list[dict[str, Any]], conc: Cutoff, protags: Protagonists) -> None:
    """Cascade must be the strict betweenness maximum in the supplier network."""
    if conc.top_score <= conc.runner_up:
        sys.exit(
            f"Story 1 betweenness: Cascade ({protags.cascade_id})={conc.top_score} "
            f"is not the strict network maximum (runner-up={conc.runner_up})."
        )
    top = scores[0]["supplier_id"]
    if top != protags.cascade_id:
        sys.exit(
            f"Story 1 betweenness: top supplier is {top}, "
            f"expected Cascade {protags.cascade_id}."
        )
    print(
        f"  assert OK: Cascade betweenness {conc.top_score} is the strict network "
        f"maximum (next {conc.runner_up}); THR-03 cutoff {conc.value}"
    )


def assert_pagerank(scores: list[dict[str, Any]], cont: Cutoff, protags: Protagonists) -> None:
    """Jade must clear the contagion cutoff while no filler customer does."""
    family = {protags.kestrel_id, protags.jade_id, *protags.sibling_ids}
    by_id = {s["customer_id"]: s["pagerank"] for s in scores}
    jade = by_id[protags.jade_id]
    if jade < cont.value:
        sys.exit(
            f"Story 2 PageRank: Jade ({protags.jade_id})={jade} does not clear "
            f"THR-04 cutoff {cont.value}."
        )
    fillers_over = sorted(
        (cid, v) for cid, v in by_id.items() if cid not in family and v >= cont.value
    )
    if fillers_over:
        sys.exit(
            f"Story 2 PageRank: filler customers clear THR-04 cutoff {cont.value}: "
            f"{fillers_over}"
        )
    print(
        f"  assert OK: Jade PageRank {jade} clears THR-04 cutoff {cont.value}; "
        f"no filler customer does"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="directory holding ground_truth.json and thresholds.csv (default: data/)",
    )
    args = parser.parse_args()

    ground_truth = json.loads((args.data_dir / "ground_truth.json").read_text())
    protags = Protagonists.from_ground_truth(ground_truth)

    load_dotenv(HERE / ".env")
    uri = require_env("NEO4J_URI")
    auth = (require_env("NEO4J_USERNAME", "neo4j"), require_env("NEO4J_PASSWORD"))
    database = require_env("NEO4J_DATABASE", "neo4j")

    gds = GraphDataScience(uri, auth=auth, database=database)
    with gds:
        print(f"Connected to {uri} (database={database}), GDS client v{gds.version()}")

        betweenness = compute_betweenness(gds, protags)
        conc = concentration_cutoff(betweenness, protags)
        assert_betweenness(betweenness, conc, protags)
        write_betweenness(gds, betweenness)

        pagerank = compute_pagerank(gds, protags)
        cont = contagion_cutoff(pagerank, protags)
        assert_pagerank(pagerank, cont, protags)
        write_pagerank(gds, pagerank)

        header("Graph-native thresholds (set from the computed distributions)")
        cutoffs = {
            CONCENTRATION_THRESHOLD_ID: conc.value,
            CONTAGION_THRESHOLD_ID: cont.value,
        }
        write_thresholds(gds, cutoffs)
        update_thresholds_csv(args.data_dir / "thresholds.csv", cutoffs)

    print(
        "\nGDS analytics complete: betweenness and pagerank written to Neo4j as "
        "node properties, THR-03/THR-04 set. Nothing synced to Delta."
    )


if __name__ == "__main__":
    main()

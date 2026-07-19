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
     projection is the raw-material supply chain only. The network is several
     webbed regional clusters joined to each other by a number of bridges, with
     Cascade Glassworks (SUP-901) sitting as a narrow waist between a wide
     feedstock base and the processor tier that feeds the bottle makers. Removing
     Cascade leaves the network in one piece, so whatever score it takes it takes
     by position rather than by being the only way across. It is NOT the most
     connected supplier, and counting connections finds someone else entirely.
     Written back as a betweenness property on every Supplier node.

  2. Weighted ownership PageRank (Story 2, the clean payer in a bad group).
     Projects the ownership network (Customer nodes, OWNED_BY edges, undirected)
     with the ownership stake as a relationship weight, and runs personalized
     gds.pageRank seeded on every defaulted customer in the book. Influence
     splits by the size of each stake, so nearness counts for nothing on its own:
     Jade sits three hops from the four failures in its group and still takes the
     top score, because every stake on the path is a controlling one, while the
     accounts sitting next door to a default hold only a few percent of it.
     Written back as a pagerank property on every Customer node.

Both algorithms then set the two graph-native thresholds that had no value until
the scores existed, and they are set by opposite logic. The Supply Concentration
Threshold (THR-03) resolves a governed percentile, fixed in the generator before
any score existed, against the distribution this run produced; it catches a
cohort, and how many suppliers are in it is an output. The Ownership Contagion
Threshold (THR-04) is still placed between Jade and the next trading customer so
only Jade clears it, because Story 2 is out of scope. Do not "align" THR-04 to
THR-03: that is a redesign of Story 2 rather than a tidy-up. Both are written
onto the live Threshold nodes and back into data/thresholds.csv (graph-only,
never uploaded to Unity Catalog), so a reload carries them.

Two knowledge-layer bindings follow, both from the same computed values. The
cutoffs are backfilled onto RULE-05 and RULE-06 as an inline threshold property,
so the graph-native rules carry their number the way the four column-findable
rules already do. And the governing term name is written onto every node that
carries the metric, so the governed vocabulary travels with the score into any
result set. Neither materializes a classification: every Supplier carries the
same term string whether or not it clears the cutoff.

The build fails loud if either plant is wrong: Cascade must clear THR-03 in a
cohort with more than one member, and Jade must be the top trading customer by
weighted contagion. Where Cascade ranks is reported and is not a pass
condition. PageRank convergence is checked before its scores are used, since
the contagion cutoff is placed from them to six decimal places. Deterministic
given the fixed-seed data. Re-runnable: both graph
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
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from dotenv import load_dotenv
from graphdatascience import GraphDataScience

# THR-03's governed input. It is imported rather than restated so there is one
# place it can be changed and one commit that shows when it was fixed. The
# generator is import-safe: everything below its main guard is data.
from generate_data import (
    EVALUATED_AT,
    RULE_VERSION,
    SUPPLY_CONCENTRATION_PERCENTILE,
)

HERE = Path(__file__).parent

SUPPLIER_GRAPH = "supplierNetwork"
OWNERSHIP_GRAPH = "ownershipNetwork"

CONCENTRATION_THRESHOLD_ID = "THR-03"  # Supply Concentration Threshold
CONTAGION_THRESHOLD_ID = "THR-04"  # Ownership Contagion Threshold

CONCENTRATION_RULE_ID = "RULE-05"  # Critical Supplier Rule
CONTAGION_RULE_ID = "RULE-06"  # Ownership Risk Rule

DELINQUENT_TERM_ID = "TERM-03"  # Delinquent Customer, a CLASSIFIED_AS edge

CRITICAL_SUPPLIER_TERM = "Critical Supplier"  # TERM-05, governs Supplier.betweenness
OWNERSHIP_RISK_TERM = "Ownership Risk"  # TERM-06, governs Customer.pagerank

TOP_N_PRINT = 6  # how many ranked rows to echo for eyeballing on stage
# How deep report_degree_overlap compares the two rankings. Wider than
# TOP_N_PRINT because the question is whether the measures agree at all, not
# what fits on a slide, and narrow enough that an overlap is a real coincidence
# rather than an artifact of comparing most of the network with itself.
TOP_N_OVERLAP = 8

# Weighted personalized PageRank config, shared by the stats and stream calls so
# the convergence check describes the run the scores actually come from. The
# ownership DAG runs several levels deep and the stakes are lopsided, so mass
# takes far more than the default 20 iterations to settle; at 20 it had not
# converged and THR-04 would have been read off moving numbers. The keys are the
# GDS 2.x config names, so this dict can be splatted straight into a client call.
# dampingFactor is spelled out rather than inherited: it is GDS's default, but the
# demo's placement of THR-04 depends on it, so it is pinned here where a change is
# visible. concurrency lives in this dict for the same reason and is the one entry
# that must: a tolerance-based run accumulates mass in whatever order the threads
# finish, so a stats call and a stream call at different concurrencies are not the
# same run, which is exactly what this dict exists to prevent.
PAGERANK_CONFIG = {
    "relationshipWeightProperty": "ownershipPct",
    "dampingFactor": 0.85,
    "maxIterations": 200,
    "tolerance": 1e-9,
    "concurrency": 1,
}


@dataclass(frozen=True)
class Protagonists:
    """The two stories' hand-named nodes, read from ground_truth.json."""

    cascade_id: str
    tier1_ids: list[str]
    kestrel_id: str
    jade_id: str
    group_ids: list[str]
    seed_ids: list[str]

    @classmethod
    def from_ground_truth(cls, ground_truth: dict[str, Any]) -> Protagonists:
        story1 = ground_truth["story1_hidden_glassworks"]
        story2 = ground_truth["story2_clean_payer"]
        return cls(
            cascade_id=story1["cascade_id"],
            tier1_ids=list(story1["tier1_ids"]),
            kestrel_id=story2["kestrel_id"],
            jade_id=story2["jade_id"],
            group_ids=list(story2["group_ids"]),
            seed_ids=list(story2["seed_ids"]),
        )


class Score(NamedTuple):
    """One node's score from one of the two algorithms.

    Both algorithms produce the same shape, a node id, a display name and a
    number, and everything downstream of them (the cutoff placement, the
    assertions, the write-backs, the stage printing) only ever needs those three
    fields. Carrying them as dicts meant two parallel vocabularies for identical
    data, supplier_id/betweenness against customer_id/pagerank, which forced the
    cutoff and assertion logic to be written twice. The field is called `value`
    rather than the metric name for that reason: what it means is fixed by which
    algorithm produced the list, not by the key it is read under.
    """

    node_id: str
    name: str
    value: float


class Cutoff(NamedTuple):
    """A graph-native threshold placed between the protagonist and the field."""

    top_id: str
    top_score: float
    runner_up: float
    value: float


class Cohort(NamedTuple):
    """A governed percentile, resolved against a run's score distribution.

    Distinct from Cutoff because the two are placed by opposite logic and mixing
    them is how a percentile quietly becomes a one-winner threshold again. A
    Cutoff is placed relative to a named node. A Cohort is placed relative to the
    field and then asked who it caught, which is why `members` is a list and
    nothing in it is required to have length one.
    """

    percentile: int
    value: float
    members: list[Score]


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


def check_supplier_projection(gds: GraphDataScience, relationship_count: int) -> None:
    """Fail the build if the projection is not exactly the supplier-to-supplier chain.

    compute_betweenness claims the Supplier->BusinessUnit SUPPLIES edges drop out
    of the projection because their BusinessUnit endpoint is not in the node set.
    Nothing tested that, and it is the difference between measuring the raw-material
    chain and measuring the customer-facing fan-out. THR-03 is placed off these
    scores, so a single supplier edge gained or lost moves a threshold the build
    then asserts against. UNDIRECTED stores each relationship in both directions,
    so GDS reports twice the number of source rows.
    """
    rows = gds.run_cypher(
        """
        MATCH (:Supplier)-[r:SUPPLIES]->(:Supplier)
        RETURN count(r) AS supplierEdges
        """
    )
    supplier_edges = int(rows["supplierEdges"].iloc[0])
    expected = supplier_edges * 2
    if relationship_count != expected:
        sys.exit(
            f"Supplier projection holds {relationship_count} relationships; expected "
            f"{expected}, twice the {supplier_edges} Supplier->Supplier SUPPLIES edges "
            f"in the database. Either a Supplier->BusinessUnit edge reached the "
            f"projection or the supply network changed shape."
        )
    print(f"  projection: {supplier_edges} supplier-to-supplier SUPPLIES edges")


def compute_betweenness(gds: GraphDataScience, protags: Protagonists) -> list[Score]:
    """Algorithm 1: betweenness over the supplier-to-supplier network.

    The projection keeps Supplier nodes and SUPPLIES edges, undirected. The
    Supplier->BusinessUnit SUPPLIES edges drop out because their BusinessUnit
    endpoint is not in the node set, so what is left is the raw-material chain.
    Cascade scores because of where it sits in that chain: a wide feedstock base
    on one side, the processor tier and the bottle makers on the other, and no
    short way around it between them. Removing it does not disconnect the
    network, which is what makes the score a statement about position rather
    than about severance. The busiest suppliers sit inside the regional clusters,
    where the web routes traffic around them, so they win any count of
    connections and lose this.
    """
    header("Algorithm 1: supplier betweenness (Story 1, Critical Supplier)")
    drop_graph(gds, SUPPLIER_GRAPH)
    # UNDIRECTED is load-bearing: do not "correct" it to match edge semantics.
    # SUPPLIES runs the way the material does, so the feedstock edges point into
    # Cascade and the processor edges point out of it. A NATURAL (or REVERSE)
    # projection therefore sees only one side of the waist and collapses
    # Cascade's betweenness. The claim is that Cascade sits between the upstream
    # and downstream populations, and only an undirected projection can see both
    # at once. Changing this silently deletes Story 1.
    projection = gds.run_cypher(
        "CALL gds.graph.project($graph, 'Supplier', "
        "{SUPPLIES: {orientation: 'UNDIRECTED'}}) "
        "YIELD nodeCount, relationshipCount",
        params={"graph": SUPPLIER_GRAPH},
    )
    node_count = int(projection["nodeCount"].iloc[0])
    try:
        check_supplier_projection(gds, int(projection["relationshipCount"].iloc[0]))
        # samplingSize is spelled out for the same reason PAGERANK_CONFIG pins
        # dampingFactor: at the node count this is GDS's default and the result is
        # exact Brandes over every source node, but the default is a value the
        # library chooses, and THR-03 is resolved off these scores to two decimals.
        # concurrency is pinned alongside it for symmetry with PAGERANK_CONFIG.
        # Exact Brandes is already deterministic, so unlike the PageRank case this
        # costs nothing and proves nothing; do not generalize the reasoning.
        # Anything below the node count silently switches to sampled betweenness,
        # which is non-deterministic without a samplingSeed and would put the
        # cutoff on numbers that move between runs.
        rows = gds.run_cypher(
            """
            CALL gds.betweenness.stream($graph,
                 {samplingSize: $samplingSize, concurrency: 1})
            YIELD nodeId, score
            WITH gds.util.asNode(nodeId) AS s, score
            RETURN s.id AS supplierId, s.name AS name, score
            ORDER BY score DESC, supplierId
            """,
            params={"graph": SUPPLIER_GRAPH, "samplingSize": node_count},
        )
    finally:
        drop_graph(gds, SUPPLIER_GRAPH)

    scores = [
        Score(r["supplierId"], r["name"], round(float(r["score"]), 4))
        for _, r in rows.iterrows()
    ]
    print("  Supplier betweenness (top of the supplier-to-supplier network):")
    for rank, row in enumerate(scores[:TOP_N_PRINT], start=1):
        marker = "  <- Cascade" if row.node_id == protags.cascade_id else ""
        print(
            f"    {rank}. {row.node_id} {row.name:<24} "
            f"betweenness={row.value:>8}{marker}"
        )
    return scores


def write_betweenness(gds: GraphDataScience, scores: list[Score]) -> None:
    rows = [{"sid": s.node_id, "score": s.value} for s in scores]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (s:Supplier {id: row.sid})
        SET s.betweenness = row.score
        RETURN count(s) AS written
        """,
        params={"rows": rows},
    )
    written = int(result["written"].iloc[0])
    if written != len(rows):
        sys.exit(
            f"Betweenness write set {written} of {len(rows)} Supplier nodes; every "
            f"supplier in the projection must exist under MATCH (s:Supplier {{id}})."
        )
    print(f"  wrote betweenness to {written} Supplier nodes")


def write_critical_supplier_labels(gds: GraphDataScience, conc: Cohort) -> None:
    """Materialize CLASSIFIED_AS edges from the THR-03 cohort to TERM-05.

    This simulates what a production deployment does on a schedule: a batch GDS
    job scores the supply network, compares each score against the governed
    threshold, and writes the classification back so downstream systems can read
    a label instead of recomputing centrality per question. Nobody runs Brandes
    at query time when a risk officer asks who is critical.

    Until now the two graph-native terms carried no CLASSIFIED_AS edges at all,
    on the reasoning that they are resolved live from the score properties and
    bound to their implementation through SCORED_BY. That reasoning is sound and
    the re-probe still killed it. Four terms in the graph are findable by
    classification edge and two are not, so an agent doing schema discovery
    learns the pattern from the majority, applies it to Critical Supplier, gets
    zero rows, and truthfully reports that the system does not classify critical
    suppliers. The definition, the rule, and the threshold were all present and
    reachable. Nothing walked to them, because nothing needed to until the query
    came back empty, and by then the agent had its answer.

    **The cohort is derived and never enumerated.** Membership comes from the
    resolved cutoff, so the edges are an output of the run in exactly the way
    the cutoff is. A literal list of supplier ids here would convert this from a
    materialized computation into the plant CONTRACT.md section 8 bans, and it
    would be the same betrayal whether or not the ids happened to be right.

    **On the Delta write-back, which looks like leakage and is not.** These
    edges do flow into the `classifications` gold table, because
    CLASSIFICATIONS_SPEC in `upload.py` selects every CLASSIFIED_AS edge. That
    is the intended alternative surfacing pattern and not an oversight. The
    protection is that the gold tables are never attached to the Genie space,
    which `banned_tables` in `guard.py` enforces against the space's declared
    data sources on every run. Do not add a term filter to CLASSIFICATIONS_SPEC
    to "fix" this: the filter would restore the empty-result failure above while
    looking like a safety improvement.
    """
    reason = (
        f"supply betweenness at or above the {conc.percentile}th percentile "
        f"cutoff of {conc.value}"
    )
    result = gds.run_cypher(
        """
        MATCH (t:BusinessTerm {name: $term})
        UNWIND $ids AS sid
        MATCH (s:Supplier {id: sid})
        MERGE (s)-[r:CLASSIFIED_AS]->(t)
        SET r.reason = $reason,
            r.evaluatedAt = datetime($evaluatedAt),
            r.ruleVersion = $ruleVersion
        RETURN count(r) AS written
        """,
        params={
            "term": CRITICAL_SUPPLIER_TERM,
            "ids": [s.node_id for s in conc.members],
            "reason": reason,
            "evaluatedAt": EVALUATED_AT,
            "ruleVersion": RULE_VERSION,
        },
    )
    written = int(result["written"].iloc[0])
    if written != len(conc.members):
        sys.exit(
            f"Critical Supplier labelling wrote {written} of "
            f"{len(conc.members)} CLASSIFIED_AS edges. Every cohort member must "
            f"exist as a Supplier node and '{CRITICAL_SUPPLIER_TERM}' must exist "
            f"as a BusinessTerm, or Beat 3 resolves to an empty result."
        )
    print(
        f"  labelled {written} supplier(s) as '{CRITICAL_SUPPLIER_TERM}' "
        f"(CLASSIFIED_AS, cohort resolved from the {conc.percentile}th percentile)"
    )


def check_seed_ids(gds: GraphDataScience, protags: Protagonists) -> None:
    """Fail the build if any ground-truth seed id does not match a Customer.

    The personalization vector is built by `MATCH (seed:Customer) WHERE seed.id IN
    $seeds`, which silently yields a shorter list when an id is stale. The run
    still converges, so a dropped seed changes the scores THR-04 is placed from
    without failing anything. Check the count up front instead.
    """
    rows = gds.run_cypher(
        """
        MATCH (seed:Customer) WHERE seed.id IN $seeds
        RETURN count(seed) AS matched
        """,
        params={"seeds": protags.seed_ids},
    )
    matched = int(rows["matched"].iloc[0])
    if matched != len(protags.seed_ids):
        sys.exit(
            f"Seed match found {matched} of {len(protags.seed_ids)} Customer nodes; "
            f"expected ids {sorted(protags.seed_ids)} to all exist. A stale seed id "
            f"would silently change the personalization vector."
        )


def check_pagerank_convergence(gds: GraphDataScience, protags: Protagonists) -> None:
    """Fail the build if personalized PageRank did not converge.

    The stream below yields only nodeId and score, so didConverge is discarded
    there. THR-04 is then derived from those scores to six decimal places and
    assert_pagerank makes the build pass or fail on it, so the cutoff must never
    be read off an unstable run. stats mode runs the same configuration and
    reports convergence without touching the graph.
    """
    rows = gds.run_cypher(
        """
        MATCH (seed:Customer) WHERE seed.id IN $seeds
        WITH collect(seed) AS sources
        CALL gds.pageRank.stats($graph, {
            sourceNodes: sources,
            relationshipWeightProperty: $relationshipWeightProperty,
            dampingFactor: $dampingFactor,
            maxIterations: $maxIterations,
            tolerance: $tolerance,
            concurrency: $concurrency
        })
        YIELD didConverge, ranIterations
        RETURN didConverge, ranIterations
        """,
        params={
            "graph": OWNERSHIP_GRAPH,
            "seeds": protags.seed_ids,
            **PAGERANK_CONFIG,
        },
    )
    iterations = int(rows["ranIterations"].iloc[0])
    if not bool(rows["didConverge"].iloc[0]):
        sys.exit(
            f"Story 2 PageRank did not converge after {iterations} iterations, so "
            f"THR-04 would be placed from unstable scores. Raise maxIterations."
        )
    print(f"  converged after {iterations} iterations")


def compute_pagerank(gds: GraphDataScience, protags: Protagonists) -> list[Score]:
    """Algorithm 2: weighted personalized PageRank over the ownership network.

    The projection keeps Customer nodes and OWNED_BY edges, undirected, carrying
    the ownership stake as a relationship weight. Every defaulted customer in the
    book seeds the restart distribution, not just one group's, so the score is
    how much failure actually reaches an account rather than how near the nearest
    failure happens to be.

    The weight is the whole point. Influence splits by the size of each stake, so
    a default next door held at three percent transmits almost nothing, while
    four defaults three levels away held through controlling stakes accumulate
    into the top score. That is Jade. No hop count and no GROUP BY over these
    edges reaches the same answer, which is why the metric has to be a graph
    computation rather than a column.
    """
    header("Algorithm 2: weighted ownership PageRank (Story 2, Ownership Risk)")
    print(f"  seeded on all {len(protags.seed_ids)} defaulted customers")
    check_seed_ids(gds, protags)
    drop_graph(gds, OWNERSHIP_GRAPH)
    # UNDIRECTED is load-bearing: do not "correct" it to match edge semantics.
    # The four defaulters sit under Harbour and Tern while Jade sits under
    # Kestrel, so contagion reaches Jade only by travelling UP to the shared
    # parent and back DOWN. Under NATURAL or REVERSE orientation Jade scores
    # exactly 0.0 and Story 2 is destroyed. An UNDIRECTED projection materializes
    # a synthetic reverse edge reusing the same ownershipPct value; that is
    # intentional. On the reverse direction the number is a conductance ratio
    # governing how much failure flows back up a stake, not a literal claim that
    # the child owns that share of the parent.
    gds.run_cypher(
        "CALL gds.graph.project($graph, 'Customer', "
        "{OWNED_BY: {orientation: 'UNDIRECTED', properties: ['ownershipPct']}})",
        params={"graph": OWNERSHIP_GRAPH},
    )
    try:
        check_pagerank_convergence(gds, protags)
        rows = gds.run_cypher(
            """
            MATCH (seed:Customer) WHERE seed.id IN $seeds
            WITH collect(seed) AS sources
            CALL gds.pageRank.stream($graph, {
                sourceNodes: sources,
                relationshipWeightProperty: $relationshipWeightProperty,
                dampingFactor: $dampingFactor,
                maxIterations: $maxIterations,
                tolerance: $tolerance,
                concurrency: $concurrency
            })
            YIELD nodeId, score
            WITH gds.util.asNode(nodeId) AS c, score
            RETURN c.id AS customerId, c.name AS name, score
            ORDER BY score DESC, customerId
            """,
            params={
                "graph": OWNERSHIP_GRAPH,
                "seeds": protags.seed_ids,
                **PAGERANK_CONFIG,
            },
        )
    finally:
        drop_graph(gds, OWNERSHIP_GRAPH)

    scores = [
        Score(r["customerId"], r["name"], round(float(r["score"]), 6))
        for _, r in rows.iterrows()
    ]
    return scores


def print_top_trading(
    scores: list[Score], protags: Protagonists, trading: set[str]
) -> None:
    """Echo the ranking the story is actually about.

    The raw top of the distribution is the defaulted customers themselves and the
    holdcos that own them, which is arithmetic, not a finding. What the demo
    turns on is the ranking among customers still trading, where Jade is first.
    """
    ranked = [s for s in scores if s.node_id in trading]
    print("  Weighted ownership contagion, trading customers only:")
    for rank, row in enumerate(ranked[:TOP_N_PRINT], start=1):
        marker = "  <- Jade" if row.node_id == protags.jade_id else ""
        print(
            f"    {rank}. {row.node_id} {row.name:<26} pagerank={row.value}{marker}"
        )


def write_pagerank(gds: GraphDataScience, scores: list[Score]) -> None:
    rows = [{"cid": s.node_id, "score": s.value} for s in scores]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.cid})
        SET c.pagerank = row.score
        RETURN count(c) AS written
        """,
        params={"rows": rows},
    )
    written = int(result["written"].iloc[0])
    if written != len(rows):
        sys.exit(
            f"PageRank write set {written} of {len(rows)} Customer nodes; every "
            f"customer in the projection must exist under MATCH (c:Customer {{id}})."
        )
    print(f"  wrote pagerank to {written} Customer nodes")


def require_score(by_id: dict[str, float], node_id: str, what: str) -> float:
    """Look up a protagonist's score, failing loud the way everything else does."""
    if node_id not in by_id:
        sys.exit(
            f"{what} {node_id} is missing from the computed scores; ground_truth.json "
            f"and the loaded graph disagree."
        )
    return by_id[node_id]


def score_index(scores: list[Score]) -> dict[str, float]:
    """The scores keyed by node id, the shape every lookup below wants."""
    return {s.node_id: s.value for s in scores}


def place_cutoff(
    scores: list[Score],
    top_id: str,
    what: str,
    digits: int,
    eligible: set[str] | None = None,
) -> Cutoff:
    """Place a threshold midway between the protagonist and the next node down.

    THR-04 only. This used to place both graph-native thresholds and now places
    one, because THR-03 resolves a governed percentile instead: see
    concentration_cutoff for why placing a threshold relative to the node it is
    going to catch is a post-hoc threshold however principled the arithmetic.

    That reasoning applies to THR-04 too and is deliberately not acted on here.
    Story 2 is out of scope, and converting it to a percentile by analogy would
    be a redesign of Story 2 dressed as consistency. It needs that decision
    reopened rather than worked around.

    `digits` is 6 rather than 2 because the PageRank scores are small enough that
    rounding to 2 would collapse the cutoff onto Jade's own score. `eligible` is
    the trading set, because the holdcos outscore Jade by construction and are
    not counterparties the rule can act on.
    """
    by_id = score_index(scores)
    top = require_score(by_id, top_id, what)
    runner_up = max(
        (
            value
            for node_id, value in by_id.items()
            if node_id != top_id and (eligible is None or node_id in eligible)
        ),
        default=0.0,
    )
    return Cutoff(top_id, top, runner_up, round((top + runner_up) / 2, digits))


def concentration_cutoff(scores: list[Score]) -> Cohort:
    """THR-03: the governed percentile, resolved against this run's distribution.

    The percentile is the input and it is fixed in the generator before any score
    exists. Resolving it is the only part that cannot be known in advance, and
    that is all this does.

    Nothing here takes a protagonist, and the missing parameter is the point. The
    previous version placed the cutoff midway between Cascade's score and the
    next supplier's, which meant the threshold was defined in terms of the
    supplier it was going to catch. That is a post-hoc threshold however
    principled the arithmetic, and it also made the answer a single name by
    construction. A percentile catches whoever is in the tail, and how many that
    is is a fact about the network rather than a decision.
    """
    ranked = sorted(s.value for s in scores)
    # Nearest-rank: the smallest score with at least P percent of the field at or
    # below it. No interpolation, so the cutoff is always a score some supplier
    # actually has and "at or above the 95th percentile" means what a risk
    # committee reading it would think it means.
    index = math.ceil(SUPPLY_CONCENTRATION_PERCENTILE / 100 * len(ranked)) - 1
    value = round(ranked[max(index, 0)], 2)
    members = [s for s in scores if s.value >= value]
    return Cohort(SUPPLY_CONCENTRATION_PERCENTILE, value, members)


def trading_customers(gds: GraphDataScience) -> set[str]:
    """Customers that actually trade, so the ones Ownership Risk can apply to.

    TERM-06 governs an active customer, and a holding company with no invoices
    has no receivable to act on. Kestrel and the two intermediate holdcos score
    higher than Jade by construction, because they sit between her and the
    failures, but none of them is a trading counterparty. Filtering on having an
    invoice is what the term already says, not a special case carved out for the
    demo.

    RULE-06 and TERM-06 both require a customer that is neither defaulted nor
    delinquent, so both clauses are implemented here: the null defaultedPeriod
    covers the first, and the absence of a CLASSIFIED_AS edge to TERM-03
    (Delinquent Customer) covers the second. The delinquency clause changes no
    outcome on the fixed-seed data, since neither Jade nor the runner-up is
    delinquent; it only narrows the ranked set so the code matches the governed
    definition rather than half of it.
    """
    rows = gds.run_cypher(
        """
        MATCH (c:Customer)
        WHERE c.defaultedPeriod IS NULL
          AND EXISTS { (c)-[:HAS_INVOICE]->(:Invoice) }
          AND NOT EXISTS {
              (c)-[:CLASSIFIED_AS]->(:BusinessTerm {id: $delinquentTerm})
          }
        RETURN c.id AS cid
        """,
        params={"delinquentTerm": DELINQUENT_TERM_ID},
    )
    trading = set(rows["cid"])
    if not trading:
        sys.exit(
            "No trading customers found: every customer is defaulted, delinquent, "
            "or has no invoice. The Story 2 assertion would pass having checked "
            "nothing, so the build stops here instead."
        )

    # Landmine assert: the filter has to have actually excluded somebody.
    #
    # An empty result is caught above, but the dangerous failure is the opposite
    # shape: a filter that matches every customer looks identical to a filter
    # that works, and it would silently promote the holdcos back into the ranked
    # set. Kestrel and the two intermediate holdcos outscore Jade by
    # construction, so if they are not filtered out the demo names a holding
    # company with no receivable and Story 2 collapses without anything failing.
    #
    # Stated as a relationship rather than a count, per contract section 9: some
    # customers must be excluded, not a specific number of them.
    total = int(gds.run_cypher("MATCH (c:Customer) RETURN count(c) AS n")["n"].iloc[0])
    excluded = total - len(trading)
    if excluded <= 0:
        sys.exit(
            f"The trading-customer filter excluded nobody: {total} customers in, "
            f"{len(trading)} out. It has silently stopped working, which looks "
            f"exactly like it working. The holdcos would re-enter the ranking."
        )
    print(f"  trading customers: {len(trading)} of {total} ({excluded} excluded)")
    return trading


def contagion_cutoff(
    scores: list[Score], protags: Protagonists, trading: set[str]
) -> Cutoff:
    """THR-04: midway between Jade's PageRank and the next trading customer's."""
    return place_cutoff(scores, protags.jade_id, "Jade", digits=6, eligible=trading)


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


def write_rule_thresholds(gds: GraphDataScience, cutoffs: dict[str, float]) -> None:
    """Backfill the inline threshold on the two graph-native BusinessRule nodes.

    RULE-05 and RULE-06 ship with a null threshold, because the number does not
    exist until the algorithms above have run. The four column-findable rules
    carry theirs inline, which is why a model standing on one of those rules can
    read the cutoff without traversing anywhere. Setting the same property here
    gives the graph-native rules the same forward path to the number, matching
    THR-03 and THR-04 exactly since both come from the same Cutoff values.
    """
    rows = [{"id": rid, "value": value} for rid, value in cutoffs.items()]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (r:BusinessRule {id: row.id})
        SET r.threshold = row.value
        RETURN count(r) AS written
        """,
        params={"rows": rows},
    )
    written = int(result["written"].iloc[0])
    if written != len(cutoffs):
        sys.exit(
            f"Rule threshold write set {written} of {len(cutoffs)} BusinessRule "
            f"nodes; expected ids {sorted(cutoffs)} to all exist."
        )
    for rid, value in cutoffs.items():
        print(f"  set BusinessRule {rid}.threshold = {value}")


def write_governed_terms(gds: GraphDataScience) -> None:
    """Name the governing BusinessTerm on every node that carries the metric.

    The four column-findable terms reach a model unbidden, because CLASSIFIED_AS
    puts the term name into any result set that touches the node. The two
    graph-native terms are denied that edge by design, so nothing carries the
    governed vocabulary back to a model that computed its answer from
    betweenness or pagerank, and it narrates in its own words instead.

    These properties name the TERM that governs the metric, not which nodes
    qualify under it. Every Supplier carries the same string whether or not it
    clears THR-03, and every Customer whether or not it clears THR-04, so no
    classification is materialized and the contract's "never a materializable
    row" guarantee holds. Neo4j only: nothing here is ever synced to Delta.
    """
    suppliers = gds.run_cypher(
        """
        MATCH (s:Supplier)
        SET s.betweennessGovernedTerm = $term
        RETURN count(s) AS written
        """,
        params={"term": CRITICAL_SUPPLIER_TERM},
    )
    print(
        f"  bound '{CRITICAL_SUPPLIER_TERM}' to betweenness on "
        f"{int(suppliers['written'].iloc[0])} Supplier nodes"
    )

    customers = gds.run_cypher(
        """
        MATCH (c:Customer)
        SET c.pagerankGovernedTerm = $term
        RETURN count(c) AS written
        """,
        params={"term": OWNERSHIP_RISK_TERM},
    )
    print(
        f"  bound '{OWNERSHIP_RISK_TERM}' to pagerank on "
        f"{int(customers['written'].iloc[0])} Customer nodes"
    )


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

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {', '.join(sorted(cutoffs))} back into {path.name}")


def check_three_legs(gds: GraphDataScience, protags: Protagonists) -> None:
    """Beat 3's three legs resolve against the loaded graph.

    CONTRACT.md section 4 says the graph grounds its answer through exactly
    three capabilities, and section 7 asserts each of them resolves. Nothing
    checked that until now. This file asserted the scores it computes, but
    nothing walked the ontology to confirm the walk arrives anywhere, and leg 1
    is the load-bearing leg of the load-bearing claim: if TERM-05 does not reach
    RULE-05 and THR-03, Beat 3 opens on a broken query.

    This is the mechanical half only. That the three produce three DISTINCT
    visible outputs on a screen cannot be asserted by a build and is a re-probe
    phase exit check instead.
    """
    header("Beat 3: the three legs resolve")

    # Leg 1, definition. The full authored walk, term to rule to threshold,
    # which is the path Beat 3 opens on. Matched by term NAME rather than by id,
    # because the name is what a question arrives as.
    leg1 = gds.run_cypher(
        """
        MATCH (t:BusinessTerm {name: $term})-[:DEFINED_BY]->(r:BusinessRule)
        OPTIONAL MATCH (r)-[:USES_THRESHOLD]->(h:Threshold)
        RETURN t.definition AS definition, r.id AS rule_id,
               r.expression AS expression, h.id AS threshold_id,
               h.basis AS basis, h.value AS value
        """,
        params={"term": CRITICAL_SUPPLIER_TERM},
    )
    if leg1.empty:
        sys.exit(
            f"Leg 1 does not resolve: no BusinessTerm named "
            f"'{CRITICAL_SUPPLIER_TERM}' reaches a rule. Beat 3 opens by asking "
            f"what a Critical Supplier is, and the graph cannot answer."
        )
    row = leg1.iloc[0]
    for field, what in (
        ("definition", "the term's definition"),
        ("expression", "the rule's expression"),
        ("threshold_id", "the governing threshold"),
        ("basis", "the threshold's authored basis"),
        ("value", "the threshold's resolved cutoff"),
    ):
        if not row[field] and row[field] != 0:
            sys.exit(
                f"Leg 1 resolves but {what} is empty ({field}). The room's next "
                f"question after RULE-05 is what the threshold is, and leg 1 is "
                f"the strongest artifact the demo has."
            )
    print(f"  leg 1 definition:  {row['rule_id']} -> {row['threshold_id']}, "
          f"basis present, cutoff {row['value']}")

    # Leg 2, discovery. The protagonist carries the precomputed score the demo
    # reads. Presence only: what the score IS is read from the output and never
    # asserted, per contract section 7.
    leg2 = gds.run_cypher(
        "MATCH (s:Supplier {id: $id}) RETURN s.betweenness AS betweenness",
        params={"id": protags.cascade_id},
    )
    if leg2.empty or leg2["betweenness"].iloc[0] is None:
        sys.exit(
            f"Leg 2 does not resolve: {protags.cascade_id} carries no betweenness "
            f"property. The discovery leg has nothing to show."
        )
    print(f"  leg 2 discovery:   {protags.cascade_id} carries betweenness")

    # Leg 3, explanation. The convergence traversal returns at least one path.
    # Variable-length so it survives the rebuild moving Cascade a tier back;
    # asserting a hop count here would bake today's topology into the check.
    leg3 = gds.run_cypher(
        """
        MATCH (c:Supplier {id: $cascade})-[:SUPPLIES*1..6]->(t:Supplier)
        WHERE t.id IN $tier1
        RETURN count(DISTINCT t) AS reached
        """,
        params={"cascade": protags.cascade_id, "tier1": protags.tier1_ids},
    )
    reached = int(leg3["reached"].iloc[0])
    if reached < 1:
        sys.exit(
            f"Leg 3 does not resolve: no SUPPLIES path from "
            f"{protags.cascade_id} to any tier-1 supplier. The explanation leg "
            f"has no path evidence to put on screen."
        )
    print(f"  leg 3 explanation: reached "
          f"{reached} of {len(protags.tier1_ids)} tier-1 suppliers")


def assert_betweenness(
    scores: list[Score], conc: Cohort, protags: Protagonists
) -> None:
    """Cascade must clear THR-03, and the cohort it clears with must not be alone.

    Two asserts, and neither is about who wins. The old version required Cascade
    to be the strict network maximum, which the demo does not need and which a
    room is entitled to be suspicious of: a single supplier topping a ranking by
    construction is a data plant wearing a graph algorithm. What the story claims
    is that Cascade is a Critical Supplier under a governed definition, and
    clearing the threshold is exactly that claim.

    The cohort size assert runs the other way, against the failure where the
    percentile catches Cascade and nothing else. That would be a one-winner
    threshold reappearing by accident, and it would make RULE-05's "catches a
    cohort rather than a single name" false on stage.

    Where Cascade ranks is printed rather than asserted. It is worth knowing and
    it is not a pass condition.
    """
    by_id = score_index(scores)
    cascade = require_score(by_id, protags.cascade_id, "Cascade")
    if cascade < conc.value:
        sys.exit(
            f"Story 1 betweenness: Cascade ({protags.cascade_id})={cascade} does "
            f"not clear the THR-03 cutoff {conc.value}, resolved from the "
            f"{conc.percentile}th percentile of supply betweenness. Per "
            f"proposals/CONTRACT.md section 7 the topology is what gets fixed, "
            f"the percentile does not move, and there are two honest iterations "
            f"before this becomes a finding rather than a bug."
        )
    if len(conc.members) < 2:
        sys.exit(
            f"Story 1 betweenness: the THR-03 cohort has {len(conc.members)} "
            f"member(s), so the threshold catches a single name and RULE-05's "
            f"cohort language does not describe what the graph does."
        )
    rank = [s.node_id for s in scores].index(protags.cascade_id) + 1
    print(
        f"  assert OK: Cascade betweenness {cascade} clears the THR-03 cutoff "
        f"{conc.value} ({conc.percentile}th percentile), ranking {rank} of "
        f"{len(scores)} in a cohort of {len(conc.members)}"
    )


def report_degree_overlap(
    gds: GraphDataScience, scores: list[Score], protags: Protagonists
) -> None:
    """Print how far the betweenness ranking diverges from counting connections.

    Leg 2 claims the graph algorithm finds something a GROUP BY over
    supply_relationships would not. That claim is about the realized data, not
    about the topology, so the generator cannot assert it: check_supply_structure
    asserts only that the network has the shape in which the two measures *can*
    diverge, and asserting the outcome there would be fitting the data to the
    story. This is the other half of that decision. The overlap is measured and
    printed so a build that fails to separate says so, and it is not a pass
    condition, so a build that fails to separate still finishes and leaves the
    evidence on the floor rather than being tuned until it passes.

    A high overlap is a finding to escalate under CONTRACT.md section 7, not a
    signal to keep raising SUP_WEB_CHORD_RATIO.
    """
    rows = gds.run_cypher(
        """
        MATCH (s:Supplier)-[:SUPPLIES]-(t:Supplier)
        RETURN s.id AS supplierId, count(*) AS degree
        ORDER BY degree DESC, supplierId
        """
    )
    degrees = {r["supplierId"]: int(r["degree"]) for _, r in rows.iterrows()}
    top_degree = [r["supplierId"] for _, r in rows.iterrows()][:TOP_N_OVERLAP]
    top_between = [s.node_id for s in scores[:TOP_N_OVERLAP]]
    shared = set(top_degree) & set(top_between)

    cascade_degree_rank = top_degree.index(protags.cascade_id) + 1 \
        if protags.cascade_id in top_degree else None
    placement = (
        f"rank {cascade_degree_rank}" if cascade_degree_rank
        else f"outside the top {TOP_N_OVERLAP}"
    )
    print(
        f"  degree vs betweenness: the top {TOP_N_OVERLAP} by each measure share "
        f"{len(shared)} supplier(s); Cascade has degree "
        f"{degrees.get(protags.cascade_id, 0)} and sits {placement} by degree"
    )


def assert_pagerank(
    scores: list[Score],
    cont: Cutoff,
    protags: Protagonists,
    trading: set[str],
) -> None:
    """Jade must be the top trading customer by weighted contagion."""
    by_id = score_index(scores)
    jade = require_score(by_id, protags.jade_id, "Jade")
    if jade < cont.value:
        sys.exit(
            f"Story 2 PageRank: Jade ({protags.jade_id})={jade} does not clear "
            f"THR-04 cutoff {cont.value}."
        )
    others_over = sorted(
        (cid, v)
        for cid, v in by_id.items()
        if cid in trading and cid != protags.jade_id and v >= cont.value
    )
    if others_over:
        sys.exit(
            f"Story 2 PageRank: other trading customers clear THR-04 cutoff "
            f"{cont.value}: {others_over}"
        )
    print(
        f"  assert OK: Jade PageRank {jade} is the top trading customer "
        f"(next {cont.runner_up}); THR-04 cutoff {cont.value}"
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

    with GraphDataScience(uri, auth=auth, database=database) as gds:
        print(
            f"Connected to {uri} (database={database}), "
            f"GDS client v{gds.version()}"
        )

        betweenness = compute_betweenness(gds, protags)
        conc = concentration_cutoff(betweenness)
        assert_betweenness(betweenness, conc, protags)
        report_degree_overlap(gds, betweenness, protags)
        write_betweenness(gds, betweenness)
        write_critical_supplier_labels(gds, conc)

        pagerank = compute_pagerank(gds, protags)
        trading = trading_customers(gds)
        print_top_trading(pagerank, protags, trading)
        cont = contagion_cutoff(pagerank, protags, trading)
        assert_pagerank(pagerank, cont, protags, trading)
        write_pagerank(gds, pagerank)

        header("Graph-native thresholds (set from the computed distributions)")
        cutoffs = {
            CONCENTRATION_THRESHOLD_ID: conc.value,
            CONTAGION_THRESHOLD_ID: cont.value,
        }
        write_thresholds(gds, cutoffs)
        update_thresholds_csv(args.data_dir / "thresholds.csv", cutoffs)
        write_rule_thresholds(
            gds,
            {
                CONCENTRATION_RULE_ID: conc.value,
                CONTAGION_RULE_ID: cont.value,
            },
        )

        header("Governed vocabulary bound to the metrics (Neo4j only)")
        write_governed_terms(gds)

        # Last, because leg 1 walks to the threshold value that only exists once
        # the cutoffs above have been written.
        check_three_legs(gds, protags)

    print(
        "\nGDS analytics complete: betweenness and pagerank written to Neo4j as "
        "node properties, THR-03/THR-04 set, RULE-05/RULE-06 thresholds backfilled, "
        "governing terms bound to both metrics. Nothing synced to Delta."
    )


if __name__ == "__main__":
    main()

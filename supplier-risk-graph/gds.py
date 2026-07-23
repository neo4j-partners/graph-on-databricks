"""Phase 2 graph analytics for the sharpened supplier-risk-graph demo.

Runs the three graph algorithms that the three demo stories turn on, with the
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

  3. Payment-behaviour kNN (the Risky Customer early warning). Projects the
     Customer nodes with their two payment-behaviour features, avgDaysLate and
     overdueShare, scales the pair to z-scores as one vector, and runs gds.knn
     to find each customer's nearest neighbours in that space. The metric is
     then the share of those neighbours already classified Delinquent, so a
     customer scores by the company its payment behaviour keeps rather than by
     any threshold on its own columns. Written back as a delinquencySimilarity
     property on every Customer node.

     This is the early-warning counterpart to the Delinquent Customer rule: one
     term is the rule that already tripped, the other is the resemblance that
     has not tripped it yet. The neighbourhoods are computed over every
     customer, because the delinquent accounts have to be in the candidate set
     for anything to be near them, while the classification is applied only to
     customers that have not already failed.

Algorithms 1 and 2 then set the two graph-native thresholds that had no value
until the scores existed, and they are set by opposite logic. The Supply Concentration
Threshold (THR-03) resolves a governed percentile, fixed in the generator before
any score existed, against the distribution this run produced; it catches a
cohort, and how many suppliers are in it is an output. The Ownership Contagion
Threshold (THR-04) is still placed between Jade and the next trading customer so
only Jade clears it, because Story 2 is out of scope. Do not "align" THR-04 to
THR-03: that is a redesign of Story 2 rather than a tidy-up. Both are written
onto the live Threshold nodes and back into data/thresholds.csv (graph-only,
never uploaded to Unity Catalog), so a reload carries them.

THR-05, the Customer Similarity Threshold, is the exception and is the shape to
copy for anything new. Its governed parameter is a neighbour share, already on
the same scale as the metric it governs, so there is nothing to resolve: it is
authored in the generator before any similarity is computed and this file only
verifies that the graph carries the value it screened against. Do not convert it
to a fitted cutoff for symmetry with THR-04.

Knowledge-layer bindings follow from the same computed values. The
cutoffs are backfilled onto RULE-05 and RULE-06 as an inline threshold property,
so the graph-native rules carry their number the way the four column-findable
rules already do. And the governing term name is written onto every node that
carries the metric, so the governed vocabulary travels with the score into any
result set. Risky Customer also materializes a governed `CLASSIFIED_AS` edge and
its delinquent-neighbour evidence because it is an operational early-warning
cohort. The governing property still travels on every Customer, whether or not
the customer clears the screen.

The build fails loud if either plant is wrong: Cascade must clear THR-03 in a
cohort with more than one member, and Jade must be the top trading customer by
weighted contagion. Where Cascade ranks is reported and is not a pass
condition. PageRank convergence is checked before its scores are used, since
the contagion cutoff is placed from them to six decimal places. Deterministic
given the fixed-seed data. Re-runnable: all three graph projections are dropped
on entry and exit, derived Risky Customer evidence and labels are replaced, and
the remaining write-backs overwrite in place.

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
    DELINQUENCY_NEIGHBOUR_SHARE,
    DELINQUENCY_NEIGHBOURS,
    RULE_VERSION,
    SUPPLY_CONCENTRATION_PERCENTILE,
)

HERE = Path(__file__).parent

SUPPLIER_GRAPH = "supplierNetwork"
OWNERSHIP_GRAPH = "ownershipNetwork"
BEHAVIOUR_GRAPH = "customerBehaviour"

CONCENTRATION_THRESHOLD_ID = "THR-03"  # Supply Concentration Threshold
CONTAGION_THRESHOLD_ID = "THR-04"  # Ownership Contagion Threshold
SIMILARITY_THRESHOLD_ID = "THR-05"  # Customer Similarity Threshold

CONCENTRATION_RULE_ID = "RULE-05"  # Critical Supplier Rule
CONTAGION_RULE_ID = "RULE-06"  # Ownership Risk Rule
RISKY_CUSTOMER_RULE_ID = "RULE-09"  # Risky Customer Rule

DELINQUENT_TERM_ID = "TERM-03"  # Delinquent Customer, a CLASSIFIED_AS edge

CRITICAL_SUPPLIER_TERM = "Critical Supplier"  # TERM-05, governs Supplier.betweenness
OWNERSHIP_RISK_TERM = "Ownership Risk"  # TERM-06, governs Customer.pagerank
RISKY_CUSTOMER_TERM = "Risky Customer"  # TERM-07, governs Customer.delinquencySimilarity

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

# The scaled feature vector kNN reads, and the two raw properties behind it.
#
# Standardizing first is not a tidy-up, it decides the answer. GDS scores each
# nodeProperty separately and averages, and for scalars it uses 1/(1+|a-b|), so
# on the raw columns a typical overdueShare gap of 0.1 scores about 0.91 while a
# typical avgDaysLate gap of 10 scores about 0.09. Passing the two raw properties
# would therefore rank customers on overdueShare alone with avgDaysLate reduced to
# a near-constant. Scaling both to z-scores and comparing the pair as one vector
# is what makes the neighbourhood mean "similar payment behaviour" rather than
# "similar on whichever feature happens to have the narrower range".
BEHAVIOUR_FEATURES = ["avgDaysLate", "overdueShare"]
BEHAVIOUR_VECTOR = "paymentBehaviour"

# kNN config, pinned for determinism the way PAGERANK_CONFIG is and for the same
# reason: the cohort that clears THR-05 is read off these neighbourhoods, so two
# runs that disagree would move who gets classified.
#
# GDS kNN uses neighbour descent rather than a brute-force all-pairs comparison.
# sampleRate 1.0 considers every candidate the algorithm encounters, while
# deltaThreshold 0.0 disables early convergence; together they favour recall but
# do not turn the implementation into an exact search. randomSeed pins the
# initial neighbourhoods and tie-breaking, which matters more here than the node
# count suggests: many customers pay on time and carry identical feature pairs.
# GDS requires concurrency 1 for randomSeed to be honoured, so the two always
# travel together. The result is deterministic, and the validation below proves
# that it is complete at topK for every customer before any classification is
# written.
KNN_CONFIG = {
    "nodeProperties": {BEHAVIOUR_VECTOR: "EUCLIDEAN"},
    "topK": DELINQUENCY_NEIGHBOURS,
    "sampleRate": 1.0,
    "deltaThreshold": 0.0,
    "randomSeed": 42,
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
    """One node's score from a graph algorithm.

    The scoring stages share the same shape: a node id, a display name, and a
    number. Downstream cutoff placement, assertions, write-backs, and stage
    printing only need those three fields. The field is called `value` because
    its meaning is fixed by the algorithm that produced the list, not by the key
    it is read under.
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


class Screen(NamedTuple):
    """A governed cutoff applied on the metric's own scale to an eligible set.

    The third threshold shape in this file, and distinct from both of the others
    for a reason that is easy to collapse. A Cutoff is fitted between a named
    node and the runner-up. A Cohort resolves a percentile against the run's
    distribution, so its `value` is an output. A Screen's cutoff is neither
    fitted nor resolved: THR-05 is a share of a fixed neighbourhood, already on
    the same 0-to-1 scale as the metric it governs, so the governed parameter and
    the cutoff are the same number and it is authored in the generator before any
    similarity is computed.

    `eligible` is carried because a Screen is applied to a population rather than
    to the whole field. Risky Customer can only describe an account that has not
    already failed, so the count of who was even considered is part of reading the
    result honestly: a cohort of seven means something different out of four
    hundred candidates than out of ten.
    """

    cutoff: float
    members: list[Score]
    eligible: int


class Neighbourhood(NamedTuple):
    """The kNN pass's two outputs, which are needed by different consumers.

    `scores` is the metric itself, one delinquency-similarity value for every
    Customer, and it is written to every node the way betweenness and pagerank
    are. `delinquent_links` is the evidence behind it: the individual (customer,
    already-delinquent neighbour, similarity, rank) tuples the score counts up.
    The score answers which customers are Risky Customers, and only the links
    answer why this one, which is the Explanation step.
    """

    scores: list[Score]
    delinquent_links: list[tuple[str, str, float, int]]


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


def write_critical_supplier_labels(
    gds: GraphDataScience, conc: Cohort, evaluated_at: str
) -> None:
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
            "evaluatedAt": evaluated_at,
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
    # Select the cohort against the unrounded nearest-rank score, and round only
    # for the value written to the Threshold node, to thresholds.csv and to the
    # display. Rounding before the >= comparison drops the supplier that defines
    # the percentile whenever the round goes up: its own score sits fractionally
    # below the cutoff derived from it and it falls out of its own cohort. A round
    # down lets suppliers below the percentile join. Selecting against the score
    # the field actually produced keeps the cohort the percentile names.
    selection = ranked[max(index, 0)]
    members = [s for s in scores if s.value >= selection]
    value = round(selection, 2)
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

    # Risky Customer is the one graph-native term that also carries CLASSIFIED_AS
    # edges, so unlike the two above this property is not the only way the
    # vocabulary travels. It is set anyway, for the same reason the score is
    # written to every Customer: the binding says which term governs the metric,
    # not which customers qualify under it, and a model reading the score off an
    # unclassified customer should still learn what the number is called.
    similarity = gds.run_cypher(
        """
        MATCH (c:Customer)
        SET c.delinquencySimilarityGovernedTerm = $term
        RETURN count(c) AS written
        """,
        params={"term": RISKY_CUSTOMER_TERM},
    )
    print(
        f"  bound '{RISKY_CUSTOMER_TERM}' to delinquencySimilarity on "
        f"{int(similarity['written'].iloc[0])} Customer nodes"
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
    # Membership, not a comparison against the rounded value. conc.value is the
    # display figure written to the Threshold node; the cohort was selected
    # against the unrounded percentile score, so "Cascade clears THR-03" is
    # exactly "Cascade is in the cohort". Comparing the 4-decimal score against
    # the 2-decimal value here would reintroduce the rounding boundary that the
    # cohort selection in concentration_cutoff was fixed to avoid.
    if not any(s.node_id == protags.cascade_id for s in conc.members):
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


def compute_delinquency_similarity(gds: GraphDataScience) -> Neighbourhood:
    """Algorithm 3: kNN over payment behaviour (the Risky Customer early warning).

    The projection keeps Customer nodes carrying the two payment-behaviour
    features, scales them to z-scores as one vector, and asks each customer who
    its k nearest neighbours are in that space. The metric is then the share of
    those neighbours already classified Delinquent.

    **The neighbourhood is computed over every Customer, and that is
    load-bearing.** The delinquent customers have to be in the candidate set or
    there is nothing for a near neighbour to be near. Eligibility, meaning who
    the resulting classification may apply to, is a separate question answered by
    risky_candidates below. Filtering the delinquents out here instead would
    silently produce a metric that is zero for everybody.

    The score is written to every Customer for the same reason betweenness is
    written to every Supplier: it is a metric, not a verdict. A customer paying
    perfectly on time gets a delinquency similarity of zero, which is a fact
    about it rather than an absence of one.

    OWNED_BY is projected only because gds.graph.project refuses an empty
    relationship projection. kNN reads node properties and ignores relationships
    entirely, so which type is projected has no effect on the result.
    """
    header("Algorithm 3: payment-behaviour kNN (the Risky Customer early warning)")
    feature_stats = gds.run_cypher(
        """
        MATCH (c:Customer)
        RETURN count(c) AS total,
               count(c.avgDaysLate) AS withAvgDaysLate,
               count(c.overdueShare) AS withOverdueShare
        """
    ).iloc[0]
    customer_count = int(feature_stats["total"])
    if customer_count <= DELINQUENCY_NEIGHBOURS:
        sys.exit(
            f"Payment-behaviour kNN needs more than {DELINQUENCY_NEIGHBOURS} "
            f"customers to return that many neighbours, found {customer_count}."
        )
    incomplete = {
        "avgDaysLate": customer_count - int(feature_stats["withAvgDaysLate"]),
        "overdueShare": customer_count - int(feature_stats["withOverdueShare"]),
    }
    incomplete = {name: count for name, count in incomplete.items() if count}
    if incomplete:
        sys.exit(
            "Payment-behaviour kNN cannot score customers with missing features: "
            + ", ".join(f"{name} missing on {count}" for name, count in incomplete.items())
        )

    drop_graph(gds, BEHAVIOUR_GRAPH)
    gds.run_cypher(
        "CALL gds.graph.project($graph, {Customer: {properties: $features}}, "
        "['OWNED_BY'])",
        params={"graph": BEHAVIOUR_GRAPH, "features": BEHAVIOUR_FEATURES},
    )
    try:
        scaled = gds.run_cypher(
            """
            CALL gds.scaleProperties.mutate($graph, {
                nodeProperties: $features,
                scaler: 'StdScore',
                mutateProperty: $vector
            })
            YIELD nodePropertiesWritten
            RETURN nodePropertiesWritten AS written
            """,
            params={
                "graph": BEHAVIOUR_GRAPH,
                "features": BEHAVIOUR_FEATURES,
                "vector": BEHAVIOUR_VECTOR,
            },
        )
        print(
            f"  scaled {', '.join(BEHAVIOUR_FEATURES)} to z-scores on "
            f"{int(scaled['written'].iloc[0])} Customer nodes"
        )

        # One row per (customer, neighbour) pair, carrying whether the neighbour
        # is already Delinquent. The share is aggregated below in Python rather
        # than in Cypher so the raw pairs survive for the Explanation step.
        rows = gds.run_cypher(
            """
            CALL gds.knn.stream($graph, {
                nodeProperties: $nodeProperties,
                topK: $topK,
                sampleRate: $sampleRate,
                deltaThreshold: $deltaThreshold,
                randomSeed: $randomSeed,
                concurrency: $concurrency
            })
            YIELD node1, node2, similarity
            WITH gds.util.asNode(node1) AS c, gds.util.asNode(node2) AS n, similarity
            RETURN c.id AS customerId, c.name AS name, n.id AS neighbourId,
                   similarity,
                   EXISTS {
                       (n)-[:CLASSIFIED_AS]->(:BusinessTerm {id: $delinquentTerm})
                   } AS neighbourDelinquent
            ORDER BY customerId, similarity DESC, neighbourId
            """,
            params={
                "graph": BEHAVIOUR_GRAPH,
                "delinquentTerm": DELINQUENT_TERM_ID,
                **KNN_CONFIG,
            },
        )
    finally:
        drop_graph(gds, BEHAVIOUR_GRAPH)

    totals: dict[str, int] = {}
    delinquent_neighbours: dict[str, int] = {}
    names: dict[str, str] = {}
    links: list[tuple[str, str, float, int]] = []
    pairs: set[tuple[str, str]] = set()
    for _, row in rows.iterrows():
        cid = row["customerId"]
        neighbour_id = row["neighbourId"]
        pair = (cid, neighbour_id)
        if cid == neighbour_id:
            sys.exit(f"Payment-behaviour kNN returned a self-neighbour for {cid}.")
        if pair in pairs:
            sys.exit(
                f"Payment-behaviour kNN returned duplicate neighbour pair "
                f"{cid} -> {neighbour_id}."
            )
        pairs.add(pair)
        names[cid] = row["name"]
        totals[cid] = totals.get(cid, 0) + 1
        similarity = float(row["similarity"])
        if not math.isfinite(similarity) or not 0 <= similarity <= 1:
            sys.exit(
                f"Payment-behaviour kNN returned invalid similarity {similarity} "
                f"for {cid} -> {neighbour_id}."
            )
        if row["neighbourDelinquent"]:
            delinquent_neighbours[cid] = delinquent_neighbours.get(cid, 0) + 1
            links.append((cid, neighbour_id, round(similarity, 4), totals[cid]))

    if len(totals) != customer_count:
        sys.exit(
            f"Payment-behaviour kNN returned neighbourhoods for {len(totals)} of "
            f"{customer_count} customers."
        )
    short = {
        cid: total
        for cid, total in totals.items()
        if total != DELINQUENCY_NEIGHBOURS
    }
    if short:
        sample = ", ".join(
            f"{cid}={total}" for cid, total in sorted(short.items())[:TOP_N_PRINT]
        )
        sys.exit(
            f"Payment-behaviour kNN did not return exactly "
            f"{DELINQUENCY_NEIGHBOURS} neighbours for every customer: {sample}. "
            f"The governed share cannot be compared with a changing denominator."
        )

    # The rule says "share of 10", so the configured neighbourhood size is the
    # denominator. The completeness check above makes that statement true for
    # every score instead of silently adapting the rule to partial output.
    scores = [
        Score(
            cid,
            names[cid],
            round(
                delinquent_neighbours.get(cid, 0) / DELINQUENCY_NEIGHBOURS,
                4,
            ),
        )
        for cid in sorted(totals)
    ]
    scores.sort(key=lambda s: (-s.value, s.node_id))
    print(
        f"  scored {len(scores)} customers on the share of their "
        f"{DELINQUENCY_NEIGHBOURS} nearest neighbours already classified "
        f"'{DELINQUENT_TERM_ID}'"
    )
    return Neighbourhood(scores, links)


def risky_candidates(gds: GraphDataScience) -> set[str]:
    """Customers the Risky Customer term can apply to at all.

    TERM-07 is an early warning, so it can only describe an account that has not
    already failed. Three clauses, all of them from the definition rather than
    carved out for the demo: a customer that already carries a defaultedPeriod
    has defaulted, a customer already classified Delinquent has tripped RULE-03
    and needs no warning, and a customer with no invoices has no payment
    behaviour to resemble anything.

    Deliberately parallel to trading_customers, including the landmine assert.
    A filter that silently matches everybody looks identical to a filter that
    works, and here it would classify already-delinquent customers as an early
    warning about themselves.
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
    candidates = set(rows["cid"])
    if not candidates:
        sys.exit(
            "No Risky Customer candidates found: every customer has already "
            "defaulted, is already delinquent, or has no invoices. The screen "
            "would pass having considered nobody."
        )

    total = int(gds.run_cypher("MATCH (c:Customer) RETURN count(c) AS n")["n"].iloc[0])
    excluded = total - len(candidates)
    if excluded <= 0:
        sys.exit(
            f"The Risky Customer candidate filter excluded nobody: {total} "
            f"customers in, {len(candidates)} out. The already-failed accounts "
            f"would be classified as an early warning about themselves."
        )
    print(f"  candidates: {len(candidates)} of {total} ({excluded} already failed)")
    return candidates


def risky_screen(scores: list[Score], candidates: set[str]) -> Screen:
    """THR-05 applied to the eligible customers. Nothing here is fitted.

    The contrast with concentration_cutoff is the point. That function has to
    resolve a percentile against the run's distribution before it names a number.
    This one does not, because a neighbour share is already on the metric's
    scale, so the authored constant IS the cutoff and this is a filter rather
    than a placement. Who clears it is the only output.
    """
    members = [
        s for s in scores if s.node_id in candidates and s.value >= DELINQUENCY_NEIGHBOUR_SHARE
    ]
    return Screen(DELINQUENCY_NEIGHBOUR_SHARE, members, len(candidates))


def write_delinquency_similarity(gds: GraphDataScience, scores: list[Score]) -> None:
    rows = [{"cid": s.node_id, "score": s.value} for s in scores]
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.cid})
        SET c.delinquencySimilarity = row.score
        RETURN count(c) AS written
        """,
        params={"rows": rows},
    )
    written = int(result["written"].iloc[0])
    if written != len(rows):
        sys.exit(
            f"Delinquency similarity write set {written} of {len(rows)} Customer "
            f"nodes; every scored customer must exist under MATCH (c:Customer {{id}})."
        )
    print(f"  wrote delinquencySimilarity to {written} Customer nodes")


def write_similarity_edges(
    gds: GraphDataScience,
    screen: Screen,
    links: list[tuple[str, str, float, int]],
    evaluated_at: str,
) -> None:
    """Materialize the neighbour evidence behind each classified customer.

    Without this the Risky Customer beat can say who and cannot say why. The
    score alone is a number that has to be taken on trust, and "why this
    customer" is the Explanation step that Beat 3 answers with a supply path.
    These edges are that path's counterpart: they name the already-delinquent
    accounts whose payment behaviour this customer's most resembles, so the
    answer on screen is a list of real customers rather than a decimal.

    Only the classified cohort's links are written. Every customer has nearest
    neighbours, but an edge from a customer nobody classified is evidence for a
    conclusion that was never drawn, and writing all of them would put roughly
    one edge per customer into the graph to no purpose.

    Neo4j only, like every other output in this file. Nothing here is synced to
    Delta.
    """
    member_ids = {s.node_id for s in screen.members}
    rows = [
        {"cid": cid, "nid": nid, "similarity": similarity, "rank": rank}
        for cid, nid, similarity, rank in links
        if cid in member_ids
    ]
    if not rows:
        sys.exit(
            "No delinquent-neighbour links for the Risky Customer cohort, yet the "
            "cohort is non-empty. Every member cleared THR-05 by counting "
            "delinquent neighbours, so each must have at least one."
        )
    # A supported pipeline run starts from a wiped graph, but gds.py is also
    # documented as runnable on its own. Clear the previous derived evidence so
    # a rerun cannot leave links from customers that no longer clear the screen.
    gds.run_cypher(
        "MATCH ()-[r:SIMILAR_PAYMENT_BEHAVIOR]->() DELETE r"
    )
    result = gds.run_cypher(
        """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.cid})
        MATCH (n:Customer {id: row.nid})
        MERGE (c)-[r:SIMILAR_PAYMENT_BEHAVIOR]->(n)
        SET r.similarity = row.similarity,
            r.neighbourRank = row.rank,
            r.evaluatedAt = datetime($evaluatedAt)
        RETURN count(r) AS written
        """,
        params={
            "rows": rows,
            "evaluatedAt": evaluated_at,
        },
    )
    written = int(result["written"].iloc[0])
    if written != len(rows):
        sys.exit(
            f"Payment-behaviour explanation wrote {written} of {len(rows)} "
            f"SIMILAR_PAYMENT_BEHAVIOR edges."
        )
    print(
        f"  wrote {written} SIMILAR_PAYMENT_BEHAVIOR edges from the cohort to the "
        f"delinquent customers they resemble"
    )


def write_risky_customer_labels(
    gds: GraphDataScience, screen: Screen, evaluated_at: str
) -> None:
    """Materialize CLASSIFIED_AS edges from the THR-05 screen to TERM-07.

    Same reasoning as write_critical_supplier_labels, including the Delta
    write-back note: these edges do reach the `classifications` gold table, and
    what keeps them away from the lakehouse-only engine is `banned_tables` in
    guard.py holding that table out of the Genie space. Do not add a term filter
    to CLASSIFICATIONS_SPEC to "fix" it.

    **The cohort is derived and never enumerated.** Membership comes from the
    scored neighbourhoods, so the edges are an output of this run. The generator
    plants payment behaviour for a near-miss cohort and it plants no
    classification, which is why the two sets are allowed to differ and on the
    current data do: the screen catches customers nobody planted and misses
    planted ones whose neighbourhoods came out just under the line. Writing the
    planted ids here instead would be the plant CONTRACT.md section 8 bans.
    """
    reason = (
        f"at least {screen.cutoff:.0%} of its {DELINQUENCY_NEIGHBOURS} nearest "
        f"neighbours by payment behaviour are already classified Delinquent"
    )
    # Remove the previous derived cohort before writing this run's screen. This
    # makes a standalone rerun replace the classification instead of accumulating
    # stale Risky Customer labels.
    gds.run_cypher(
        """
        MATCH (:Customer)-[r:CLASSIFIED_AS]->(:BusinessTerm {name: $term})
        DELETE r
        """,
        params={"term": RISKY_CUSTOMER_TERM},
    )
    result = gds.run_cypher(
        """
        MATCH (t:BusinessTerm {name: $term})
        UNWIND $ids AS cid
        MATCH (c:Customer {id: cid})
        MERGE (c)-[r:CLASSIFIED_AS]->(t)
        SET r.reason = $reason,
            r.evaluatedAt = datetime($evaluatedAt),
            r.ruleVersion = $ruleVersion
        RETURN count(r) AS written
        """,
        params={
            "term": RISKY_CUSTOMER_TERM,
            "ids": [s.node_id for s in screen.members],
            "reason": reason,
            "evaluatedAt": evaluated_at,
            "ruleVersion": RULE_VERSION,
        },
    )
    written = int(result["written"].iloc[0])
    if written != len(screen.members):
        sys.exit(
            f"Risky Customer labelling wrote {written} of {len(screen.members)} "
            f"CLASSIFIED_AS edges. Every screen member must exist as a Customer "
            f"node and '{RISKY_CUSTOMER_TERM}' must exist as a BusinessTerm, or "
            f"the early-warning beat resolves to an empty result."
        )
    print(
        f"  labelled {written} customer(s) as '{RISKY_CUSTOMER_TERM}' "
        f"(CLASSIFIED_AS, screened at {screen.cutoff})"
    )


def check_governed_threshold(gds: GraphDataScience) -> None:
    """THR-05 and RULE-09 must carry the value this file screened against.

    Unlike THR-03 and THR-04, nothing in this file writes THR-05: it is authored
    in the generator and arrives through load.py. That is the property worth
    having, and it is also a new way to be wrong. If data/ is regenerated with a
    different governed share and Neo4j is not reloaded, the screen above runs on
    the imported constant while the graph serves the stale one, so the demo shows
    a threshold that does not match the cohort standing next to it. Nothing else
    would notice.
    """
    rows = gds.run_cypher(
        """
        MATCH (h:Threshold {id: $thresholdId})
        MATCH (r:BusinessRule {id: $ruleId})
        RETURN h.value AS thresholdValue, h.basis AS basis, r.threshold AS ruleValue
        """,
        params={
            "thresholdId": SIMILARITY_THRESHOLD_ID,
            "ruleId": RISKY_CUSTOMER_RULE_ID,
        },
    )
    if rows.empty:
        sys.exit(
            f"{SIMILARITY_THRESHOLD_ID} or {RISKY_CUSTOMER_RULE_ID} is missing from "
            f"the graph. Reload from data/ before running this."
        )
    row = rows.iloc[0]
    for field, what in (("thresholdValue", SIMILARITY_THRESHOLD_ID),
                        ("ruleValue", RISKY_CUSTOMER_RULE_ID)):
        if row[field] is None or float(row[field]) != DELINQUENCY_NEIGHBOUR_SHARE:
            sys.exit(
                f"{what} carries {row[field]} but this run screened against "
                f"{DELINQUENCY_NEIGHBOUR_SHARE}. Neo4j holds a stale snapshot of "
                f"data/; reload before running this."
            )
    if not row["basis"]:
        sys.exit(
            f"{SIMILARITY_THRESHOLD_ID} has no authored basis. It is the sentence "
            f"that answers the room's next question after the rule, and the "
            f"early-warning beat opens on it."
        )
    print(
        f"  {SIMILARITY_THRESHOLD_ID} and {RISKY_CUSTOMER_RULE_ID} both carry the "
        f"authored share {DELINQUENCY_NEIGHBOUR_SHARE}, basis present"
    )


def assert_risky_customers(
    screen: Screen, near_miss: set[str], candidates: set[str]
) -> None:
    """The screen must catch a cohort, and the plant must be findable in it.

    Three asserts, and none of them is about which customers come out. What the
    beat claims is that an authored definition, applied to a graph metric, finds
    accounts heading for delinquency before the rule trips. Each assert covers
    one way that claim could be false while everything else still passed.

    The cohort-size assert is the same one assert_betweenness makes and is there
    for the same reason: a threshold exactly one entity clears is a post-hoc
    threshold however it was derived, and RULE-09's cohort language would be
    false on stage.

    The eligibility assert covers the failure where the screen classifies
    somebody who has already failed, which would make an early warning about a
    customer that needs no warning.

    The plant assert is the analogue of Cascade clearing THR-03. The generator
    shapes a near-miss cohort's payment behaviour specifically so this pass has
    something to find, and if none of it surfaces then either the plant did not
    take or the scoring is not measuring what the term claims. It asserts that
    the plant is findable and deliberately does not assert how much of it is
    found: requiring all of it would be fitting the threshold to the plant, and
    the planted customers that fall just under the line are evidence the cohort
    is derived rather than enumerated.

    **What is read from the output and never asserted:** how many customers clear,
    how the cohort splits between planted and emergent members, and who ranks
    where. Those are printed below. An emergent member is a good sign and not a
    pass condition, and turning it into one would be fitting the data.
    """
    if len(screen.members) < 2:
        sys.exit(
            f"Risky Customer: the THR-05 screen caught {len(screen.members)} "
            f"customer(s), so the threshold names a single account and RULE-09's "
            f"cohort language does not describe what the graph does."
        )
    ineligible = [s.node_id for s in screen.members if s.node_id not in candidates]
    if ineligible:
        sys.exit(
            f"Risky Customer: {sorted(ineligible)} cleared THR-05 but are not "
            f"eligible candidates. An account that has already defaulted or is "
            f"already Delinquent cannot be an early warning about itself."
        )
    caught = [s.node_id for s in screen.members if s.node_id in near_miss]
    if not caught:
        sys.exit(
            f"Risky Customer: none of the {len(near_miss)} planted near-miss "
            f"customers cleared THR-05, so either the plant did not take or the "
            f"similarity is not measuring payment behaviour. Per CONTRACT.md "
            f"section 7 the data is what gets fixed, the governed share does not "
            f"move, and there are two honest iterations before this is a finding "
            f"rather than a bug."
        )
    emergent = [s.node_id for s in screen.members if s.node_id not in near_miss]
    print(
        f"  assert OK: {len(screen.members)} customer(s) of {screen.eligible} "
        f"eligible clear THR-05 ({screen.cutoff}); {len(caught)} of "
        f"{len(near_miss)} planted near-miss customers among them"
    )
    print(
        f"  cohort composition: {len(caught)} planted, {len(emergent)} emergent "
        f"(found by the metric, planted by nobody)"
    )
    for row in screen.members:
        tag = "planted" if row.node_id in near_miss else "emergent"
        print(
            f"    {row.node_id} {row.name:<28} "
            f"delinquencySimilarity={row.value:<6} {tag}"
        )


def check_risky_customer_legs(gds: GraphDataScience, screen: Screen) -> None:
    """The early-warning beat's three steps resolve, in the Beat 3 shape.

    Deliberately parallel to check_three_legs. Beat 3 established that a grounded
    answer needs all three of Definition, Discovery and Explanation, and a second
    grounded beat that only reaches two of them is a weaker version of the first
    rather than a second one. The mechanical half only: that the three produce
    three distinct visible outputs on a screen is a re-probe check, not a build
    one.
    """
    header("The early-warning beat: the three steps resolve")

    # Definition. Term to rule to threshold, matched by term name because that is
    # how the question arrives.
    definition = gds.run_cypher(
        """
        MATCH (t:BusinessTerm {name: $term})-[:DEFINED_BY]->(r:BusinessRule)
        OPTIONAL MATCH (r)-[:USES_THRESHOLD]->(h:Threshold)
        RETURN t.definition AS definition, r.id AS rule_id,
               r.expression AS expression, h.id AS threshold_id,
               h.basis AS basis, h.value AS value
        """,
        params={"term": RISKY_CUSTOMER_TERM},
    )
    if definition.empty:
        sys.exit(
            f"Definition does not resolve: no BusinessTerm named "
            f"'{RISKY_CUSTOMER_TERM}' reaches a rule. The beat opens by asking "
            f"what a Risky Customer is, and the graph cannot answer."
        )
    row = definition.iloc[0]
    for field, what in (
        ("definition", "the term's definition"),
        ("expression", "the rule's expression"),
        ("threshold_id", "the governing threshold"),
        ("basis", "the threshold's authored basis"),
        ("value", "the threshold's value"),
    ):
        if not row[field] and row[field] != 0:
            sys.exit(
                f"Definition resolves but {what} is empty ({field})."
            )
    print(f"  definition:  {row['rule_id']} -> {row['threshold_id']}, "
          f"basis present, cutoff {row['value']}")

    # Discovery. The classified cohort is reachable from the term, the way the
    # four column-findable terms are, and each edge carries its reason.
    discovery = gds.run_cypher(
        """
        MATCH (c:Customer)-[r:CLASSIFIED_AS]->(:BusinessTerm {name: $term})
        RETURN count(c) AS classified, count(r.reason) AS withReason
        """,
        params={"term": RISKY_CUSTOMER_TERM},
    )
    classified = int(discovery["classified"].iloc[0])
    with_reason = int(discovery["withReason"].iloc[0])
    if classified != len(screen.members) or with_reason != classified:
        sys.exit(
            f"Discovery does not resolve: {classified} customers carry a "
            f"'{RISKY_CUSTOMER_TERM}' classification ({with_reason} with a "
            f"reason), but the screen caught {len(screen.members)}."
        )
    print(f"  discovery:   {classified} classified customers, each with a reason")

    # Explanation. Every classified customer names the delinquent accounts it
    # resembles. Presence and coverage only: which neighbours, and how similar,
    # are read from the output.
    explanation = gds.run_cypher(
        """
        MATCH (c:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm {name: $term})
        OPTIONAL MATCH (c)-[s:SIMILAR_PAYMENT_BEHAVIOR]->(n:Customer)
        WITH c, count(s) AS neighbours,
             count(s.similarity) AS withSimilarity,
             count(s.neighbourRank) AS withRank,
             count(CASE WHEN EXISTS {
                 (n)-[:CLASSIFIED_AS]->(:BusinessTerm {id: $delinquentTerm})
             } THEN 1 END) AS delinquentNeighbours
        RETURN c.id AS cid, c.delinquencySimilarity AS score, neighbours,
               withSimilarity, withRank, delinquentNeighbours
        ORDER BY cid
        """,
        params={
            "term": RISKY_CUSTOMER_TERM,
            "delinquentTerm": DELINQUENT_TERM_ID,
        },
    )
    for _, explained in explanation.iterrows():
        neighbours = int(explained["neighbours"])
        expected = round(float(explained["score"]) * DELINQUENCY_NEIGHBOURS)
        if (
            neighbours != expected
            or int(explained["delinquentNeighbours"]) != expected
            or int(explained["withSimilarity"]) != expected
            or int(explained["withRank"]) != expected
        ):
            sys.exit(
                f"Explanation does not resolve for {explained['cid']}: score "
                f"implies {expected} delinquent neighbours, but the graph has "
                f"{neighbours} links ({int(explained['delinquentNeighbours'])} "
                f"to Delinquent customers, {int(explained['withSimilarity'])} "
                f"with similarity, {int(explained['withRank'])} with rank)."
            )
    fewest = int(explanation["neighbours"].min())
    total = int(explanation["neighbours"].sum())
    print(
        f"  explanation: {total} neighbour links across "
        f"the cohort, fewest {fewest} on any member"
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
    evaluated_at = f"{ground_truth['as_of_date']}T00:00:00Z"
    # The planted near-miss cohort, read rather than hardcoded. It is a cohort
    # and not a protagonist, so it stays out of Protagonists: nothing here names
    # one of these customers, and the only question asked of the set is whether
    # the screen found any of it.
    near_miss = set(ground_truth["classification_cohorts"]["near_miss_customers"])

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
        write_critical_supplier_labels(gds, conc, evaluated_at)

        pagerank = compute_pagerank(gds, protags)
        trading = trading_customers(gds)
        print_top_trading(pagerank, protags, trading)
        cont = contagion_cutoff(pagerank, protags, trading)
        assert_pagerank(pagerank, cont, protags, trading)
        write_pagerank(gds, pagerank)

        knn = compute_delinquency_similarity(gds)
        candidates = risky_candidates(gds)
        screen = risky_screen(knn.scores, candidates)
        assert_risky_customers(screen, near_miss, candidates)
        write_delinquency_similarity(gds, knn.scores)
        write_similarity_edges(gds, screen, knn.delinquent_links, evaluated_at)
        write_risky_customer_labels(gds, screen, evaluated_at)

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
        # THR-05 is authored rather than computed, so it is verified here instead
        # of written. See check_governed_threshold.
        check_governed_threshold(gds)

        header("Governed vocabulary bound to the metrics (Neo4j only)")
        write_governed_terms(gds)

        # Last, because leg 1 walks to the threshold value that only exists once
        # the cutoffs above have been written.
        check_three_legs(gds, protags)
        check_risky_customer_legs(gds, screen)

    print(
        "\nGDS analytics complete: betweenness, pagerank and delinquency "
        "similarity written to Neo4j as node properties, THR-03/THR-04 set and "
        "THR-05 verified, RULE-05/RULE-06 thresholds backfilled, governing terms "
        "bound to all three metrics. Nothing synced to Delta."
    )


if __name__ == "__main__":
    main()

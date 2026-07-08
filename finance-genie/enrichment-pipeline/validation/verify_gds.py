# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "neo4j>=5.20",
#     "python-dotenv>=1.0",
#     "graphdatascience>=1.12",
#     "pandas>=2.0",
# ]
# ///
"""Verify GDS outputs against ground truth.

Run after run_gds.py completes. Connects to Neo4j, runs signal checks,
and prints a summary report. Exits 0 if all checks pass, 1 if any fail.

Run from enrichment-pipeline/:

    uv run validation/verify_gds.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from graphdatascience import GraphDataScience
from neo4j.exceptions import AuthError, ServiceUnavailable

from _common import fail, header, load_env, ok, warn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jobs"))
from _gold_constants import (  # noqa: E402
    GDS_BETWEENNESS_RATIO_MIN as BETWEENNESS_RATIO_MIN,
    GDS_COMMUNITY_PURITY_MIN as COMMUNITY_PURITY_MIN,
    GDS_PR_RATIO_MIN as PR_RATIO_MIN,
    GDS_RING_EXCLUSION_MAX as RING_EXCLUSION_MAX,
    GDS_SIM_RATIO_MIN as SIM_RATIO_MIN,
)

# Precision warning threshold. Not a hard gate — the check prints WARN and
# reports the number without failing the pipeline. See RAISE_PURITY.md for
# rationale on why this is not yet a FAIL threshold.
_PRECISION_WARN = 0.70

REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
MAX_COMMUNITIES_OK = 500

# Must match the degreeCutoff used in run_gds.py.
NODESIM_DEGREE_CUTOFF = 5

# Must match KYC_BUSINESS_TERM in run_gds.py.
KYC_BUSINESS_TERM = "Shared Identity Ring"

# Summary table column widths
_LABEL_W = 38
_STATUS_W = 4


def load_ground_truth(script_dir: Path) -> dict:
    gt_path = script_dir.parent.parent / "data" / "ground_truth.json"
    if not gt_path.is_file():
        fail(f"ground_truth.json not found at {gt_path}")
    return json.loads(gt_path.read_text())


def connect(uri: str, user: str, password: str) -> GraphDataScience:
    try:
        gds = GraphDataScience(uri, auth=(user, password))
        print(f"OK    connected  |  GDS client v{gds.version()}")
        return gds
    except AuthError as e:
        fail(f"authentication failed: {e}")
    except ServiceUnavailable as e:
        fail(f"cannot reach Neo4j at {uri}: {e}")
    except Exception as e:
        fail(f"GDS client error: {e}")


def check_feature_completeness(gds: GraphDataScience) -> tuple[list[str], str]:
    problems: list[str] = []
    row = gds.run_cypher(
        """
        MATCH (a:Account)
        RETURN count(a) AS total,
               sum(CASE WHEN a.risk_score       IS NOT NULL THEN 1 ELSE 0 END) AS has_pr,
               sum(CASE WHEN a.community_id     IS NOT NULL THEN 1 ELSE 0 END) AS has_cid,
               sum(CASE
                     WHEN a.betweenness_centrality IS NOT NULL THEN 1 ELSE 0
                   END) AS has_betweenness,
               sum(CASE WHEN a.similarity_score IS NOT NULL THEN 1 ELSE 0 END) AS has_sim,
               sum(CASE
                     WHEN (a.risk_score IS NULL) <> (a.betweenness_centrality IS NULL)
                     THEN 1 ELSE 0
                   END) AS risk_betweenness_mismatch
        """
    ).iloc[0]
    print(
        f"      {row['total']:,} accounts | risk_score={row['has_pr']:,}  "
        f"community_id={row['has_cid']:,}  "
        f"betweenness_centrality={row['has_betweenness']:,}  "
        f"similarity_score={row['has_sim']:,}"
    )
    for name, label in (
        ("has_pr", "risk_score"),
        ("has_cid", "community_id"),
        ("has_betweenness", "betweenness_centrality"),
        ("has_sim", "similarity_score"),
    ):
        if int(row[name]) < int(row["total"]):
            problems.append(
                f"{label} set on only {int(row[name]):,}/{int(row['total']):,} accounts"
            )
    mismatch = int(row["risk_betweenness_mismatch"] or 0)
    if mismatch:
        problems.append(
            "betweenness_centrality is not populated on the same node set as risk_score "
            f"({mismatch:,} mismatches)"
        )
    detail = "all 4 properties set" if not problems else f"{len(problems)} property gap(s)"
    return problems, detail


def check_pagerank(gds: GraphDataScience, fraud_ids: list[int]) -> tuple[list[str], str]:
    problems: list[str] = []
    stats = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.risk_score IS NOT NULL
        RETURN min(a.risk_score) AS mn, max(a.risk_score) AS mx,
               avg(a.risk_score) AS av
        """
    ).iloc[0]
    print(
        f"      risk_score: min={stats['mn']:.4f}  max={stats['mx']:.4f}  "
        f"avg={stats['av']:.4f}"
    )
    if stats["mx"] == stats["mn"]:
        problems.append("risk_score is constant — PageRank did not differentiate nodes")
        return problems, "constant (no signal)"

    top20 = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.risk_score IS NOT NULL
        RETURN a.account_id AS id, a.risk_score AS score
        ORDER BY a.risk_score DESC LIMIT 20
        """
    )
    fraud_set = set(fraud_ids)
    top20_fraud = sum(1 for i in top20["id"] if int(i) in fraud_set)
    top20_frac = top20_fraud / len(top20) if len(top20) else 0.0
    print(f"      top-20 by risk_score: {top20_fraud}/20 are fraud ({top20_frac:.0%})")

    averages = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.risk_score IS NOT NULL
        RETURN
          avg(CASE WHEN a.account_id IN $fraud_ids     THEN a.risk_score END) AS fraud_avg,
          avg(CASE WHEN NOT a.account_id IN $fraud_ids THEN a.risk_score END) AS normal_avg
        """,
        params={"fraud_ids": fraud_ids},
    ).iloc[0]
    fraud_avg = float(averages["fraud_avg"] or 0.0)
    normal_avg = float(averages["normal_avg"] or 0.0)
    ratio = fraud_avg / normal_avg if normal_avg else float("inf")
    print(
        f"      fraud avg={fraud_avg:.4f}  normal avg={normal_avg:.4f}  "
        f"ratio={ratio:.2f}×  (min {PR_RATIO_MIN}×)"
    )

    if ratio < PR_RATIO_MIN:
        problems.append(f"fraud/normal PageRank ratio {ratio:.2f}× < {PR_RATIO_MIN}×")
    return problems, f"ratio={ratio:.2f}×  (min {PR_RATIO_MIN}×)"


def check_betweenness(
    gds: GraphDataScience, fraud_ids: list[int]
) -> tuple[list[str], str]:
    problems: list[str] = []
    stats = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.betweenness_centrality IS NOT NULL
        RETURN min(a.betweenness_centrality) AS mn,
               max(a.betweenness_centrality) AS mx,
               avg(a.betweenness_centrality) AS av
        """
    ).iloc[0]
    print(
        f"      betweenness_centrality: min={stats['mn']:.4f}  "
        f"max={stats['mx']:.4f}  avg={stats['av']:.4f}"
    )
    if stats["mx"] == stats["mn"]:
        problems.append(
            "betweenness_centrality is constant — Betweenness did not differentiate nodes"
        )
        return problems, "constant (no signal)"

    averages = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.betweenness_centrality IS NOT NULL
        RETURN
          avg(CASE
                WHEN a.account_id IN $fraud_ids
                THEN a.betweenness_centrality
              END) AS fraud_avg,
          avg(CASE
                WHEN NOT a.account_id IN $fraud_ids
                THEN a.betweenness_centrality
              END) AS normal_avg
        """,
        params={"fraud_ids": fraud_ids},
    ).iloc[0]
    fraud_avg = float(averages["fraud_avg"] or 0.0)
    normal_avg = float(averages["normal_avg"] or 0.0)
    ratio = fraud_avg / normal_avg if normal_avg else float("inf")
    print(
        f"      fraud avg={fraud_avg:.4f}  normal avg={normal_avg:.4f}  "
        f"ratio={ratio:.2f}×  (min {BETWEENNESS_RATIO_MIN}×)"
    )

    if ratio <= BETWEENNESS_RATIO_MIN:
        problems.append(
            "fraud/normal betweenness ratio "
            f"{ratio:.2f}× <= {BETWEENNESS_RATIO_MIN}×"
        )
    return problems, f"ratio={ratio:.2f}×  (min > {BETWEENNESS_RATIO_MIN}×)"


def check_louvain_per_ring(
    gds: GraphDataScience, rings: list[dict]
) -> tuple[list[str], str]:
    problems: list[str] = []

    sizes = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.community_id IS NOT NULL
        RETURN a.community_id AS cid, count(*) AS size
        """
    )
    cid_to_size = {int(r["cid"]): int(r["size"]) for _, r in sizes.iterrows()}
    n_communities = len(cid_to_size)
    print(f"      total communities: {n_communities:,}")

    if n_communities > MAX_COMMUNITIES_OK:
        problems.append(
            f"{n_communities:,} communities is excessive (>{MAX_COMMUNITIES_OK}). "
            f"Louvain fragmented the graph — indicates a sparse projection."
        )

    total_ring_coverage: list[float] = []
    purity_values: list[float] = []
    for ring in rings:
        ring_id = ring["ring_id"]
        members = [int(a) for a in ring["account_ids"]]

        cid_counts = gds.run_cypher(
            """
            MATCH (a:Account)
            WHERE a.account_id IN $members
            RETURN a.community_id AS cid, count(*) AS members_in_cid
            ORDER BY members_in_cid DESC
            """,
            params={"members": members},
        )
        if cid_counts.empty:
            problems.append(f"ring {ring_id}: no community_id set on any member")
            continue

        dominant_cid = int(cid_counts.iloc[0]["cid"])
        dominant_members = int(cid_counts.iloc[0]["members_in_cid"])
        coverage = dominant_members / len(members)
        dominant_size = cid_to_size.get(dominant_cid, 0)
        purity = dominant_members / dominant_size if dominant_size else 0.0
        distinct_cids = len(cid_counts)

        total_ring_coverage.append(coverage)
        purity_values.append(purity)
        print(
            f"      ring {ring_id}: {len(members)} members split across "
            f"{distinct_cids} communities | top cid={dominant_cid} "
            f"({dominant_members}/{len(members)} = {coverage:.0%} of ring, "
            f"purity {purity:.0%} of {dominant_size}-node community)"
        )

        if coverage < 0.80:
            problems.append(
                f"ring {ring_id}: only {coverage:.0%} of members in its dominant "
                f"community — Louvain is splitting the ring"
            )

    if purity_values:
        avg_purity = sum(purity_values) / len(purity_values)
        avg_coverage = (
            sum(total_ring_coverage) / len(total_ring_coverage)
            if total_ring_coverage
            else 0.0
        )
        print(
            f"      avg community purity: {avg_purity:.0%}  "
            f"avg ring coverage: {avg_coverage:.0%}  "
            f"(min purity {COMMUNITY_PURITY_MIN:.0%})"
        )
        if avg_purity < COMMUNITY_PURITY_MIN:
            problems.append(
                f"avg Louvain purity {avg_purity:.0%} < {COMMUNITY_PURITY_MIN:.0%} — "
                f"communities absorbing too many non-fraud accounts"
            )
        detail = f"purity={avg_purity:.0%}  coverage={avg_coverage:.0%}  (min purity {COMMUNITY_PURITY_MIN:.0%})"
    else:
        detail = "no rings found"
    return problems, detail


def check_similarity(
    gds: GraphDataScience, fraud_ids: list[int]
) -> tuple[list[str], str]:
    problems: list[str] = []
    row = gds.run_cypher(
        "MATCH ()-[s:SIMILAR_TO]->() RETURN count(s) AS n"
    ).iloc[0]
    n_sim = int(row["n"])
    print(f"      :SIMILAR_TO relationships: {n_sim:,}")
    if n_sim == 0:
        problems.append("no :SIMILAR_TO relationships written")
        return problems, "0 relationships"

    averages = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.similarity_score IS NOT NULL
        RETURN
          avg(CASE WHEN a.account_id IN $fraud_ids     THEN a.similarity_score END) AS fraud_avg,
          avg(CASE WHEN NOT a.account_id IN $fraud_ids THEN a.similarity_score END) AS normal_avg
        """,
        params={"fraud_ids": fraud_ids},
    ).iloc[0]
    fraud_avg = float(averages["fraud_avg"] or 0.0)
    normal_avg = float(averages["normal_avg"] or 0.0)
    ratio = fraud_avg / normal_avg if normal_avg else float("inf")
    print(
        f"      fraud avg={fraud_avg:.4f}  normal avg={normal_avg:.4f}  "
        f"ratio={ratio:.2f}×  (min {SIM_RATIO_MIN}×)"
    )

    if ratio < SIM_RATIO_MIN:
        problems.append(f"fraud/normal similarity ratio {ratio:.2f}× < {SIM_RATIO_MIN}×")
    return problems, f"ratio={ratio:.2f}×  (min {SIM_RATIO_MIN}×)"


def check_ring_member_nodesim_exclusion(
    gds: GraphDataScience, fraud_ids: list[int]
) -> tuple[list[str], str]:
    """Fraction of ring-member accounts excluded from the NodeSim bipartite
    projection by degreeCutoff. Ring members with fewer than the cutoff unique
    TRANSACTED_WITH targets carry similarity_score=0 but still land as
    fraud_risk_tier='high' via is_ring_community."""
    problems: list[str] = []

    row = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.account_id IN $fraud_ids
        OPTIONAL MATCH (a)-[:TRANSACTED_WITH]->(m:Merchant)
        WITH a, count(DISTINCT m) AS uniq_merchants
        RETURN count(a) AS total,
               sum(CASE WHEN uniq_merchants < $cutoff THEN 1 ELSE 0 END) AS excluded,
               avg(uniq_merchants) AS avg_uniq
        """,
        params={"fraud_ids": fraud_ids, "cutoff": NODESIM_DEGREE_CUTOFF},
    ).iloc[0]

    total = int(row["total"])
    excluded = int(row["excluded"])
    avg_uniq = float(row["avg_uniq"] or 0.0)
    frac = excluded / total if total else 0.0

    print(
        f"      ring members: {total:,}  "
        f"avg unique merchants: {avg_uniq:.1f}  "
        f"excluded at cutoff {NODESIM_DEGREE_CUTOFF}: {excluded:,} "
        f"({frac:.1%})  (max {RING_EXCLUSION_MAX:.0%})"
    )

    if frac > RING_EXCLUSION_MAX:
        problems.append(
            f"ring-member exclusion {frac:.1%} > {RING_EXCLUSION_MAX:.0%} "
            f"— similarity_score=0 coverage will drop below demo viability"
        )
    return problems, f"excluded={frac:.1%}  (max {RING_EXCLUSION_MAX:.0%})"


def check_ring_candidate_precision(
    gds: GraphDataScience, rings: list[dict], fraud_ids: list[int]
) -> tuple[list[str], str]:
    """Measure how many non-fraud accounts land in ring-candidate communities.

    Finds the dominant community ID for each planted ring, counts every account
    in those communities, and reports precision = fraud_in_candidates / total_in_candidates.
    This is a warning-only check — it never fails the pipeline. A number here is
    the input needed to decide whether to raise GDS_COMMUNITY_PURITY_MIN.
    See RAISE_PURITY.md for context.
    """
    dominant_cids: list[int] = []
    for ring in rings:
        members = [int(a) for a in ring["account_ids"]]
        cid_counts = gds.run_cypher(
            """
            MATCH (a:Account) WHERE a.account_id IN $members
            RETURN a.community_id AS cid, count(*) AS n
            ORDER BY n DESC LIMIT 1
            """,
            params={"members": members},
        )
        if not cid_counts.empty:
            dominant_cids.append(int(cid_counts.iloc[0]["cid"]))

    if not dominant_cids:
        warn("no dominant communities found — skipping precision check")
        return [], "skipped (no communities)"

    fraud_set = set(fraud_ids)
    row = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.community_id IN $cids
        RETURN count(a) AS total,
               sum(CASE WHEN a.account_id IN $fraud_ids THEN 1 ELSE 0 END) AS fraud_count
        """,
        params={"cids": dominant_cids, "fraud_ids": list(fraud_set)},
    ).iloc[0]

    total = int(row["total"])
    fraud_count = int(row["fraud_count"])
    precision = fraud_count / total if total else 0.0
    true_rate = len(fraud_set) / 25_000

    print(
        f"      ring-candidate accounts: {total:,}  fraud in candidates: {fraud_count:,}  "
        f"precision: {precision:.1%}  (book fraud rate: {true_rate:.1%})"
    )
    print(
        f"      over-labeling: {total - fraud_count:,} non-fraud accounts in candidate communities"
    )

    if precision < _PRECISION_WARN:
        warn(
            f"ring-candidate precision {precision:.1%} < {_PRECISION_WARN:.0%} — "
            f"communities are absorbing too many non-fraud accounts. "
            f"See RAISE_PURITY.md."
        )

    return [], f"precision={precision:.1%}  (warn below {_PRECISION_WARN:.0%})  [diagnostic only]"


def check_kyc_identity(gds: GraphDataScience, kyc: dict) -> tuple[list[str], str]:
    """Verify graph identity resolution against the kyc_story_ring ground truth.

    The story ring must resolve to one WCC identity cluster containing exactly
    its 8 accounts, its shared counts must match the planted phone and address
    groups, and zero background accounts may show any shared-identity signal.
    """
    problems: list[str] = []
    story_ids = [int(a) for a in kyc["account_ids"]]

    # Expected per-account counts derived from the planted groups: each member
    # shares its identifier with (group size - 1) other customers.
    expected_phone = {a: 0 for a in story_ids}
    for ids in kyc["shared_phones"].values():
        for a in ids:
            expected_phone[int(a)] = len(ids) - 1
    expected_address = {a: 0 for a in story_ids}
    for ids in kyc["shared_address"].values():
        for a in ids:
            expected_address[int(a)] = len(ids) - 1

    coverage = gds.run_cypher(
        """
        MATCH (a:Account)
        RETURN count(a) AS total,
               count(a.identity_cluster_id)   AS has_cid,
               count(a.identity_cluster_size) AS has_size,
               count(a.shared_phone_count)    AS has_phone,
               count(a.shared_address_count)  AS has_address
        """
    ).iloc[0]
    total = int(coverage["total"])
    print(
        f"      {total:,} accounts | identity_cluster_id={int(coverage['has_cid']):,}  "
        f"identity_cluster_size={int(coverage['has_size']):,}  "
        f"shared_phone_count={int(coverage['has_phone']):,}  "
        f"shared_address_count={int(coverage['has_address']):,}"
    )
    for name, label in (
        ("has_cid", "identity_cluster_id"),
        ("has_size", "identity_cluster_size"),
        ("has_phone", "shared_phone_count"),
        ("has_address", "shared_address_count"),
    ):
        if int(coverage[name]) < total:
            problems.append(
                f"{label} set on only {int(coverage[name]):,}/{total:,} accounts"
            )
    if problems:
        return problems, "identity properties missing"

    cids = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.account_id IN $ids
        RETURN collect(DISTINCT a.identity_cluster_id) AS cids
        """,
        params={"ids": story_ids},
    ).iloc[0]["cids"]
    if len(cids) != 1:
        problems.append(
            f"story ring spans {len(cids)} identity clusters, expected 1: {cids}"
        )
        return problems, f"{len(cids)} clusters for story ring"

    cluster_members = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.identity_cluster_id = $cid
        RETURN collect(a.account_id) AS ids
        """,
        params={"cid": int(cids[0])},
    ).iloc[0]["ids"]
    member_set = {int(a) for a in cluster_members}
    print(
        f"      story cluster {int(cids[0])}: {len(member_set)} accounts "
        f"(expected {len(story_ids)})"
    )
    if member_set != set(story_ids):
        problems.append(
            f"story identity cluster is {sorted(member_set)}, "
            f"expected exactly {sorted(story_ids)}"
        )

    wrong_size = gds.run_cypher(
        """
        MATCH (a:Account)
        WHERE a.account_id IN $ids AND a.identity_cluster_size <> $n
        RETURN count(a) AS n
        """,
        params={"ids": story_ids, "n": len(story_ids)},
    ).iloc[0]["n"]
    if int(wrong_size):
        problems.append(
            f"{int(wrong_size)} story accounts have identity_cluster_size != "
            f"{len(story_ids)}"
        )

    background_shared = gds.run_cypher(
        """
        MATCH (a:Account)
        WHERE NOT a.account_id IN $ids
          AND (a.identity_cluster_size > 1
               OR a.shared_phone_count > 0
               OR a.shared_address_count > 0)
        RETURN count(a) AS n
        """,
        params={"ids": story_ids},
    ).iloc[0]["n"]
    print(
        f"      background accounts with any shared-identity signal: "
        f"{int(background_shared):,}"
    )
    if int(background_shared):
        problems.append(
            f"{int(background_shared):,} background accounts show shared-identity "
            f"signal — background data contaminated the story ring"
        )

    counts = gds.run_cypher(
        """
        MATCH (a:Account) WHERE a.account_id IN $ids
        RETURN a.account_id AS id,
               a.shared_phone_count AS spc,
               a.shared_address_count AS sac
        """,
        params={"ids": story_ids},
    )
    mismatches = [
        f"account {int(r['id'])}: phone {int(r['spc'])} "
        f"(want {expected_phone[int(r['id'])]}), address {int(r['sac'])} "
        f"(want {expected_address[int(r['id'])]})"
        for _, r in counts.iterrows()
        if int(r["spc"]) != expected_phone[int(r["id"])]
        or int(r["sac"]) != expected_address[int(r["id"])]
    ]
    print(
        f"      shared counts match ground truth on "
        f"{len(story_ids) - len(mismatches)}/{len(story_ids)} story accounts"
    )
    for m in mismatches:
        problems.append(f"shared count mismatch — {m}")

    detail = (
        f"cluster of {len(member_set)}/{len(story_ids)}, background clean"
        if not problems
        else f"{len(problems)} identity problem(s)"
    )
    return problems, detail


def check_kyc_provenance(gds: GraphDataScience, kyc: dict) -> tuple[list[str], str]:
    """Verify the knowledge layer makes a KYC violation explainable as a traversal.

    The 8 story-ring customers — owners of the 8 ground-truth accounts, mapped
    via OWNS — must each be CLASSIFIED_AS 'Shared Identity Ring' and no
    background customer may be. The explain path must resolve end to end:
    (:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule)
    plus (:BusinessTerm)-[:GOVERNED_BY]->(:Policy) and
    (:BusinessRule)-[:DERIVED_FROM]->(:DataSource).
    """
    problems: list[str] = []
    story_ids = [int(a) for a in kyc["account_ids"]]

    # Story accounts map to their owning customers via OWNS.
    owners = gds.run_cypher(
        """
        MATCH (c:Customer)-[:OWNS]->(a:Account)
        WHERE a.account_id IN $ids
        RETURN collect(DISTINCT c.customer_id) AS ids
        """,
        params={"ids": story_ids},
    ).iloc[0]["ids"]
    story_owner_ids = {int(c) for c in owners}
    print(
        f"      story ring: {len(story_ids)} accounts owned by "
        f"{len(story_owner_ids)} customers"
    )
    if len(story_owner_ids) != len(story_ids):
        problems.append(
            f"{len(story_ids)} story accounts map to {len(story_owner_ids)} "
            f"owning customers, expected {len(story_ids)}"
        )

    classified = gds.run_cypher(
        """
        MATCH (c:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm {name: $term})
        RETURN collect(DISTINCT c.customer_id) AS ids
        """,
        params={"term": KYC_BUSINESS_TERM},
    ).iloc[0]["ids"]
    classified_ids = {int(c) for c in classified}
    story_classified = classified_ids & story_owner_ids
    background_classified = classified_ids - story_owner_ids
    print(
        f"      CLASSIFIED_AS '{KYC_BUSINESS_TERM}': {len(classified_ids)} customers "
        f"({len(story_classified)} story, {len(background_classified)} background)"
    )
    missing = story_owner_ids - classified_ids
    if missing:
        problems.append(
            f"{len(missing)} story-ring customers are not CLASSIFIED_AS "
            f"'{KYC_BUSINESS_TERM}'"
        )
    if background_classified:
        problems.append(
            f"{len(background_classified)} background customers are CLASSIFIED_AS "
            f"'{KYC_BUSINESS_TERM}' — expected 0"
        )

    # The provenance path from the term back to the policy and data sources.
    path = gds.run_cypher(
        """
        MATCH (term:BusinessTerm {name: $term})
        RETURN count { (term)-[:GOVERNED_BY]->(:Policy) }      AS policy,
               count { (term)-[:DEFINED_BY]->(:BusinessRule) } AS rule,
               count { (term)-[:DEFINED_BY]->(:BusinessRule)
                             -[:DERIVED_FROM]->(:DataSource) } AS sources
        """,
        params={"term": KYC_BUSINESS_TERM},
    ).iloc[0]
    n_policy = int(path["policy"])
    n_rule = int(path["rule"])
    n_sources = int(path["sources"])
    print(
        f"      explain path: GOVERNED_BY :Policy={n_policy}  "
        f"DEFINED_BY :BusinessRule={n_rule}  "
        f"DERIVED_FROM :DataSource={n_sources}"
    )
    if n_policy < 1:
        problems.append("BusinessTerm has no GOVERNED_BY edge to a :Policy")
    if n_rule < 1:
        problems.append("BusinessTerm has no DEFINED_BY edge to a :BusinessRule")
    if n_sources < 1:
        problems.append("BusinessRule has no DERIVED_FROM edge to a :DataSource")

    detail = (
        f"{len(story_classified)}/{len(story_ids)} story classified, "
        f"{len(background_classified)} background, path resolves"
        if not problems
        else f"{len(problems)} provenance problem(s)"
    )
    return problems, detail


def print_summary(results: list[tuple[str, list[str], str]]) -> list[str]:
    W = 62
    all_problems: list[str] = []

    print()
    print("═" * W)
    print("VERIFICATION SUMMARY")
    print("═" * W)
    for label, problems, detail in results:
        status = "PASS" if not problems else "FAIL"
        print(f"  {label:<{_LABEL_W}}{status:<{_STATUS_W}}  {detail}")
        all_problems.extend(problems)
    print("─" * W)

    n_total = len(results)
    n_fail = sum(1 for _, p, _ in results if p)
    if all_problems:
        print(f"Result: FAIL  {n_fail}/{n_total} checks failed")
        print()
        for p in all_problems:
            print(f"  ✗ {p}")
    else:
        print(f"Result: PASS  {n_total}/{n_total} checks passed")
    print("═" * W)

    return all_problems


def main() -> None:
    load_env(REQUIRED_VARS)
    script_dir = Path(__file__).parent
    gt = load_ground_truth(script_dir)
    rings = gt["rings"]
    fraud_ids = [int(a) for r in rings for a in r["account_ids"]]
    kyc_story = gt.get("kyc_story_ring")
    if not kyc_story:
        fail("kyc_story_ring missing from ground_truth.json — regenerate the data layer")
    ok(f"ground_truth.json loaded: {len(rings)} rings, {len(fraud_ids):,} fraud accounts")

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]

    gds = connect(uri, user, password)

    try:
        results: list[tuple[str, list[str], str]] = []

        header("[1/9] Feature completeness")
        problems, detail = check_feature_completeness(gds)
        results.append(("[1/9] Feature completeness", problems, detail))

        header("[2/9] PageRank (risk_score)")
        problems, detail = check_pagerank(gds, fraud_ids)
        results.append(("[2/9] PageRank (risk_score)", problems, detail))

        header("[3/9] Betweenness (betweenness_centrality)")
        problems, detail = check_betweenness(gds, fraud_ids)
        results.append(("[3/9] Betweenness", problems, detail))

        header("[4/9] Louvain (community_id) — per-ring coverage")
        problems, detail = check_louvain_per_ring(gds, rings)
        results.append(("[4/9] Louvain (community_id)", problems, detail))

        header("[5/9] Node Similarity (similarity_score)")
        problems, detail = check_similarity(gds, fraud_ids)
        results.append(("[5/9] Node Similarity", problems, detail))

        header("[6/9] Ring-member NodeSim exclusion (degreeCutoff)")
        problems, detail = check_ring_member_nodesim_exclusion(gds, fraud_ids)
        results.append(("[6/9] Ring-member exclusion", problems, detail))

        header("[7/9] Ring-candidate population precision (diagnostic)")
        problems, detail = check_ring_candidate_precision(gds, rings, fraud_ids)
        results.append(("[7/9] Ring-candidate precision", problems, detail))

        header("[8/9] KYC identity resolution (WCC + shared counts)")
        problems, detail = check_kyc_identity(gds, kyc_story)
        results.append(("[8/9] KYC identity resolution", problems, detail))

        header("[9/9] KYC provenance (knowledge layer)")
        problems, detail = check_kyc_provenance(gds, kyc_story)
        results.append(("[9/9] KYC provenance", problems, detail))

        all_problems = print_summary(results)
        if all_problems:
            sys.exit(1)
    finally:
        try:
            gds.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

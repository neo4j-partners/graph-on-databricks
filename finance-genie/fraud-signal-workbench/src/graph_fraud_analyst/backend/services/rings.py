"""Ring search service, backed by live Cypher against Aura.

Two Cypher round-trips per call:
  1. Summaries: ring-candidate communities with avg risk, member count, anchor
     merchant categories, total volume. Top-N by avg risk_score.
  2. Details: full :Account node list and within-community TRANSFERRED_TO edges
     for every ring returned by the summary. No node or edge caps — the demo
     surfaces the real graph shape per community.

Shape parity with the previous SQL-backed version: same RingOut fields, so the
frontend OpenAPI client requires no regeneration. The `graph` field now
carries real Cytoscape-renderable nodes and edges instead of empty arrays.
"""

from __future__ import annotations

from neo4j import Driver

from ..models import Graph, GraphEdge, GraphNode, Risk, RingOut

# Minimum community size to count as a ring-candidate. Matches the
# enrichment-pipeline's is_ring_candidate gate (member_count >= 3).
_MIN_MEMBERS = 3

# Cap returned rings; mirrors the SQL LIMIT 20 from the previous gold-table
# query and keeps payloads small.
_TOP_N = 20

# Per-ring, mark this many highest-betweenness members as `is_hub=True`.
_HUB_COUNT_PER_RING = 3


def _risk_band(score: float, max_score: float) -> Risk:
    normalized = score / max_score if max_score > 0 else 0.0
    if normalized >= 0.75:
        return "H"
    if normalized >= 0.5:
        return "M"
    return "L"


_RINGS_SUMMARY_CYPHER = """
MATCH (a:Account)
WHERE a.community_id IS NOT NULL
WITH a.community_id AS community_id,
     count(a)       AS member_count,
     avg(a.risk_score) AS avg_risk_score
WHERE member_count >= $min_members AND member_count <= $max_nodes
OPTIONAL MATCH (b:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
WHERE b.community_id = community_id
WITH community_id, member_count, avg_risk_score,
     collect(DISTINCT m.category) AS categories,
     sum(t.amount)                AS total_volume
RETURN community_id,
       member_count,
       avg_risk_score,
       categories[0..3] AS anchor_merchant_categories,
       coalesce(total_volume, 0)  AS total_volume_usd
ORDER BY avg_risk_score DESC
LIMIT $top_n
"""


_RINGS_DETAILS_CYPHER = """
UNWIND $cids AS cid
MATCH (a:Account) WHERE a.community_id = cid
WITH cid,
     collect({
       account_id: a.account_id,
       risk_score: a.risk_score,
       betweenness: a.betweenness_centrality
     }) AS nodes,
     collect(a.account_id) AS ids
OPTIONAL MATCH (m1:Account)-[:TRANSFERRED_TO]->(m2:Account)
WHERE m1.community_id = cid
  AND m2.community_id = cid
  AND m1.account_id IN ids
  AND m2.account_id IN ids
WITH cid, nodes,
     collect(DISTINCT {src: m1.account_id, dst: m2.account_id}) AS edges
RETURN cid, nodes, [e IN edges WHERE e.dst IS NOT NULL] AS edges
"""


def _build_graph(
    raw_nodes: list[dict],
    raw_edges: list[dict],
) -> Graph:
    """Convert Neo4j node/edge records into the Graph response model.

    Risk band per node is computed relative to the max risk_score in this ring.
    `is_hub` marks the top _HUB_COUNT_PER_RING by betweenness within the ring.
    """
    if not raw_nodes:
        return Graph(nodes=[], edges=[])

    max_score = max(
        (float(n.get("risk_score") or 0) for n in raw_nodes), default=0.0
    )

    # Highest betweenness within this ring → marked as hubs.
    ordered_by_betweenness = sorted(
        raw_nodes,
        key=lambda n: float(n.get("betweenness") or 0),
        reverse=True,
    )
    hub_ids = {
        str(n.get("account_id"))
        for n in ordered_by_betweenness[:_HUB_COUNT_PER_RING]
    }

    nodes: list[GraphNode] = []
    for n in raw_nodes:
        node_id = str(n.get("account_id"))
        nodes.append(
            GraphNode(
                id=node_id,
                risk=_risk_band(float(n.get("risk_score") or 0), max_score),
                is_hub=node_id in hub_ids,
            )
        )

    edges: list[GraphEdge] = []
    for e in raw_edges:
        src = e.get("src")
        dst = e.get("dst")
        if src is None or dst is None:
            continue
        edges.append(GraphEdge(source=str(src), target=str(dst)))

    return Graph(nodes=nodes, edges=edges)


def list_rings(driver: Driver, max_nodes: int) -> list[RingOut]:
    """Return up to _TOP_N ring-candidate communities, each with real graph data."""
    with driver.session() as session:
        summaries = session.run(
            _RINGS_SUMMARY_CYPHER,
            min_members=_MIN_MEMBERS,
            max_nodes=int(max_nodes),
            top_n=_TOP_N,
        ).data()

        if not summaries:
            return []

        cids = [s["community_id"] for s in summaries]
        details = session.run(_RINGS_DETAILS_CYPHER, cids=cids).data()

    details_by_cid = {d["cid"]: d for d in details}
    max_summary_score = max(
        (float(s.get("avg_risk_score") or 0) for s in summaries), default=0.0
    )

    out: list[RingOut] = []
    for s in summaries:
        cid = s["community_id"]
        raw_risk_score = float(s.get("avg_risk_score") or 0)
        normalized_risk_score = (
            raw_risk_score / max_summary_score if max_summary_score > 0 else 0.0
        )
        anchors = s.get("anchor_merchant_categories") or []
        if not isinstance(anchors, list):
            anchors = []

        d = details_by_cid.get(cid, {"nodes": [], "edges": []})
        graph = _build_graph(d.get("nodes", []) or [], d.get("edges", []) or [])

        out.append(
            RingOut(
                ring_id=str(cid),
                nodes=int(s.get("member_count") or 0),
                volume=int(float(s.get("total_volume_usd") or 0)),
                shared_identifiers=[str(a) for a in anchors],
                risk=_risk_band(raw_risk_score, max_summary_score),
                risk_score=normalized_risk_score,
                # Topology defaults to "mesh"; the UI uses the real graph
                # nodes/edges with Cytoscape's cose layout for the tile, so
                # the per-ring topology label is informational only.
                topology="mesh",
                graph=graph,
            )
        )
    return out

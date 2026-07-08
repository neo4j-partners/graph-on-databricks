# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "neo4j>=5.20",
#     "python-dotenv>=1.0",
#     "graphdatascience>=1.12",
#     "pandas>=2.0",
# ]
# ///
"""Run the GDS pipeline against Neo4j Aura.

Mirrors the algorithm steps in workshop/02_aura_gds_guide.ipynb — writes
risk_score, betweenness_centrality, community_id, and similarity_score to every
:Account node, and creates :SIMILAR_TO relationships. Then runs WCC identity
resolution over the Customer/Phone/Address graph and writes identity_cluster_id,
identity_cluster_size, shared_phone_count, and shared_address_count to every
:Customer node and its owned :Account node. Finally it builds a thin KYC
knowledge layer (:Policy/:BusinessTerm/:BusinessRule/:DataSource) and links
every shared-identity customer to it with a :CLASSIFIED_AS edge, so a KYC
violation can be explained by graph traversal. Exits 0 on success, 1 on failure.

Run from enrichment-pipeline/:

    uv run validation/run_gds.py

Verify the outputs afterwards with:

    uv run validation/verify_gds.py
"""

from __future__ import annotations

import os

from graphdatascience import GraphDataScience
from neo4j.exceptions import AuthError, ServiceUnavailable

from _common import fail, header, load_env, ok

REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
EXPECTED_ACCOUNTS = 25_000

# NodeSimilarity degreeCutoff used in the pipeline below. Ring members whose
# unique TRANSACTED_WITH degree falls below this threshold are excluded from
# the bipartite projection and land with similarity_score=0. Keep this value
# synchronized with verify_gds.py and the writeRelationship call below.
NODESIM_DEGREE_CUTOFF = 5

# Exact betweenness is expensive on the 25k-node workshop graph. A fixed sample
# keeps demo runs predictable while preserving the "broker account" signal.
BETWEENNESS_SAMPLING_SIZE = 1_000
BETWEENNESS_SAMPLING_SEED = 42

# BusinessTerm the KYC knowledge layer classifies shared-identity customers as.
# Duplicated in verify_gds.py — keep the two in sync.
KYC_BUSINESS_TERM = "Shared Identity Ring"


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


def drop_if_exists(gds: GraphDataScience, name: str) -> None:
    gds.run_cypher("CALL gds.graph.drop($name, false) YIELD graphName", params={"name": name})


def run_pipeline(gds: GraphDataScience) -> None:
    header("Step 1: graph sanity")
    # COUNT {} subqueries instead of chained MATCH: a chained MATCH on a label
    # with zero nodes returns an empty result set, which would crash .iloc[0]
    # instead of reaching the clear fail() below.
    counts = gds.run_cypher(
        """
        RETURN count { (a:Account) } AS accounts,
               count { (m:Merchant) } AS merchants,
               count { (c:Customer) } AS customers,
               count { ()-[:TRANSACTED_WITH]->() } AS txns,
               count { ()-[:TRANSFERRED_TO]->() } AS p2p
        """
    ).iloc[0]
    print(
        f"      accounts={counts['accounts']:,}  merchants={counts['merchants']:,}  "
        f"customers={counts['customers']:,}  txns={counts['txns']:,}  "
        f"p2p={counts['p2p']:,}"
    )
    if counts["accounts"] != EXPECTED_ACCOUNTS:
        fail(f"account count {counts['accounts']} != {EXPECTED_ACCOUNTS}")
    if counts["customers"] != EXPECTED_ACCOUNTS:
        fail(
            f"customer count {counts['customers']} != {EXPECTED_ACCOUNTS} — "
            "re-run jobs/02_neo4j_ingest.py to load the identity layer"
        )

    header("Step 2: project account_transfers (UNDIRECTED)")
    drop_if_exists(gds, "account_transfers")
    G, stats = gds.graph.project(
        "account_transfers",
        "Account",
        {"TRANSFERRED_TO": {"orientation": "UNDIRECTED"}},
    )
    print(
        f"      projected '{G.name()}': {stats['nodeCount']:,} nodes, "
        f"{stats['relationshipCount']:,} relationships"
    )

    header("Step 3: PageRank.write → risk_score")
    pr = gds.pageRank.write(
        G, maxIterations=20, dampingFactor=0.85, writeProperty="risk_score"
    )
    print(
        f"      propertiesWritten={int(pr['nodePropertiesWritten']):,}  "
        f"iterations={int(pr['ranIterations'])}  converged={bool(pr['didConverge'])}"
    )

    header("Step 4: Louvain.write → community_id")
    louvain = gds.louvain.write(G, writeProperty="community_id")
    print(
        f"      communityCount={int(louvain['communityCount']):,}  "
        f"modularity={float(louvain['modularity']):.4f}  "
        f"propertiesWritten={int(louvain['nodePropertiesWritten']):,}"
    )

    header("Step 4.5: Betweenness.write → betweenness_centrality")
    betweenness = gds.betweenness.write(
        G,
        writeProperty="betweenness_centrality",
        samplingSize=BETWEENNESS_SAMPLING_SIZE,
        samplingSeed=BETWEENNESS_SAMPLING_SEED,
    )
    dist = betweenness.get("centralityDistribution") or {}
    print(
        f"      propertiesWritten={int(betweenness['nodePropertiesWritten']):,}  "
        f"computeMillis={int(betweenness['computeMillis']):,}  "
        f"min={float(dist.get('min') or 0.0):.4f}  "
        f"mean={float(dist.get('mean') or 0.0):.4f}  "
        f"max={float(dist.get('max') or 0.0):.4f}"
    )

    gds.graph.drop(G)

    header("Step 5: project account_merchants (NATURAL, bipartite)")
    drop_if_exists(gds, "account_merchants")
    G2, stats2 = gds.graph.project(
        "account_merchants",
        ["Account", "Merchant"],
        {"TRANSACTED_WITH": {"orientation": "NATURAL"}},
    )
    print(
        f"      projected '{G2.name()}': {stats2['nodeCount']:,} nodes, "
        f"{stats2['relationshipCount']:,} relationships"
    )

    header("Step 5.5: delete stale :SIMILAR_TO relationships")
    cleared = gds.run_cypher(
        "MATCH ()-[s:SIMILAR_TO]->() DELETE s RETURN count(*) AS deleted"
    )
    print(f"      deleted={int(cleared['deleted'].iloc[0]):,} stale relationships")

    header("Step 6: NodeSimilarity.write → :SIMILAR_TO + similarity_score")
    ns = gds.nodeSimilarity.write(
        G2,
        similarityMetric="JACCARD",
        topK=10,
        degreeCutoff=NODESIM_DEGREE_CUTOFF,
        writeRelationshipType="SIMILAR_TO",
        writeProperty="similarity_score",
    )
    print(
        f"      nodesCompared={int(ns['nodesCompared']):,}  "
        f"relationshipsWritten={int(ns['relationshipsWritten']):,}"
    )
    gds.graph.drop(G2)

    header("Step 7: aggregate max similarity per account")
    agg = gds.run_cypher(
        """
        MATCH (a:Account)-[s:SIMILAR_TO]-()
        WITH a, MAX(s.similarity_score) AS max_sim
        SET a.similarity_score = max_sim
        RETURN count(a) AS accounts_updated
        """
    )
    print(f"      accounts_updated={int(agg['accounts_updated'].iloc[0]):,}")

    header("Step 8: set similarity_score=0 on accounts with no SIMILAR_TO edge")
    zeroed = gds.run_cypher(
        """
        MATCH (a:Account)
        WHERE NOT (a)-[:SIMILAR_TO]-()
        SET a.similarity_score = 0.0
        RETURN count(a) AS accounts_zeroed
        """
    )
    print(f"      accounts_zeroed={int(zeroed['accounts_zeroed'].iloc[0]):,}")

    header("Step 9: create Account lookup indexes for analyst queries")
    # The analyst client searches by Louvain community and ranks by PageRank.
    # These properties do not exist until the GDS writes above complete, so the
    # indexes live here rather than in the base Spark ingest.
    gds.run_cypher(
        """
        CREATE INDEX account_community_id IF NOT EXISTS
        FOR (a:Account) ON (a.community_id)
        """
    )
    gds.run_cypher(
        """
        CREATE INDEX account_risk_score IF NOT EXISTS
        FOR (a:Account) ON (a.risk_score)
        """
    )
    print("      indexes ready: account_community_id, account_risk_score")

    header("Step 10: project customer_identity (UNDIRECTED)")
    drop_if_exists(gds, "customer_identity")
    G3, stats3 = gds.graph.project(
        "customer_identity",
        ["Customer", "Phone", "Address"],
        {
            "HAS_PHONE": {"orientation": "UNDIRECTED"},
            "HAS_ADDRESS": {"orientation": "UNDIRECTED"},
        },
    )
    print(
        f"      projected '{G3.name()}': {stats3['nodeCount']:,} nodes, "
        f"{stats3['relationshipCount']:,} relationships"
    )

    header("Step 11: WCC.write → identity_cluster_id")
    wcc = gds.wcc.write(G3, writeProperty="identity_cluster_id")
    print(
        f"      componentCount={int(wcc['componentCount']):,}  "
        f"propertiesWritten={int(wcc['nodePropertiesWritten']):,}"
    )
    gds.graph.drop(G3)

    header("Step 12: identity_cluster_size per customer")
    # Cluster size counts customers only — WCC also labels the :Phone and
    # :Address nodes in each component, but those are identifiers, not members.
    sized = gds.run_cypher(
        """
        MATCH (c:Customer)
        WITH c.identity_cluster_id AS cid, collect(c) AS members
        UNWIND members AS c
        SET c.identity_cluster_size = size(members)
        WITH cid, size(members) AS cluster_size
        RETURN count(DISTINCT cid) AS clusters,
               sum(CASE WHEN cluster_size > 1 THEN 1 ELSE 0 END) AS shared_customers
        """
    ).iloc[0]
    print(
        f"      clusters={int(sized['clusters']):,}  "
        f"customers_in_shared_clusters={int(sized['shared_customers']):,}"
    )

    header("Step 13: shared_phone_count / shared_address_count per customer")
    for rel, prop in (
        ("HAS_PHONE", "shared_phone_count"),
        ("HAS_ADDRESS", "shared_address_count"),
    ):
        row = gds.run_cypher(
            f"""
            MATCH (c:Customer)
            OPTIONAL MATCH (c)-[:{rel}]->()<-[:{rel}]-(other:Customer)
            WITH c, count(DISTINCT other) AS n
            SET c.{prop} = n
            RETURN sum(CASE WHEN n > 0 THEN 1 ELSE 0 END) AS sharing
            """
        ).iloc[0]
        print(f"      {prop}: {int(row['sharing']):,} customers share")

    header("Step 14: propagate identity properties to :Account via OWNS")
    propagated = gds.run_cypher(
        """
        MATCH (c:Customer)-[:OWNS]->(a:Account)
        SET a.identity_cluster_id = c.identity_cluster_id,
            a.identity_cluster_size = c.identity_cluster_size,
            a.shared_phone_count = c.shared_phone_count,
            a.shared_address_count = c.shared_address_count
        RETURN count(a) AS accounts_updated
        """
    ).iloc[0]
    print(f"      accounts_updated={int(propagated['accounts_updated']):,}")

    header("Step 15: knowledge layer — Policy / BusinessTerm / BusinessRule / DataSource")
    # Thin semantic/provenance layer so "which policy, definition, and data
    # sources flagged this customer" is a traversal, not tribal knowledge. Built
    # here, next to the WCC classification, so detection and its explanation are
    # written together. All MERGE — safe to re-run.
    gds.run_cypher(
        """
        MERGE (p:Policy {policy_id: 'KYC-CIP-001'})
          SET p.name = 'Customer Identification Program (KYC)',
              p.authority = 'FinCEN 31 CFR 1020.220',
              p.description = 'Requires verifying customer identity and detecting customers operating under shared or synthetic identities.'
        MERGE (term:BusinessTerm {name: $term})
          SET term.description = 'A group of customers linked into one identity cluster by shared phone numbers or addresses, indicating possible synthetic-identity or structuring activity.'
        MERGE (rule:BusinessRule {rule_id: 'KYC-WCC-001'})
          SET rule.name = 'Shared-identity WCC cluster',
              rule.logic = 'Weakly Connected Components over (:Customer)-[:HAS_PHONE|HAS_ADDRESS]->() ; flag every customer whose identity_cluster_size > 1.',
              rule.threshold = 1
        MERGE (phone:DataSource {name: 'silver.customers.phone'})
          SET phone.description = 'Customer phone column; feeds the :Phone identity nodes via HAS_PHONE.'
        MERGE (addr:DataSource {name: 'silver.customers.address'})
          SET addr.description = 'Customer address column; feeds the :Address identity nodes via HAS_ADDRESS.'
        MERGE (term)-[:GOVERNED_BY]->(p)
        MERGE (term)-[:DEFINED_BY]->(rule)
        MERGE (rule)-[:DERIVED_FROM]->(phone)
        MERGE (rule)-[:DERIVED_FROM]->(addr)
        """,
        params={"term": KYC_BUSINESS_TERM},
    )
    print(
        "      knowledge layer ready: Policy, BusinessTerm, BusinessRule, "
        "2 DataSource + provenance edges"
    )

    header("Step 16: delete stale :CLASSIFIED_AS relationships")
    cleared = gds.run_cypher(
        """
        MATCH (:Customer)-[r:CLASSIFIED_AS]->(:BusinessTerm)
        DELETE r RETURN count(r) AS deleted
        """
    )
    print(f"      deleted={int(cleared['deleted'].iloc[0]):,} stale relationships")

    header("Step 17: classify shared-identity customers → :CLASSIFIED_AS provenance")
    # Every customer whose WCC cluster holds more than one customer is a member
    # of a shared-identity ring. The edge carries a human-readable reason and
    # the cluster it was derived from, so the classification explains itself.
    classified = gds.run_cypher(
        """
        MATCH (term:BusinessTerm {name: $term})
        MATCH (c:Customer) WHERE c.identity_cluster_size > 1
        MERGE (c)-[r:CLASSIFIED_AS]->(term)
        SET r.reason = 'shares ' + toString(c.shared_phone_count) +
                       ' phone(s) and ' + toString(c.shared_address_count) +
                       ' address with ' + toString(c.identity_cluster_size - 1) +
                       ' other customer(s) in identity cluster ' +
                       toString(c.identity_cluster_id),
            r.evaluatedAt = datetime(),
            r.cluster_id = c.identity_cluster_id,
            r.cluster_size = c.identity_cluster_size
        RETURN count(r) AS classified
        """,
        params={"term": KYC_BUSINESS_TERM},
    ).iloc[0]
    print(
        f"      customers classified as '{KYC_BUSINESS_TERM}': "
        f"{int(classified['classified']):,}"
    )


def main() -> None:
    load_env(REQUIRED_VARS)

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]

    gds = connect(uri, user, password)
    with gds:
        run_pipeline(gds)
        ok("GDS pipeline complete — run verify_gds.py to check outputs")


if __name__ == "__main__":
    main()

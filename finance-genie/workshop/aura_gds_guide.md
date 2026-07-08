# GDS Algorithms in Neo4j Aura

**This is a reference guide.** Run these commands in the **Neo4j Aura Workspace**
Query tab rather than Databricks. It is a standalone alternative to
`04_gds_enrichment.ipynb` for readers who prefer to follow along outside a
Databricks notebook.

After running `03_neo4j_ingest`, switch to Aura and execute the steps below.
When finished, return to Databricks and run `05_pull_gold_tables`.

## What We're Computing

| Algorithm | Property Written | Fraud Signal |
|-----------|-----------------|--------------|
| **PageRank** | `Account.risk_score` | Central accounts in money-flow networks |
| **Louvain** | `Account.community_id` | Tightly connected fraud-ring clusters |
| **Node Similarity** | `Account.similarity_score` | Accounts sharing the same merchants |

---

## How the Fraud Signal Gets In

Each algorithm reads a different part of the synthetic graph. The signal was
planted at data-generation time, and the algorithms recover it from structure
alone.

**PageRank and Louvain: signal source, within-ring transfers**

Each fraud ring has 100 accounts. At generation time, `WITHIN_RING_PROB` of all P2P transfers are forced to stay inside a ring: ring members send money to other ring members at a much higher rate than background accounts do. This creates a dense internal `TRANSFERRED_TO` subgraph for each ring.

- **Louvain** sees that density as a tight community and assigns all members the same `community_id`.
- **PageRank** sees ring members recursively passing centrality to each other. Because the senders are themselves well-connected ring members, the centrality compounds. Ring members score higher than background accounts even though their raw transfer counts are moderate.

Both algorithms project only Account nodes and `TRANSFERRED_TO` relationships.
Merchant data stays outside this analytic view.

**NodeSimilarity: signal source, anchor merchants**

Each fraud ring is assigned 4 anchor merchants at generation time. Ring members direct `RING_ANCHOR_PREF` of their transactions toward those specific 4 merchants. Normal accounts visit merchants uniformly at random.

The result: ring members share a distinctive set of merchants. NodeSimilarity projects the bipartite Account–Merchant graph (`TRANSACTED_WITH` relationships) and computes Jaccard similarity over shared merchant sets. Two accounts that visit the same 4 anchor merchants out of a pool of thousands score high; two accounts whose shared merchants are explained by random volume score low.

The data flow for NodeSimilarity is:
```
anchor merchants assigned at generation
    → ring members preferentially TRANSACTED_WITH those merchants
    → bipartite Account–Merchant projection
    → NodeSimilarity computes Jaccard over shared merchant sets
    → similarity_score written to Account nodes
```

All three GDS algorithms operate purely on graph structure.

---

## Step 1: Verify and Explore the Graph

Before projecting anything, make sure the ingest landed and get a feel for the
shape of the data.

### 1a. Node and relationship counts

```cypher
MATCH (a:Account) WITH count(a) AS accounts
MATCH (m:Merchant) WITH accounts, count(m) AS merchants
MATCH ()-[t:TRANSACTED_WITH]->() WITH accounts, merchants, count(t) AS txns
MATCH ()-[p:TRANSFERRED_TO]->() WITH accounts, merchants, txns, count(p) AS p2p
RETURN accounts, merchants, txns, p2p
```

**Expected:** ~25,000 accounts, ~7,500 merchants, ~250,000 transactions, ~300,000 transfers.

### 1b. Account breakdown by transfer activity

```cypher
MATCH (a:Account)
OPTIONAL MATCH (a)-[:TRANSFERRED_TO]-()
WITH a, count(*) AS degree
RETURN a.account_type AS account_type,
       count(a) AS account_count,
       round(avg(a.balance), 2) AS avg_balance,
       round(avg(degree), 1) AS avg_degree,
       max(degree) AS max_degree
ORDER BY account_count DESC
```

**What to look for:** transfer degree is fairly uniform across account types.
The separation lives in graph structure rather than tabular attributes. This is
the point of the exercise.

### 1c. Account breakdown by balance tier

```cypher
MATCH (a:Account)
WITH a,
     CASE WHEN a.balance < 10000 THEN 'low'
          WHEN a.balance < 100000 THEN 'mid'
          ELSE 'high' END AS balance_tier
RETURN balance_tier,
       count(a) AS accounts,
       round(avg(a.balance), 2) AS avg_balance,
       min(a.holder_age) AS min_age,
       max(a.holder_age) AS max_age
ORDER BY accounts DESC
```

**What to look for:** balance tiers and age ranges overlap heavily across all
groups. Column filters miss the fraud rings.

### 1d. Sample the subgraph around an account

```cypher
MATCH (a:Account)
WHERE (a)-[:TRANSFERRED_TO]-()
WITH a LIMIT 1
OPTIONAL MATCH (a)-[t:TRANSACTED_WITH]->(m:Merchant)
OPTIONAL MATCH (a)-[p:TRANSFERRED_TO]->(b:Account)
RETURN a, t, m, p, b
```

**What to look for:** the account connects to merchants across various
categories and has at least one `TRANSFERRED_TO` edge to another account.
Good visual primer before running the algorithms.

---

## Step 2: Project the Account Transfer Graph

GDS algorithms run on an **in-memory graph projection** instead of the stored database graph.
This projects only Account nodes and `TRANSFERRED_TO` relationships: the peer-to-peer
money-flow graph where fraud rings live.

A projection is a named, temporary analytics view of the stored graph. Neo4j
keeps the source `Account`, `Merchant`, `TRANSFERRED_TO`, and `TRANSACTED_WITH`
records in the database, while GDS loads only the labels, relationship types,
and properties needed by the algorithm into its graph catalog. That separation
matters: you can project a narrow graph for fast analytics while keeping the
stored operational graph unchanged until an algorithm writes results back.

For PageRank and Louvain, the projection deliberately excludes merchants and
merchant transactions. The target question is: "Which accounts are structurally
central or clustered in the peer-to-peer money flow network?" The `UNDIRECTED`
orientation lets community detection treat a
transfer between two accounts as evidence of connection regardless of direction,
which is useful for finding dense rings.

Run these as separate queries in the Aura Query tab. The first query clears any
stale projection from a previous run:

```cypher
CALL gds.graph.drop('account_transfers', false)
YIELD graphName
RETURN graphName
```

Then create the projection:

```cypher
CALL gds.graph.project(
  'account_transfers',
  'Account',
  {TRANSFERRED_TO: {orientation: 'UNDIRECTED'}}
)
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
```

**Expected:** ~25,000 nodes, ~300,000 relationships.

`nodeCount` tells you how many `Account` nodes were loaded into the analytic
view. `relationshipCount` tells you how many `TRANSFERRED_TO` edges GDS can use.
If either count is unexpectedly low, stop here and check the ingest before
running algorithms. The algorithms can only find patterns in the projected graph
they are given.

Before moving on, confirm the projection is in the GDS graph catalog:

```cypher
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount
WHERE graphName = 'account_transfers'
RETURN graphName, nodeCount, relationshipCount
```

If this returns zero rows, the current database's GDS graph catalog is missing
the projection. Re-run the projection query above before running PageRank or
Louvain. GDS projections are in-memory; they disappear if they are dropped, if
the database restarts, or if you switch to a different Neo4j database.

---

## Step 3: Run PageRank For Risk Centrality

PageRank measures how "central" an account is in the transfer network.
Accounts that receive money from many well-connected accounts score higher.
That is exactly how money-mule networks operate.

In plain terms, PageRank asks: "Which accounts are important because they are
connected to other important accounts?" That is more useful than counting
transfers. A mule inside a ring can have moderate raw transaction volume and a
high centrality score because it sits among accounts that are themselves central
to the ring. This gives the demo a structural risk feature that SQL aggregation
over account rows misses.

This command uses `write` mode. GDS computes PageRank against the in-memory
projection, then writes the result back to each stored `Account` node as
`risk_score`. Databricks later reads that property into Gold as a normal column,
so Genie can filter, group, and rank accounts by graph centrality.

If PageRank reports a missing `account_transfers` graph, return to Step 2 and
recreate the projection first.

```cypher
CALL gds.pageRank.write(
  'account_transfers',
  {
    maxIterations: 20,
    dampingFactor: 0.85,
    writeProperty: 'risk_score'
  }
)
YIELD nodePropertiesWritten, ranIterations, didConverge
RETURN nodePropertiesWritten, ranIterations, didConverge
```

**Verify: top 10 by PageRank:**

```cypher
MATCH (a:Account)
WHERE a.risk_score IS NOT NULL
RETURN a.account_id AS id,
       round(a.risk_score, 6) AS pagerank
ORDER BY a.risk_score DESC
LIMIT 10
```

These top accounts are the most central nodes in the transfer network. Cross-reference the IDs against `account_labels` in Databricks after running the full pipeline to verify the fraud signal.

---

## Step 4: Run Louvain Community Detection For Fraud Rings

Louvain finds clusters of densely connected accounts. In a legitimate network,
communities are large and diffuse. Fraud rings form **small, tight clusters**
with heavy internal transfers.

Louvain is a community detection algorithm. It tries to partition the graph so
that accounts have many connections inside their assigned community and fewer
connections outside it. The returned `modularity` summarizes how strongly the
graph separates into communities: higher values indicate clearer community
structure.

The value for the lakehouse is the `community_id` feature. It turns topology
into a dimension that downstream tools can use. Instead of asking Genie to infer
"coordinated behavior" from raw transfers every time, the pipeline gives Genie a
stable grouping column: all accounts assigned to the same Louvain community can
be counted, ranked, compared by balance, or joined to merchant activity.

If you see `GraphNotFoundException` for `account_transfers`, Step 2 failed to
create a projection in the current Neo4j database, or the projection was
dropped/lost after PageRank. Run the Step 2 `gds.graph.list()` check. If it
returns zero rows, recreate `account_transfers`, then run Louvain.

```cypher
CALL gds.louvain.write(
  'account_transfers',
  {
    writeProperty: 'community_id'
  }
)
YIELD communityCount, modularity, nodePropertiesWritten
RETURN communityCount, modularity, nodePropertiesWritten
```

**Verify: community size distribution:**

```cypher
MATCH (a:Account)
WHERE a.community_id IS NOT NULL
RETURN a.community_id AS community, count(*) AS size
ORDER BY size DESC
LIMIT 15
```

**Visualise a small, dense fraud-ring candidate community:**

```cypher
MATCH (a:Account)
WHERE a.community_id IS NOT NULL
WITH a.community_id AS community, count(*) AS size
ORDER BY size ASC LIMIT 1
WITH community
MATCH (m:Account {community_id: community})-[r:TRANSFERRED_TO]-(other:Account {community_id: community})
RETURN m, r, other
```

**How this query works:**

The query runs in two stages separated by the intermediate `WITH community`.

*Stage 1: find the smallest community:*
- `MATCH (a:Account) WHERE a.community_id IS NOT NULL` collects every account Louvain has labelled.
- `WITH a.community_id AS community, count(*) AS size` groups by community and counts members.
- `ORDER BY size ASC LIMIT 1` picks the single smallest community. Small is the tell: the background population forms one large community of thousands of accounts; fraud rings form tight clusters of ~100.
- The second `WITH community` discards `size` and carries only the community ID into stage 2. This makes the `LIMIT 1` stick and preserves the single-community constraint for the next `MATCH`.

*Stage 2: retrieve the internal transfer subgraph:*
- `MATCH (m:Account {community_id: community})-[r:TRANSFERRED_TO]-(other:Account {community_id: community})` finds every `TRANSFERRED_TO` relationship where **both** endpoints belong to that community. The undirected `-` (rather than `->`) returns edges in either direction, so the full internal transfer graph is captured.
- `RETURN m, r, other` hands nodes and relationships to the Aura visual renderer, which draws them as a graph.

The result is a graph panel showing only the accounts inside the ring and the transfers between them. A fraud ring looks like a dense hairball; a random slice of background accounts looks like a sparse tree.

---

## Step 5: Drop the Transfer Graph Projection

Clean up before creating the next projection. Dropping a projection leaves
`Account` nodes, `TRANSFERRED_TO` relationships, and the properties written by
PageRank and Louvain intact. It only releases the temporary in-memory analytics
view named `account_transfers`.

This matters in a workshop environment because each algorithm family needs a
different shape of graph. Keeping only the projection you need reduces memory
usage and makes later `gds.graph.list()` checks easier to interpret.

```cypher
CALL gds.graph.drop('account_transfers')
YIELD graphName
RETURN graphName
```

---

## Step 6: Project the Bipartite Graph From Account To Merchant

Node Similarity needs the bipartite graph: which accounts transact
with which merchants.

This projection has a different purpose than `account_transfers`. It includes
both `Account` and `Merchant` nodes, connected by `TRANSACTED_WITH`
relationships. The projected shape is bipartite: accounts connect only to
merchants. GDS can then infer account-to-account similarity from shared merchant
neighborhoods.

The `NATURAL` orientation keeps the stored direction from account to merchant.
That direction matches the semantic question: "Which merchants did each account
transact with?" For this algorithm, merchant overlap is the signal, so transfer
relationships are intentionally excluded.

```cypher
CALL gds.graph.project(
  'account_merchants',
  ['Account', 'Merchant'],
  {TRANSACTED_WITH: {orientation: 'NATURAL'}}
)
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
```

---

## Step 7: Run Node Similarity For Shared Merchant Patterns

Two accounts are similar if they transact with the **same merchants**.
Fraud accounts typically share a small set of high-risk merchants.

Node Similarity compares each account's merchant neighborhood with other
accounts' neighborhoods. With `JACCARD`, the score is the size of the shared
merchant set divided by the size of the combined merchant set. A score near 1.0
means two accounts mostly use the same merchants; a score near 0.0 means their
merchant patterns barely overlap.

This catches a different fraud signal than PageRank or Louvain. A ring may be
visible through peer-to-peer transfers, but it may also reveal itself because
members concentrate activity at the same anchor merchants. The `topK` and
`similarityCutoff` settings keep only the strongest account pairs, then `write`
mode persists those pairs as `SIMILAR_TO` relationships with a
`similarity_score` property.

```cypher
CALL gds.nodeSimilarity.write(
  'account_merchants',
  {
    similarityMetric: 'JACCARD',
    topK: 5,
    similarityCutoff: 0.3,
    writeRelationshipType: 'SIMILAR_TO',
    writeProperty: 'similarity_score'
  }
)
YIELD nodesCompared, relationshipsWritten
RETURN nodesCompared, relationshipsWritten
```

**Verify: most similar account pairs:**

```cypher
MATCH (a:Account)-[s:SIMILAR_TO]-(b:Account)
WHERE a.account_id < b.account_id
RETURN a.account_id AS account_a,
       b.account_id AS account_b,
       round(s.similarity_score, 3) AS similarity
ORDER BY s.similarity_score DESC
LIMIT 10
```

---

## Step 8: Aggregate Max Similarity per Account

For each account, store its **highest similarity score** as a node property.
This makes it easy to read back as a single feature column in Databricks.

Node Similarity writes pairwise relationships, which are useful for graph
inspection but awkward as a single account-level feature. This aggregation
compresses the relationship evidence into one scalar per account: the strongest
merchant-overlap signal found for that account. A downstream SQL query can then
sort or threshold `similarity_score` while avoiding expansion of the
`SIMILAR_TO` relationship graph.

```cypher
MATCH (a:Account)
OPTIONAL MATCH (a)-[s:SIMILAR_TO]-()
WITH a, COALESCE(MAX(s.similarity_score), 0.0) AS max_sim
SET a.similarity_score = max_sim
RETURN count(a) AS accounts_updated
```

---

## Step 9: Drop the Bipartite Graph Projection

As with the transfer projection, this removes only the temporary in-memory GDS
projection. The `SIMILAR_TO` relationships and account-level
`similarity_score` values written in Steps 7 and 8 remain in the stored graph.

```cypher
CALL gds.graph.drop('account_merchants')
YIELD graphName
RETURN graphName
```

---

## Step 10: Final Verification, All Features Written

Confirm all three properties exist on Account nodes:

This is the handoff check before returning to Databricks. At this point, the
graph algorithms have converted three structural patterns into three properties:
centrality (`risk_score`), community membership (`community_id`), and shared
merchant behavior (`similarity_score`). The next notebook reads these properties
back into Unity Catalog, where they become ordinary Gold columns.

```cypher
MATCH (a:Account)
WHERE a.risk_score IS NOT NULL
  AND a.community_id IS NOT NULL
  AND a.similarity_score IS NOT NULL
RETURN count(a) AS accounts_with_all_features
```

**Feature distribution by community size:**

```cypher
MATCH (a:Account)
WHERE a.risk_score IS NOT NULL
  AND a.community_id IS NOT NULL
  AND a.similarity_score IS NOT NULL
WITH a.community_id AS community,
     count(a) AS size,
     round(avg(a.risk_score), 6) AS avg_pagerank,
     round(avg(a.similarity_score), 4) AS avg_similarity
RETURN CASE WHEN size <= 150 THEN 'small (ring candidate)' ELSE 'large (background)' END AS community_type,
       count(community) AS num_communities,
       round(avg(avg_pagerank), 6) AS avg_pagerank,
       round(avg(avg_similarity), 4) AS avg_similarity
ORDER BY community_type
```

Small fraud-ring communities with about 100 accounts each should show higher
average PageRank and similarity scores than the large background community. That
separation is the signal.

This rollup is a sanity check rather than a fraud verdict. It confirms that
independent graph features move in the expected direction for the synthetic
signal. Small communities should look more suspicious because the data generator
planted dense within-ring transfers and shared merchant preferences there.

---

## Step 11: Fraud Detection Queries in Pure Cypher

Before handing the features back to Databricks, it is worth seeing the payoff
in Cypher alone. These two queries combine the GDS-written properties with
the raw graph to surface fraud patterns directly.

The point of these queries is to show what the features make possible. GDS does
the expensive structural work once. After the properties are written, normal
Cypher can combine them with business logic, time windows, merchant behavior, or
human-review thresholds. Databricks does the same thing later in SQL over Gold
tables.

### 11a. Identify Ring Members

A fraud ring is a Louvain community where multiple accounts both send *and*
receive money within the same community. Accounts that only send or only
receive are peripheral; accounts on both sides of a transfer are core ring
participants. The query collects senders and receivers per community, then
intersects them. Any account in both lists is a confirmed bidirectional
participant. Communities with three or more such accounts are coordinated rings.

```cypher
MATCH (s:Account)-[:TRANSFERRED_TO]->(r:Account)
WHERE s.community_id IS NOT NULL
  AND s.community_id = r.community_id
WITH s.community_id AS community,
     collect(DISTINCT s.account_id) AS senders,
     collect(DISTINCT r.account_id) AS receivers
WITH community,
     [x IN senders WHERE x IN receivers] AS ring_members
WHERE size(ring_members) >= 3
RETURN community,
       ring_members,
       size(ring_members) AS ring_size
ORDER BY ring_size DESC
```

**What to look for:** small, tight communities with `ring_size >= 3`.
The Louvain + bidirectional intersection combo finds rings from topology alone.
Validate precision by checking the returned account IDs against
`account_labels` in Databricks after completing the pipeline.

### 11b. Off-Hours Transaction Detection

Fraud accounts in this dataset skew slightly toward off-hours activity.
Flagging accounts with three or more transactions between midnight and 5am,
then joining the already-written `risk_score` and `community_id`, gives a
single ranked list that combines structural graph signal and behavioural
time-of-day signal.

```cypher
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
WHERE t.txn_hour >= 0 AND t.txn_hour < 6
WITH a,
     count(t)                        AS off_hours_count,
     round(avg(t.amount), 2)         AS avg_amount,
     round(sum(t.amount), 2)         AS total_amount,
     collect(DISTINCT m.merchant_id) AS merchants_used
WHERE off_hours_count >= 3
RETURN a.account_id         AS account_id,
       a.risk_score          AS risk_score,
       a.community_id        AS community_id,
       off_hours_count,
       avg_amount,
       total_amount,
       size(merchants_used)  AS distinct_merchants
ORDER BY off_hours_count DESC
LIMIT 25
```

**What to look for:** accounts with high `off_hours_count` that *also* have
a high `risk_score` and share a `community_id` with other flagged accounts.
Those are the strongest fraud candidates: three independent signals pointing
at the same account.

---

## Done in Aura

The graph now has three GDS-computed properties on every Account node:

- `risk_score`: centrality in the transfer network
- `community_id`: Louvain cluster assignment
- `similarity_score`: highest Jaccard similarity to any other account

**Next →** Return to Databricks and run `05_pull_gold_tables` to read these
features back into Unity Catalog as the three Gold tables the AFTER Genie
space queries. For the KYC identity-resolution extension, continue with the
appendix below, the Aura-tab equivalent of `06_kyc_walkthrough`.

---

## Appendix: KYC Identity Resolution in Aura

These steps back `06_kyc_walkthrough.ipynb`. They run over the KYC identity
layer that `03_neo4j_ingest` loaded (`:Customer` / `:Phone` / `:Address` joined
by `OWNS` / `HAS_PHONE` / `HAS_ADDRESS`) and the `community_id` that Louvain
wrote in Step 4. Run them in the Aura Query tab, then return to Databricks and
run Part C of `06_kyc_walkthrough` to land the results in `gold_accounts`.

The signal is a planted story ring: eight accounts owned by eight customers who
share two phones and one address. No single phone connects all eight; the shared
address is the bridge that collapses them into one Weakly Connected Component.
That is the traversal a warehouse cannot express in one hop.

### A1. Confirm the identity layer loaded

```cypher
RETURN count { (a:Account) }  AS accounts,
       count { (c:Customer) } AS customers,
       count { (p:Phone) }    AS phones,
       count { (ad:Address) } AS addresses
```

If `customers` is zero, re-run the KYC identity-layer section of
`03_neo4j_ingest` before continuing.

### A2. Project the identity graph (UNDIRECTED)

Project only the identity layer. `UNDIRECTED` so a shared identifier connects
its owners in both directions.

```cypher
CALL gds.graph.drop('customer_identity', false) YIELD graphName RETURN graphName
```

```cypher
CALL gds.graph.project(
  'customer_identity',
  ['Customer', 'Phone', 'Address'],
  {
    HAS_PHONE:   {orientation: 'UNDIRECTED'},
    HAS_ADDRESS: {orientation: 'UNDIRECTED'}
  }
)
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
```

### A3. WCC → `identity_cluster_id`

Every node in a connected component gets the same `identity_cluster_id`.
Customers linked by any chain of shared phones or addresses land in one
component.

```cypher
CALL gds.wcc.write('customer_identity', {writeProperty: 'identity_cluster_id'})
YIELD componentCount, nodePropertiesWritten
RETURN componentCount, nodePropertiesWritten
```

### A4. `identity_cluster_size` per customer

Size counts customers only. WCC also labels the `:Phone` and `:Address` nodes in
each component, but those are identifiers, not members. Expect
`customers_in_shared_clusters` = 8.

```cypher
MATCH (c:Customer)
WITH c.identity_cluster_id AS cid, collect(c) AS members
UNWIND members AS c
SET c.identity_cluster_size = size(members)
WITH cid, size(members) AS cluster_size
RETURN count(DISTINCT cid) AS clusters,
       sum(CASE WHEN cluster_size > 1 THEN 1 ELSE 0 END) AS customers_in_shared_clusters
```

### A5. `shared_phone_count` / `shared_address_count` per customer

For each customer, count the distinct *other* customers reached through a shared
phone, and through a shared address. Run both queries. Expect 8 customers
sharing a phone (four per phone group) and 4 sharing the address.

```cypher
MATCH (c:Customer)
OPTIONAL MATCH (c)-[:HAS_PHONE]->()<-[:HAS_PHONE]-(other:Customer)
WITH c, count(DISTINCT other) AS n
SET c.shared_phone_count = n
RETURN sum(CASE WHEN n > 0 THEN 1 ELSE 0 END) AS customers_sharing_a_phone
```

```cypher
MATCH (c:Customer)
OPTIONAL MATCH (c)-[:HAS_ADDRESS]->()<-[:HAS_ADDRESS]-(other:Customer)
WITH c, count(DISTINCT other) AS n
SET c.shared_address_count = n
RETURN sum(CASE WHEN n > 0 THEN 1 ELSE 0 END) AS customers_sharing_an_address
```

### A6. Propagate identity properties to `:Account` via `OWNS`

The Genie-facing columns live on `:Account`, so copy the four identity
properties from each customer to the account they own.

```cypher
MATCH (c:Customer)-[:OWNS]->(a:Account)
SET a.identity_cluster_id = c.identity_cluster_id,
    a.identity_cluster_size = c.identity_cluster_size,
    a.shared_phone_count = c.shared_phone_count,
    a.shared_address_count = c.shared_address_count
RETURN count(a) AS accounts_updated
```

### A7. Build the knowledge layer

A thin semantic and provenance layer so "which policy, definition, and data
sources flagged this customer" is a traversal, not tribal knowledge. All
`MERGE`, so it is safe to re-run.

```cypher
MERGE (p:Policy {policy_id: 'KYC-CIP-001'})
  SET p.name = 'Customer Identification Program (KYC)',
      p.authority = 'FinCEN 31 CFR 1020.220',
      p.description = 'Requires verifying customer identity and detecting customers operating under shared or synthetic identities.'
MERGE (term:BusinessTerm {name: 'Shared Identity Ring'})
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
```

### A8. Classify shared-identity customers → `:CLASSIFIED_AS`

Every customer whose WCC cluster holds more than one customer is a member of a
shared-identity ring. Run the first query to clear any stale edges from a prior
run, then the second to reclassify. Expect 8 customers classified.

```cypher
MATCH (:Customer)-[r:CLASSIFIED_AS]->(:BusinessTerm)
DELETE r RETURN count(r) AS deleted
```

```cypher
MATCH (term:BusinessTerm {name: 'Shared Identity Ring'})
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
```

### A9. Drop the identity projection

```cypher
CALL gds.graph.drop('customer_identity') YIELD graphName RETURN graphName
```

### A10. Verify the story ring

Sharing as pure structure. Expect two rows, one per planted phone, each with its
four customers.

```cypher
MATCH (c:Customer)-[:HAS_PHONE]->(p:Phone)
WITH p, collect(DISTINCT c.name) AS customers
WHERE size(customers) > 1
RETURN p.number AS phone, customers
```

The resolved identity cluster on the eight story accounts. Expect one `cluster`
id with `cluster_size` = 8 on all eight rows, `shared_phones` = 3 everywhere, and
`shared_addresses` = 3 on the four address-sharers.

```cypher
MATCH (a:Account)
WHERE a.account_id IN [368, 927, 1033, 1696, 2184, 2216, 2612, 3003]
RETURN a.account_id AS account,
       a.identity_cluster_id AS cluster,
       a.identity_cluster_size AS cluster_size,
       a.shared_phone_count AS shared_phones,
       a.shared_address_count AS shared_addresses
ORDER BY a.account_id
```

The provenance path: every violator plus the rule, definition, policy, and data
sources that classified it. Expect eight rows, no background customers.

```cypher
MATCH (c:Customer)-[cl:CLASSIFIED_AS]->(term:BusinessTerm)-[:DEFINED_BY]->(rule:BusinessRule)
MATCH (term)-[:GOVERNED_BY]->(policy:Policy)
MATCH (rule)-[:DERIVED_FROM]->(src:DataSource)
RETURN c.customer_id      AS customer,
       cl.reason          AS why,
       term.name          AS business_term,
       rule.rule_id       AS rule,
       policy.policy_id   AS policy,
       policy.authority   AS policy_authority,
       collect(DISTINCT src.name) AS data_sources
ORDER BY c.customer_id
```

**Next →** Return to Databricks and run Part C of `06_kyc_walkthrough` to land
the four KYC columns (`shared_phone_count`, `shared_address_count`,
`identity_cluster_id`, `identity_cluster_size`) on `gold_accounts`, then deliver
the presenter beats in Part D.

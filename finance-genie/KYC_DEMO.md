# Graph-Native KYC Demo Walkthrough

End-to-end guide for standing up and delivering the graph-native KYC demo for Finance Genie. Part 1 is an operator runbook: the exact commands to build the demo and confirm it is correct. Part 2 is a presenter script: the talk track, live Cypher, expected outputs, Bloom visuals, and Genie beats to deliver it.

The story: money movement detects the fraud ring, identity resolution explains it, and a knowledge layer names the policy and data sources that classified it. Neither the lakehouse nor any single graph layer catches all three alone.

## The planted story ring

Eight accounts sit inside fraud ring 0 and are owned by eight customers who share a small set of identifiers:

| Identifier | Value | Customers (by account_id) |
|-----------|-------|---------------------------|
| Phone A | 312-555-0142 | 368, 927, 1033, 1696 |
| Phone B | 312-555-0143 | 2184, 2216, 2612, 3003 |
| Address | 1247 W Cermak Rd, Chicago, IL 60608 | 1033, 1696, 2184, 2216 |

The address is the bridge. It spans two customers from Phone A (1033, 1696) and two from Phone B (2184, 2216), so all eight customers collapse into one Weakly Connected Component even though no single phone connects them all. This is the traversal a warehouse cannot express in one hop.

Ground truth lives in `data/ground_truth.json` under `kyc_story_ring`. Story data owns the `555-` phone prefix, so background data can never collide with it.

Expected per-account values after GDS:

- `identity_cluster_size` = 8 on all eight accounts
- `shared_phone_count` = 3 on all eight (each phone group has four members)
- `shared_address_count` = 3 on the four address-sharers (1033, 1696, 2184, 2216), 0 on the other four
- Every background account: `identity_cluster_size` = 1, both shared counts = 0

---

# Part 1: Operator runbook

## Prerequisites

- The silver `customers` table is already deployed in Unity Catalog with 25,000 rows. The early pipeline steps do not need to run again.
- `finance-genie/.env` is in place with the Databricks and Neo4j credentials the pipeline reads.
- The Neo4j Spark Connector JAR and `graphdatascience` PyPI package are installed as cluster libraries. `validation/validate_cluster.py` (pipeline step 2) confirms this.
- Do not run `./upload_and_create_tables.sh` standalone. Running it twice double-loads every silver table.

## Build the demo

Run from `finance-genie/enrichment-pipeline/`.

```bash
# Step 8: upload job scripts. This also ships sql/gold_schema.sql, which
# 03_pull_gold_tables.py reads at runtime on the cluster. Mandatory before step 13.
PIPELINE_START_STEP=8 PIPELINE_STOP_STEP=8 ./run_existing_data_pipeline.py

# Steps 10-14: Neo4j ingest with the identity layer, GDS identity resolution
# plus verification, gold write-back, and gold validation.
PIPELINE_START_STEP=10 PIPELINE_STOP_STEP=14 ./run_existing_data_pipeline.py

# Step 16: collect job logs (optional).
PIPELINE_START_STEP=16 ./run_existing_data_pipeline.py
```

What each step does:

- **Step 8** uploads the job scripts, including `sql/gold_schema.sql`. Skipping it leaves a stale `03_pull_gold_tables.py` on the cluster.
- **Step 10** (`jobs/02_neo4j_ingest.py`) wipes Neo4j and re-ingests everything, adding `Customer`, `Phone`, and `Address` nodes with `OWNS` / `HAS_PHONE` / `HAS_ADDRESS` relationships and uniqueness constraints. Shared phones and addresses MERGE onto single nodes.
- **Step 11** (`validation/run_gds.py`) runs the transfer-graph algorithms, then projects the identity graph, runs WCC, and writes `identity_cluster_id`, `identity_cluster_size`, `shared_phone_count`, and `shared_address_count` to customers and their accounts. It also builds the knowledge layer and classifies the violating customers. It fails fast if step 10 did not load the identity layer.
- **Step 12** (`validation/verify_gds.py`) gates the run against ground truth.
- **Step 13** (`jobs/03_pull_gold_tables.py`) reads the four KYC columns from Neo4j `:Account` nodes and writes `gold_accounts` at 25 columns.
- **Step 14** validates the gold tables. The KYC columns do not affect the existing checks.

## Run GDS and verify on their own

To iterate on the graph without re-running the whole pipeline, run the GDS scripts directly from `enrichment-pipeline/`:

```bash
uv run validation/run_gds.py      # transfer algorithms + identity resolution + knowledge layer
uv run validation/verify_gds.py   # all ground-truth checks
```

`setup/run_gds.py` is the idempotent entry point. It skips the recompute when all eight `:Account` properties are already populated, and takes `--force` to recompute.

## What a clean run looks like

The identity-resolution steps in `run_gds.py` print:

```
── Step 10: project customer_identity (UNDIRECTED) ...
      projected 'customer_identity': 75,003 nodes, 50,006 relationships
── Step 11: WCC.write → identity_cluster_id ...
      componentCount=24,993  propertiesWritten=75,003
── Step 12: identity_cluster_size per customer ...
      clusters=24,993  customers_in_shared_clusters=8
── Step 13: shared_phone_count / shared_address_count per customer ...
      shared_phone_count: 8 customers share
      shared_address_count: 4 customers share
── Step 14: propagate identity properties to :Account via OWNS ...
      accounts_updated=25,000
── Step 15: knowledge layer — Policy / BusinessTerm / BusinessRule / DataSource ...
      knowledge layer ready: Policy, BusinessTerm, BusinessRule, 2 DataSource + provenance edges
── Step 16: delete stale :CLASSIFIED_AS relationships ...
      deleted=0 stale relationships
── Step 17: classify shared-identity customers → :CLASSIFIED_AS provenance ...
      customers classified as 'Shared Identity Ring': 8
```

Node and relationship counts scale with the generated background, so treat them as shape, not exact figures. The numbers that must hold are `customers_in_shared_clusters=8`, the shared-count breakdown of 8 phone-sharers and 4 address-sharers, and `customers classified as 'Shared Identity Ring': 8`. On the first run `deleted=0`; on re-runs it equals the prior classification count, since step 16 clears stale edges before step 17 rewrites them.

`verify_gds.py` ends with a summary. The KYC checks are the last two:

```
  [8/9] KYC identity resolution           PASS  cluster of 8/8, background clean
  [9/9] KYC provenance (knowledge layer)  PASS  8/8 story classified, 0 background, path resolves
──────────────────────────────────────────────────────────────
Result: PASS  9/9 checks passed
```

A `FAIL` on `[8/9]` means the story cluster is the wrong size, background data leaked a shared identifier, or a shared count drifted from ground truth. A `FAIL` on `[9/9]` means classification or the provenance path is broken. Both print the exact discrepancy.

---

# Part 2: Presenter script

Deliver this after the fraud-ring detection portion of the Finance Genie demo, once the audience has seen Louvain find ring 0. The arc is three beats: identity as structure, identity explains the ring, and the knowledge layer explains the classification. Close on Genie.

Run the Cypher in Neo4j Browser or the Aura console. Keep Bloom open in a second tab for the visual beats.

## Beat 1: sharing is structure, not a computed count

**Say:** "In the warehouse, a phone number is text in a column. To find who shares one, you self-join the table against itself, and every extra hop is another join. In the graph, the phone number is its own node. Everyone who uses it points at it. Sharing is something you see, not something you compute."

**Show:** who shares an identifier with whom, as pure structure.

```cypher
MATCH (c:Customer)-[:HAS_PHONE]->(p:Phone)
WITH p, collect(DISTINCT c.name) AS customers
WHERE size(customers) > 1
RETURN p.number AS phone, customers
```

**Expected:** two rows, one per planted phone. `312-555-0142` returns the four customers behind accounts 368, 927, 1033, 1696. `312-555-0143` returns the four behind 2184, 2216, 2612, 3003. No background phone appears, because background customers each hold a unique number.

**Bloom:** search the phone values or expand from a story `Customer`. The ring renders as one connected blob around two `Phone` nodes and one `Address` node. Point out the address node in the middle: it is the single edge that ties the two phone clusters together.

## Beat 2: WCC resolves the identity, and it explains the ring

**Say:** "GDS ran Weakly Connected Components over the identity graph. It picks up one customer and sees everyone who lifts with them through any chain of shared identifiers. A normal customer is an island of one. These eight are one island, tied together by two phones and one shared address."

**Show:** the identity cluster and its shared counts.

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

**Expected:** all eight rows carry the same `cluster` id and `cluster_size` = 8. `shared_phones` = 3 on every row. `shared_addresses` = 3 on 1033, 1696, 2184, 2216 and 0 on the other four. The point to land: one cluster, eight members, no single phone connects all eight. The address is what makes it one ring.

**The flagship beat:** fraud ring meets identity cluster. Louvain already put these accounts in one transfer community. WCC now shows that eight of its accounts collapse into a single identity.

```cypher
MATCH (a:Account)
WHERE a.community_id = $ring_community
MATCH (c:Customer)-[:OWNS]->(a)
WITH c.identity_cluster_id AS cluster,
     count(DISTINCT c) AS customers,
     collect(DISTINCT a.account_id) AS accounts
WHERE customers > 1
RETURN cluster, customers, accounts
```

**Expected:** one row. Ring 0's transfer community holds many accounts, but only its eight story accounts share identifiers, so the `customers > 1` filter leaves exactly one identity cluster of eight and lists its eight account ids. Every other member of the community is its own identity cluster of one and drops out.

Set `$ring_community` to ring 0's Louvain community id. The gold pull emits `data/ring_community_map.json` on every rebuild, mapping each synthetic ring to its community id, so read the value for ring `"0"` from that file. The community ids change whenever the graph is re-projected, which is why the map is regenerated each run.

**Say:** "Money movement flagged the ring. Identity resolution proves the eight accounts are one person wearing eight masks. Neither layer alone gets there. The lakehouse equivalent is a recursive self-join across two different identifier types, which is exactly the multi-hop cost we opened with."

## Beat 3: the knowledge layer explains the classification

**Say:** "The customer's question is not only who violates the policy. It is which business definition and which data source made the call. That explanation is a traversal too."

**Show:** every violator plus the rule, definition, policy, and data-source lineage that classified it.

```cypher
MATCH (c:Customer)-[cl:CLASSIFIED_AS]->(term:BusinessTerm)-[:DEFINED_BY]->(rule:BusinessRule)
MATCH (term)-[:GOVERNED_BY]->(policy:Policy)
MATCH (rule)-[:DERIVED_FROM]->(src:DataSource)
RETURN c.customer_id      AS customer,
       cl.reason          AS why,
       term.name          AS business_term,
       rule.rule_id       AS rule,
       rule.logic         AS rule_logic,
       policy.policy_id   AS policy,
       policy.authority   AS policy_authority,
       collect(DISTINCT src.name) AS data_sources
ORDER BY c.customer_id
```

**Expected:** eight rows, one per violating customer. `why` is a plain-language reason such as `shares 3 phone(s) and 3 address with 7 other customer(s) in identity cluster 42`. `business_term` is `Shared Identity Ring`, `rule` is `KYC-WCC-001` with its WCC logic in `rule_logic`, `policy` is `KYC-CIP-001` under authority `FinCEN 31 CFR 1020.220`, and `data_sources` lists `silver.customers.phone` and `silver.customers.address`. No background customer appears, because only customers whose `identity_cluster_size` is above 1 are classified. Swap `c.customer_id` for `c.name` if you want the holder names in the room.

**Say:** "That single query is the auditable answer. The violator, the business term, the rule that fired, the policy it enforces, and the lineage back to the source columns. It is a paragraph in a warehouse and a path in the graph."

## Close: Genie answers from graph-derived columns

**Say:** "All of this writes back to Delta. Genie answers from the same lakehouse the analysts already use, and its answers are provably graph-derived."

**Show in the after-GDS Genie Space:**

- "Which accounts share a phone number with another customer?" resolves against `gold_accounts.shared_phone_count`.
- "Show me accounts in a shared-identity cluster" resolves against `gold_accounts.identity_cluster_size` greater than 1.

The four KYC columns (`shared_phone_count`, `shared_address_count`, `identity_cluster_id`, `identity_cluster_size`) sit in `gold_accounts` alongside `risk_score` and `community_id`. Their Unity Catalog comments tell Genie that values above the baseline indicate synthetic-identity risk. The values are computed in Neo4j and land in Delta through the Multi-Hop Native pattern: data starts in Databricks, multi-hop detection runs in the graph, results return to Delta.

---

## One-line recap for the room

Money movement detects the ring. Identity resolution proves it is one person. The knowledge layer names the policy and the source. Genie serves all three from Delta.

# Graph-Native KYC for Finance Genie

Finance Genie detects KYC violations inside Neo4j. Customer identity data flows from Unity Catalog into the graph, where shared phones and addresses become shared structure, GDS resolves identity clusters, and the results write back to the `gold_accounts` Delta table so Genie can answer from them.

The story: money movement detects the fraud ring, identity resolution explains it, and a knowledge layer names the policy and data sources that classified it. Neither the lakehouse nor any single graph layer catches all three alone.

Features it implements:

- **Identity layer in the graph**: `Customer`, `Phone`, and `Address` nodes; each customer keeps its own `Customer` node, and customers who share a phone or address link to the same `Phone` or `Address` node
- **GDS identity resolution**: Weakly Connected Components over the identity graph to find shared-identity clusters
- **Shared-identifier metrics**: each customer gets counts of how many other customers share a phone or address with them; the counts are copied onto the customer's accounts for the gold pull, and the graph holds the detail of who and which identifier
- **Gold write-back**: graph-derived KYC columns land in `gold_accounts` alongside the existing `risk_score` and `community_id`
- **Knowledge-layer provenance**: a `Policy` / `BusinessTerm` / `BusinessRule` / `DataSource` layer plus `CLASSIFIED_AS` edges make each violation explainable as a traversal, returning the rule, definition, policy, and data-source lineage that flagged the customer
- **Ground-truth verification**: automated checks that the planted KYC story ring is detected exactly, that only its customers are classified, and that background data stays clean

## Features

### Identity as structure

**ELI5**: In a relational database, a phone number is just text repeated in a column, like the same phone number written on 8 different index cards. To find out who shares a number, you have to compare every card against every other card. That is a self-join, and if you want chains, where customer A shares a phone with B and B shares an address with C, you need another join for every hop. In a graph, the phone number is a thing of its own, a single node, and every customer who uses it draws a line to it. Sharing stops being something you compute and becomes something you can see: 8 customers pointing at the same phone node look like a starburst. Finding chains is just following lines, no matter how long the chain gets.

- **Graph model**: `(:Customer)-[:OWNS]->(:Account)`, `(:Customer)-[:HAS_PHONE]->(:Phone)`, `(:Customer)-[:HAS_ADDRESS]->(:Address)`
- **Shared identifiers**: only `Phone` and `Address` nodes MERGE on value, so two customers with the same phone each point a `HAS_PHONE` relationship at the same `Phone` node
- **Customers stay separate**: `Customer` nodes are keyed on `customer_id` and never merge with each other, so no customer data is lost; the shared identifier node is what connects them
- **Customer properties**: name and email stay as properties because emails are unique per customer and would add nothing as nodes

### GDS identity resolution

**ELI5**: Think of customers, phones, and addresses as dots, and every "has this phone" or "has this address" link as a string between two dots. Weakly Connected Components, WCC for short, picks up one dot and sees everything that lifts with it. Each clump of dots that lifts together is one component, like finding the separate islands in an archipelago. In this graph, an island is a group of customers tied together by any chain of shared identifiers. Customer A and customer C land on the same island even if they never share anything directly, as long as some chain connects them, for example A shares a phone with B and B shares an address with C. A normal customer is an island of one. An island with several customers on it is a shared-identity candidate, which is exactly what KYC is looking for.

- **WCC clustering**: runs over the Customer, Phone, and Address graph with undirected identity relationships
- **`identity_cluster_id`**: the WCC component each customer belongs to
- **`identity_cluster_size`**: number of customers in the component; anything above 1 is a shared-identity candidate
- **`shared_phone_count` / `shared_address_count`**: count of other customers reachable through a shared identifier, computed in Cypher and propagated to accounts

### Two-layer detection story

- **Money movement detects**: Louvain on the transfer graph finds the fraud ring
- **Identity explains**: WCC on the identity graph shows the ring's 8 accounts are really one identity sharing 2 phones and 1 address
- **The point**: neither layer alone catches it, and the SQL equivalent is recursive self-joins across identifier types

### Knowledge-layer provenance

**ELI5**: Detection tells you a customer broke the rule. It does not tell you which rule, what the rule means, or where the data came from. The knowledge layer adds those as their own nodes: one `Policy` node, one `BusinessTerm` that names the pattern, one `BusinessRule` that states the logic, and `DataSource` nodes for the columns the rule reads. When GDS flags a customer, it draws a `CLASSIFIED_AS` line from that customer to the business term. Now the whole explanation, the violation, the definition, the policy it enforces, and the source columns, is one path you can walk instead of a story you have to tell.

- **Model**: `(:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule)-[:DERIVED_FROM]->(:DataSource)`, with `(:BusinessTerm)-[:GOVERNED_BY]->(:Policy)`
- **Classification**: the GDS run writes a `CLASSIFIED_AS` edge for every customer whose `identity_cluster_size` is above 1, carrying a plain-language `reason`, the `cluster_id`, and `cluster_size`
- **Self-explaining answer**: one traversal returns each violator plus the business term, the rule and its logic, the governing policy and its regulatory authority, and the data-source columns the rule was derived from
- **Graph-only**: this layer lives entirely in Neo4j and is not written back to Delta; it powers the live explain query, not a gold column

### Gold write-back and Genie

- **Multi-Hop Native pattern**: data starts in Databricks, multi-hop detection runs in Neo4j, results land back in Delta
- **`gold_accounts` columns**: `shared_phone_count`, `shared_address_count`, `identity_cluster_id`, `identity_cluster_size` join the existing GDS columns
- **Genie stays prominent**: "which accounts share a phone number" resolves against gold columns whose values are provably graph-derived

## The planted story ring

Eight accounts sit inside fraud ring 0 and are owned by eight customers who share a small set of identifiers:

| Identifier | Value | Customers (by account_id) |
|-----------|-------|---------------------------|
| Phone A | 312-555-0142 | 368, 927, 1033, 1696 |
| Phone B | 312-555-0143 | 2184, 2216, 2612, 3003 |
| Address | 1247 W Cermak Rd, Chicago, IL 60608 | 1033, 1696, 2184, 2216 |

The address is the bridge. It spans two customers from Phone A, accounts 1033 and 1696, and two from Phone B, accounts 2184 and 2216, so all eight customers collapse into one Weakly Connected Component even though no single phone connects them all. This is the traversal a warehouse cannot express in one hop.

Ground truth lives in `data/ground_truth.json` under `kyc_story_ring`. Story data owns the `555-` phone prefix, so background data can never collide with it.

Expected per-account values after GDS:

- `identity_cluster_size` = 8 on all eight accounts
- `shared_phone_count` = 3 on all eight, since each phone group has four members
- `shared_address_count` = 3 on the four address-sharers, accounts 1033, 1696, 2184, 2216, and 0 on the other four
- Every background account: `identity_cluster_size` = 1, both shared counts = 0

## How to Run the Demo

The silver `customers` table is already deployed with 25,000 rows, so the early pipeline steps do not need to run again. The Neo4j Spark Connector JAR and the `graphdatascience` PyPI package are installed as cluster libraries, and `finance-genie/.env` holds the Databricks and Neo4j credentials the pipeline reads. Do not run `./upload_and_create_tables.sh` standalone; running it twice double-loads every silver table.

From `enrichment-pipeline/`:

```bash
# Step 8: upload job scripts, including sql/gold_schema.sql that
# 03_pull_gold_tables.py reads at runtime. Mandatory before step 13.
PIPELINE_START_STEP=8 PIPELINE_STOP_STEP=8 ./run_existing_data_pipeline.py

# Steps 10-14: Neo4j ingest with the identity layer, GDS run + verify,
# gold write-back + validation
PIPELINE_START_STEP=10 PIPELINE_STOP_STEP=14 ./run_existing_data_pipeline.py

# Step 16: collect job logs (optional)
PIPELINE_START_STEP=16 ./run_existing_data_pipeline.py
```

- **Step 8**: uploads job scripts, including `sql/gold_schema.sql`; skipping it leaves a stale `03_pull_gold_tables.py` on the cluster
- **Step 10**: `jobs/02_neo4j_ingest.py` wipes Neo4j and re-ingests everything, adding `Customer`, `Phone`, and `Address` nodes with `OWNS` / `HAS_PHONE` / `HAS_ADDRESS` relationships and uniqueness constraints; shared phones and addresses MERGE onto single nodes
- **Step 11**: `validation/run_gds.py` runs the transfer algorithms, projects the identity graph, runs WCC, writes the four KYC properties, builds the knowledge layer, and classifies the shared-identity customers
- **Step 12**: `validation/verify_gds.py` gates the run against `ground_truth.json`, covering identity resolution `[8/9]` and knowledge-layer provenance `[9/9]`
- **Step 13**: `jobs/03_pull_gold_tables.py` reads the four KYC columns from Neo4j `:Account` nodes and writes `gold_accounts` at 25 columns
- **Step 14**: gold validation; the KYC columns do not affect the existing checks

To iterate on the graph without re-running the whole pipeline, run the GDS scripts directly from `enrichment-pipeline/`:

```bash
uv run validation/run_gds.py      # transfer algorithms + identity resolution + knowledge layer
uv run validation/verify_gds.py   # all ground-truth checks
```

`run_gds.py` is idempotent: it skips the recompute when all eight `:Account` properties are already populated, and takes `--force` to recompute. A clean `verify_gds.py` run ends with the two KYC checks passing:

```
  [8/9] KYC identity resolution           PASS  cluster of 8/8, background clean
  [9/9] KYC provenance (knowledge layer)  PASS  8/8 story classified, 0 background, path resolves
──────────────────────────────────────────────────────────────
Result: PASS  9/9 checks passed
```

A `FAIL` on `[8/9]` means the story cluster is the wrong size, background data leaked a shared identifier, or a shared count drifted from ground truth. A `FAIL` on `[9/9]` means classification or the provenance path is broken. Both print the exact discrepancy.

## Demo Walkthrough

Deliver this after the fraud-ring detection portion of the Finance Genie demo, once the audience has seen Louvain find ring 0. The arc is three steps: identity is structure, identity explains the ring, and the knowledge layer explains the classification. Close on Genie.

Run the Cypher in Neo4j Browser or the Aura console. Keep Bloom open in a second tab for the visuals.

### Step 1: sharing is structure, not a computed count

**Say:** "In the warehouse, a phone number is text in a column. To find who shares one, you self-join the table against itself, and every extra hop is another join. In the graph, the phone number is its own node. Everyone who uses it points at it. Sharing is something you see, not something you compute."

**Show:** who shares an identifier with whom, as pure structure.

```cypher
MATCH (c:Customer)-[:HAS_PHONE]->(p:Phone)
WITH p, collect(DISTINCT c.name) AS customers
WHERE size(customers) > 1
RETURN p.number AS phone, customers
```

**ELI5 of the query:** Start at every customer and walk the one line to their phone node. Group those customers by the phone they landed on, so each phone now carries the list of everyone pointing at it. Keep only the phones with more than one customer on the list. Those are the shared numbers, and the list is who shares them. No self-join and no comparing rows: the shared phone is already a single node with everyone attached to it.

**Expected:** two rows, one per planted phone. `312-555-0142` returns the four customers behind accounts 368, 927, 1033, 1696. `312-555-0143` returns the four behind 2184, 2216, 2612, 3003. No background phone appears, because background customers each hold a unique number.

**Bloom:** search the phone values or expand from a story `Customer`. The ring renders as one connected blob around two `Phone` nodes and one `Address` node. Point out the address node in the middle: it is the single edge that ties the two phone clusters together.

### Step 2: WCC resolves the identity, and it explains the ring

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

**ELI5 of the query:** Look up the eight story accounts by id and read back the four labels that GDS already wrote onto them. `cluster` is which island the account's owner landed on, `cluster_size` is how many customers are on that island, and the two shared counts say how many other customers reach this one through a shared phone or a shared address. Nothing is computed here; the query just reads the answers the graph algorithm stored.

**Expected:** all eight rows carry the same `cluster` id and `cluster_size` = 8. `shared_phones` = 3 on every row. `shared_addresses` = 3 on 1033, 1696, 2184, 2216 and 0 on the other four. The point to land: one cluster, eight members, no single phone connects all eight. The address is what makes it one ring.

**The flagship step:** fraud ring meets identity cluster. Louvain already put these accounts in one transfer community. WCC now shows that eight of its accounts collapse into a single identity.

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

**ELI5 of the query:** Take every account the money-movement algorithm put in ring 0's community, then walk back to the customer who owns each one. Group those customers by their identity island and count how many customers sit on each island. Throw away the islands with only one customer, the normal people. What is left is the island where several members of the same fraud community are secretly one identity, along with the account ids that give them away.

**Expected:** one row. Ring 0's transfer community holds many accounts, but only its eight story accounts share identifiers, so the `customers > 1` filter leaves exactly one identity cluster of eight and lists its eight account ids. Every other member of the community is its own identity cluster of one and drops out.

Set `$ring_community` to ring 0's Louvain community id. The gold pull emits `data/ring_community_map.json` on every rebuild, mapping each synthetic ring to its community id, so read the value for ring `"0"` from that file. The community ids change whenever the graph is re-projected, which is why the map is regenerated each run.

**Say:** "Money movement flagged the ring. Identity resolution proves the eight accounts are one person wearing eight masks. Neither layer alone gets there. The lakehouse equivalent is a recursive self-join across two different identifier types, which is exactly the multi-hop cost we opened with."

### Step 3: the knowledge layer explains the classification

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

**ELI5 of the query:** Start at each flagged customer and follow the trail the classification left behind. First hop to the business term they were tagged with, then to the rule that defines that term, then out to the policy the term answers to and back to the source columns the rule reads. One walk returns the whole chain of custody: who was flagged, the plain-language reason, the term, the rule and its logic, the policy and its regulator, and the exact columns the decision rests on.

**Expected:** eight rows, one per violating customer. `why` is a plain-language reason such as `shares 3 phone(s) and 3 address with 7 other customer(s) in identity cluster 42`. `business_term` is `Shared Identity Ring`, `rule` is `KYC-WCC-001` with its WCC logic in `rule_logic`, `policy` is `KYC-CIP-001` under authority `FinCEN 31 CFR 1020.220`, and `data_sources` lists `silver.customers.phone` and `silver.customers.address`. No background customer appears, because only customers whose `identity_cluster_size` is above 1 are classified. Swap `c.customer_id` for `c.name` if you want the holder names in the room.

**Say:** "That single query is the auditable answer. The violator, the business term, the rule that fired, the policy it enforces, and the lineage back to the source columns. It is a paragraph in a warehouse and a path in the graph."

## How to Demo Genie

Everything the graph computed writes back to Delta, so Genie answers from the same lakehouse the analysts already use, and its answers are provably graph-derived. The four KYC columns, `shared_phone_count`, `shared_address_count`, `identity_cluster_id`, and `identity_cluster_size`, sit in `gold_accounts` next to `risk_score` and `community_id`. Their Unity Catalog comments tell Genie that values above the baseline indicate synthetic-identity risk.

**Say:** "The traversals you just saw ran in Neo4j. The answers landed back in Delta as four columns. Now a business user asks in plain English, and Genie reads the same graph-derived values."

**Do this in the after-GDS Genie Space:**

1. Ask **"Which accounts share a phone number with another customer?"** Genie resolves this against `gold_accounts.shared_phone_count` and returns the accounts whose count is above 0. The story accounts surface without anyone writing SQL.
2. Ask **"Show me accounts in a shared-identity cluster."** Genie resolves this against `gold_accounts.identity_cluster_size` greater than 1, returning the same eight accounts the WCC step found in the graph.
3. Ask a follow-up such as **"How many other customers share an address with account 1033?"** to show Genie reading `shared_address_count` for a single account.

**Say:** "Same numbers, two front doors. The analyst gets a natural-language answer from Delta, and every value traces back to a multi-hop traversal that a warehouse query could not express. That is the Multi-Hop Native pattern: data starts in Databricks, multi-hop detection runs in the graph, results return to Delta for Genie to serve."

**Tip:** run the graph walkthrough first, then Genie. Showing the traversal before the natural-language question makes it clear the gold columns are not a warehouse aggregation; they are the graph's answer, served through Genie.

## Recap for the room

Money movement detects the ring. Identity resolution proves it is one person. The knowledge layer names the policy and the source. Genie serves all three from Delta.

# Graph-Native KYC for Finance Genie

Finance Genie detects KYC violations inside Neo4j. Customer identity data flows from Unity Catalog into the graph, where shared phones and addresses become shared structure, GDS resolves identity clusters, and the results write back to the `gold_accounts` Delta table so Genie can answer from them.

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

## Demos

### Story data

- **KYC story ring**: 8 accounts inside fraud ring 0 share two phone numbers, 312-555-0142 and 312-555-0143, plus one address spanning both phone groups
- **Background data**: 25,000 generated customers that can never collide with the story; story data owns the 555- phone prefix
- **Ground truth**: the ring is recorded under `kyc_story_ring` in `ground_truth.json` and verified after every run

### Demo queries

Shared identifiers as pure structure:

```cypher
MATCH (c1:Customer)-[:HAS_PHONE]->(p:Phone)<-[:HAS_PHONE]-(c2:Customer)
WHERE c1.customer_id < c2.customer_id
RETURN p.number, collect(DISTINCT c1.name) + collect(DISTINCT c2.name) AS customers
```

The flagship beat, fraud ring meets identity cluster:

```cypher
MATCH (a:Account)
WHERE a.community_id = $ring_community
MATCH (c:Customer)-[:OWNS]->(a)
RETURN c.identity_cluster_id, count(DISTINCT c) AS customers,
       collect(DISTINCT a.account_id) AS accounts
```

The explain beat, each violator with the rule, definition, policy, and data-source lineage that classified it:

```cypher
MATCH (c:Customer)-[cl:CLASSIFIED_AS]->(term:BusinessTerm)-[:DEFINED_BY]->(rule:BusinessRule)
MATCH (term)-[:GOVERNED_BY]->(policy:Policy)
MATCH (rule)-[:DERIVED_FROM]->(src:DataSource)
RETURN c.customer_id AS customer, cl.reason AS why, term.name AS business_term,
       rule.rule_id AS rule, policy.policy_id AS policy,
       collect(DISTINCT src.name) AS data_sources
ORDER BY c.customer_id
```

- **Bloom**: the story ring appears as one connected blob around 2 `Phone` nodes and 1 `Address` node
- **Genie**: natural-language questions about shared identifiers resolve against the graph-derived gold columns

## How to Run the Demo

The silver `customers` table is already deployed, so the early pipeline steps do not need to run again. Do not run `./upload_and_create_tables.sh` standalone; running it twice double-loads every silver table.

From `enrichment-pipeline/`:

```bash
# Step 8: upload job scripts (mandatory before step 13)
PIPELINE_START_STEP=8 PIPELINE_STOP_STEP=8 ./run_existing_data_pipeline.py

# Steps 10-14: Neo4j ingest with the identity layer, GDS run + verify,
# gold tables + validation
PIPELINE_START_STEP=10 PIPELINE_STOP_STEP=14 ./run_existing_data_pipeline.py

# Step 16: collect job logs (optional)
PIPELINE_START_STEP=16 ./run_existing_data_pipeline.py
```

- **Step 8**: uploads job scripts, including `sql/gold_schema.sql` that `03_pull_gold_tables.py` reads at runtime; skipping it leaves a stale copy on the cluster
- **Step 10**: `jobs/02_neo4j_ingest.py` ingests customers, phones, and addresses with uniqueness constraints, including the knowledge-layer node constraints
- **Step 11**: `validation/run_gds.py` runs WCC and writes the identity properties, then builds the knowledge layer and classifies every shared-identity customer with a `CLASSIFIED_AS` edge
- **Step 12**: `validation/verify_gds.py` checks the story ring against `ground_truth.json`, covering both identity resolution `[8/9]` and knowledge-layer provenance `[9/9]`
- **Step 13**: `jobs/03_pull_gold_tables.py` reads the KYC columns from Neo4j and writes `gold_accounts`
- **Step 14**: gold validation; the new columns do not affect the existing checks

# Graph-Native KYC Guide

Finance Genie uses Neo4j to find customers connected through shared phones and
addresses. GDS writes identity cluster results to `gold_accounts`. Genie can
then answer identity questions from the Gold table.

## Overview

- **Identity graph:** `Customer`, `Phone`, and `Address` nodes represent shared identifiers.
- **Identity resolution:** Weakly Connected Components finds groups connected by shared phones or addresses.
- **Account features:** Each account stores its identity cluster and shared-identifier counts.
- **Gold write-back:** Databricks stores the graph results in `gold_accounts`.
- **Provenance:** Policy, business term, rule, and data source nodes explain each classification.
- **Verification:** Automated checks compare the result with the planted KYC fixture.

Money movement and identity resolution answer different questions. Louvain finds
a connected transfer community. Identity resolution shows when accounts in that
community belong to customers who share identifiers.

## Graph Model

```text
(:Customer)-[:OWNS]->(:Account)
(:Customer)-[:HAS_PHONE]->(:Phone)
(:Customer)-[:HAS_ADDRESS]->(:Address)
```

- **Customer identity:** Each customer keeps a separate `Customer` node.
- **Shared phone:** Customers with the same number connect to one `Phone` node.
- **Shared address:** Customers with the same address connect to one `Address` node.
- **Email:** Email stays on the customer because the synthetic data gives each customer a unique value.

Weakly Connected Components groups every customer that can reach another
customer through a chain of shared identifiers.

- **`identity_cluster_id`:** Identifies the connected component.
- **`identity_cluster_size`:** Counts customers in that component.
- **`shared_phone_count`:** Counts other customers reached through the same phone.
- **`shared_address_count`:** Counts other customers reached through the same address.

## Planted Demo Fixture

Eight accounts in fraud ring 0 share two phones and one address.

| Identifier | Value | Account IDs |
| --- | --- | --- |
| Phone A | `312-555-0142` | 368, 927, 1033, 1696 |
| Phone B | `312-555-0143` | 2184, 2216, 2612, 3003 |
| Address | `1247 W Cermak Rd, Chicago, IL 60608` | 1033, 1696, 2184, 2216 |

The address connects the two phone groups. WCC therefore places all eight
customers in one identity cluster.

Expected values are:

- **Cluster size:** Eight on all story accounts.
- **Shared phones:** Three on all story accounts.
- **Shared addresses:** Three on accounts 1033, 1696, 2184, and 2216.
- **Background:** Cluster size one and shared counts zero.

Ground truth lives in `data/ground_truth.json` under `kyc_story_ring`.

## Demo Walkthrough

Run these queries in Neo4j Browser or the Aura console. Use Bloom to show the
same paths visually.

### Step 1: Show Shared Phones

This query groups customers by the phone node they share.

```cypher
MATCH (c:Customer)-[:HAS_PHONE]->(p:Phone)
WITH p, collect(DISTINCT c.name) AS customers
WHERE size(customers) > 1
RETURN p.number AS phone, customers
```

- **Expected rows:** Two.
- **Expected members:** Four customers for each planted phone.
- **Purpose:** Show that the shared identifier already exists as graph structure.

### Step 2: Show the Identity Cluster

This query reads the stored WCC features for the eight story accounts.

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

- **Expected cluster:** One shared cluster ID.
- **Expected cluster size:** Eight.
- **Expected phone count:** Three on every account.
- **Expected address count:** Three on the four address-sharing accounts.

To connect identity with money movement, query the transfer community and group
its customers by identity cluster.

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

Use the ring 0 community ID from `data/ring_community_map.json`. The query should
return one eight-customer identity cluster.

### Step 3: Show Classification Provenance

The knowledge layer links each classification to its business definition,
policy, rule, and source columns.

```cypher
MATCH (c:Customer)-[cl:CLASSIFIED_AS]->(term:BusinessTerm)-[:DEFINED_BY]->(rule:BusinessRule)
MATCH (term)-[:GOVERNED_BY]->(policy:Policy)
MATCH (rule)-[:DERIVED_FROM]->(src:DataSource)
RETURN c.customer_id AS customer,
       cl.reason AS why,
       term.name AS business_term,
       rule.rule_id AS rule,
       rule.logic AS rule_logic,
       policy.policy_id AS policy,
       policy.authority AS policy_authority,
       collect(DISTINCT src.name) AS data_sources
ORDER BY c.customer_id
```

- **Expected rows:** Eight story customers.
- **Expected business term:** `Shared Identity Ring`.
- **Expected rule:** `KYC-WCC-001`.
- **Expected policy:** `KYC-CIP-001`.
- **Expected sources:** The Silver phone and address columns.

## Genie Questions

Run these questions in the Gold Genie Space after the pipeline writes the four
identity columns.

1. `Which accounts share a phone number with another customer?`
2. `Show me accounts in a shared-identity cluster.`
3. `How many other customers share an address with account 1033?`

Genie reads the graph-derived values from `gold_accounts`. Neo4j keeps the paths
that support those values.

## Run the Demo Pipeline

Run these commands from `finance-genie/enrichment-pipeline/`.

```bash
# Upload current job scripts and Gold DDL.
PIPELINE_START_STEP=8 PIPELINE_STOP_STEP=8 ./run_existing_data_pipeline.py

# Rebuild Neo4j, run GDS, write Gold tables, and validate the result.
PIPELINE_START_STEP=10 PIPELINE_STOP_STEP=14 ./run_existing_data_pipeline.py

# Collect job logs when needed.
PIPELINE_START_STEP=16 ./run_existing_data_pipeline.py
```

- **Step 8:** Uploads job files and `sql/gold_schema.sql`.
- **Step 10:** Rebuilds the Neo4j graph with account and identity data.
- **Step 11:** Runs and verifies the graph algorithms.
- **Step 13:** Writes graph features to the Gold tables.
- **Step 14:** Validates the Gold results.

Run `upload_and_create_tables.sh` once for each clean demo target. A second run
can load duplicate Silver rows.

## Run Identity Resolution Only

Use this path when Neo4j already contains the current data.

```bash
uv run python validation/run_gds.py
uv run python validation/verify_gds.py
```

Then run the Gold pull and validation steps to refresh Databricks.

## Success Criteria

- **Graph model:** Customer, phone, address, and ownership relationships exist.
- **Identity result:** All eight story customers share one identity cluster.
- **Background result:** Every background customer remains in a single-customer cluster.
- **Gold result:** All four identity columns match the graph values.
- **Provenance result:** Each story customer resolves to the expected term, rule, policy, and source fields.
- **Genie result:** The Gold Space returns the eight story accounts for shared-identity questions.

Treat every identity cluster as an investigation signal. A reviewer must confirm
the customer relationship and apply the institution's KYC policy.

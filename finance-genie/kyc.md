# TLDR: Graph-Native KYC for Finance Genie

## Status: pivoted to graph-native detection (2026-07-07)

The original plan computed shared-identity counts with Spark window functions during the gold pull and deliberately kept identity data out of Neo4j. That undercuts the purpose of this demo: showing a customer that the graph and GDS find KYC violations that the lakehouse alone cannot explain. The customer's own validation question is not "return the rows", it is "find customers violating KYC policy and explain which business definitions and data sources were used". That is a traversal story, so detection moves into Neo4j and GDS, and the gold tables become the write-back destination that keeps Genie in the demo.

| Increment | Status | Notes |
|-----------|--------|-------|
| 1. Identity attributes in background data | Done, unchanged | `customers.csv` with 25,000 rows; all five pre-existing CSVs byte-identical |
| 2. One named KYC story ring | Done, unchanged | 8 accounts inside fraud ring 0 share phones 312-555-0142 / 312-555-0143 with 4 accounts each, plus one address spanning both phone groups; recorded under `kyc_story_ring` in `ground_truth.json` |
| 3. Gold columns computed in Spark | Superseded | The window-function logic in `03_pull_gold_tables.py` was never deployed and will be removed; the two gold columns survive but will be graph-derived |
| 4. Identity layer in Neo4j | To do | `Customer`, `Phone`, `Address` nodes ingested in `02_neo4j_ingest.py` |
| 5. GDS identity resolution + verification | To do | WCC over the identity graph in `validation/run_gds.py`, new checks in `validation/verify_gds.py` |
| 6. Gold write-back from the graph | To do | `03_pull_gold_tables.py` reads the KYC columns from Neo4j exactly like `risk_score` and `community_id` |
| 7. Knowledge-layer provenance | Optional, deferred | `Policy` / `BusinessTerm` / `CLASSIFIED_AS` edges; converges with the supplier-risk-graph two-layer pattern |

Deployed state as of the pivot: the silver `customers` table is live in Unity Catalog with 25,000 rows, loaded 2026-07-07. The deployed `gold_accounts` still predates all KYC work, last written June 18. Nothing has to be unwound; the Spark KYC logic never shipped.

## Why graph-native

- The Spark approach answers "which accounts share a phone" with `COUNT(*) OVER (PARTITION BY phone)`. Any warehouse can do that, which is exactly the objection the demo must preempt.
- In the graph, sharing is structure, not a computed count. The story ring becomes one connected blob around 2 `Phone` nodes and 1 `Address` node, visible in Bloom and traversable in Cypher.
- GDS closes the loop: Louvain on the transfer graph finds the fraud ring, WCC on the identity graph explains it. "These 8 accounts are really one identity sharing 2 phones and 1 address." Money movement detects, identity explains, and neither layer alone catches it.
- The SQL equivalent of identity resolution is recursive self-joins across identifier types. That is the multi-hop cost argument in its most concrete form.
- Writing the results back to `gold_accounts` demonstrates the Multi-Hop Native integration pattern: data starts in Databricks, multi-hop detection runs in Neo4j, results land back in Delta where Genie answers from them. Genie stays prominent, and its answers are provably graph-derived.

## Target graph model

Identity as structure. Shared identifiers converge to a single node via MERGE on value:

```
(:Customer {customer_id, name, email})-[:OWNS]->(:Account)
(:Customer)-[:HAS_PHONE]->(:Phone {number})
(:Customer)-[:HAS_ADDRESS]->(:Address {address})
```

Name and email stay as `Customer` properties: emails are unique per customer by construction, so `Email` nodes would all be degree-1 and add nothing structurally. Promote email to a node later only if watchlist screening lands.

New GDS outputs, written to `:Customer` and propagated to `:Account` through `OWNS`:

- `identity_cluster_id`: WCC component over the Customer / Phone / Address graph
- `identity_cluster_size`: number of customers in the component; anything above 1 is a shared-identity candidate
- `shared_phone_count`, `shared_address_count`: count of other customers reachable through a shared `Phone` or `Address` node, computed in Cypher

## Implementation plan by pipeline step

Step numbers refer to `run_existing_data_pipeline.py`.

### Step 10, `jobs/02_neo4j_ingest.py`

- Read the silver `customers` table and write `Customer` nodes keyed on `customer_id`.
- Write `OWNS` relationships keyed on `account_id`, and `HAS_PHONE` / `HAS_ADDRESS` relationships whose target `node.keys` is the identifier value, so shared phones and addresses MERGE into single nodes.
- Add uniqueness constraints for `Customer.customer_id`, `Phone.number`, `Address.address` before the relationship writes, matching the existing pattern for `Account` and `Merchant`.
- Extend the final count verification with customers, phones, and addresses.

### Step 11, `validation/run_gds.py`

- After the existing transfer-graph pipeline, project Customer / Phone / Address with undirected `HAS_PHONE` and `HAS_ADDRESS`, run WCC, and write `identity_cluster_id` and `identity_cluster_size`.
- Compute `shared_phone_count` and `shared_address_count` per customer in Cypher and write them onto the owned `:Account` nodes so the gold pull reads them like every other GDS property.
- Add the new properties to `REQUIRED_PROPERTIES` in `setup/run_gds.py` so the idempotence check covers them.

### Step 12, `validation/verify_gds.py`

- The story ring's WCC component contains exactly the 8 accounts recorded in `ground_truth.json` under `kyc_story_ring`.
- Zero background customers land in any multi-customer identity cluster.
- Shared counts on the 8 story accounts match the ground truth; all other accounts have 0.

### Step 13, `jobs/03_pull_gold_tables.py`

- Delete the Spark window logic over the silver `customers` table, the `w_phone` / `w_address` blocks.
- Read `shared_phone_count`, `shared_address_count`, `identity_cluster_id`, `identity_cluster_size` from Neo4j `:Account` nodes in the same DataFrame that already carries `risk_score` and `community_id`.

### `sql/gold_schema.sql`

- Keep `shared_phone_count` and `shared_address_count`; reword their comments to say the values come from graph identity resolution.
- Add `identity_cluster_id` and `identity_cluster_size` with comments Genie can use, bringing `gold_accounts` to 25 columns.

### Unchanged

- `setup/generate_data.py`, `setup/checks_structural.py`, `diagnostics/verify_fraud_patterns.py`: the local data-layer checks still validate the generated CSVs before upload.
- `sql/schema.sql`, `upload_and_create_tables.sh`: the silver `customers` table remains the system of record that the ingest reads.
- `run_existing_data_pipeline.py`: still requires `customers.csv`.

## Demo story queries

Who shares an identifier with whom, as pure structure:

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

On the Genie side, "which accounts share a phone number" resolves against `gold_accounts.shared_phone_count`, which now carries graph-derived values.

## Increment 7, deferred: knowledge-layer provenance

The customer's flagship question asks for the violators and the explanation. A thin semantic layer makes the explanation a traversal:

```
(:Policy {name:'KYC Policy'})
(:BusinessTerm {name:'Shared Identity Ring'})-[:DEFINED_BY]->(:BusinessRule)
(:Customer)-[:CLASSIFIED_AS {reason, evaluatedAt}]->(:BusinessTerm)
```

The GDS run writes `CLASSIFIED_AS` edges when it flags a cluster, so the answer query returns each violator plus the rule, definition, and data-source lineage that classified it. This is the same two-layer pattern the supplier-risk-graph project builds; finance-genie becomes the "same pattern, KYC domain, with GDS" companion rather than a separate story. Build it only if the sessions need the explain query live. Watchlist screening and beneficial ownership stay deferred.

## Deployment steps

Silver is already deployed, so steps 2 through 6 do not need to run again. Do not run `./upload_and_create_tables.sh` standalone either, since step 5 is that script and running it twice double-loads every silver table. After implementing increments 4 through 6, run from `enrichment-pipeline/`:

```bash
# Step 8: upload job scripts; cli upload --all also ships sql/gold_schema.sql,
# which 03_pull_gold_tables.py reads at runtime on the cluster
PIPELINE_START_STEP=8 PIPELINE_STOP_STEP=8 ./run_existing_data_pipeline.py

# Steps 10-14: Neo4j ingest with the identity layer, GDS run + verify,
# gold tables + validation
PIPELINE_START_STEP=10 PIPELINE_STOP_STEP=14 ./run_existing_data_pipeline.py

# Step 16: collect job logs (optional)
PIPELINE_START_STEP=16 ./run_existing_data_pipeline.py
```

Notes:

- Step 8 is mandatory before step 13; without it the cluster runs the stale copy of `03_pull_gold_tables.py`.
- The gold validator in step 14 selects specific existing columns, so the new columns do not affect it.
- `require_existing_data()` runs on every invocation and requires `customers.csv`, which is already generated.

## What we take from the demostack

Only one idea, from the `demo-data` skill: the two-layer data model.

- **Layer 1, story data:** a small number of hand-designed, named records. Every account, phone, and address in the KYC ring is written explicitly in code, so scripted queries return exact, known results.
- **Layer 2, background data:** generated volume that makes the story credible, with exclusion rules so it can never contaminate story query results. Story data owns the 555- phone prefix and background data never uses it.
- **Verification:** after generation, run checks that the story ring is intact and that zero background records collide with it.

Both layers and their local verification are done and unchanged by this pivot. What changes is where detection happens: in the graph, not in Spark.

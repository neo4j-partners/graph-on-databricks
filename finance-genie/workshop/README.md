# Workshop Guide

The hands-on notebook path for the Finance Genie graph enrichment demo. Each
notebook maps to a live demo stage. The **Anchor**, one fraud question with two
answers, runs in Genie. The **Pipeline** runs as three Databricks notebooks that
load, enrich, and land data in Gold. The enrichment pipeline runs Neo4j GDS as a
silver-to-gold stage that writes community membership, risk centrality, and
structural similarity back as scalar columns. Same Databricks spend, strictly
more answers.

This workshop is aligned with the `docs/demo-guide/` narrative but is a separate
executable asset. The guide is the story; the workshop is the execution.

**Audience:** Workshop participants running the demo interactively on Databricks.

## Quick Start (from scratch)

Confirm the [Prerequisites](#prerequisites) are in place, then run the notebooks
in order on the right compute:

| Order | Notebook | Compute | Stage |
|---|---|---|---|
| 1 | `00_setup_data.ipynb` | dedicated or serverless | Load the six Silver base tables from the committed CSVs |
| 2 | `01_required_setup.ipynb` | dedicated cluster | Store Neo4j credentials and Genie Space IDs, verify the Aura connection |
| 3 | `02_genie_silver_questions.ipynb` | serverless | Anchor: run the before/after reveal against both Genie Spaces |
| 4 | `03_neo4j_ingest.ipynb` | dedicated cluster | Load Silver tables into Neo4j |
| 5 | `04_gds_enrichment.ipynb` | dedicated cluster | Run GDS; patterns become columns |
| 6 | `05_pull_gold_tables.ipynb` | dedicated cluster | Enrich; results land in Gold |
| 7 | `06_kyc_walkthrough.ipynb` | dedicated cluster | KYC: resolve shared identities with WCC, build the knowledge layer, land the KYC columns in Gold |

`00_setup_data.ipynb` is only needed if the admin has not already loaded the
base tables. `01_required_setup.ipynb` is only needed if the admin has not
already populated the `neo4j-graph-engineering` secret scope.

## Prerequisites

The demo owner runs the `enrichment-pipeline/` setup first, so that before the
first notebook:

1. **Neo4j Spark Connector** is installed as a cluster library on the dedicated
   cluster:
   ```
   org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3
   ```
2. **The `neo4j-graph-engineering` secret scope** contains `uri`, `username`,
   `password`, `genie_space_id_before`, and `genie_space_id_after`. The demo
   owner populates these through the root
   [Common Setup](../README.md#common-setup) (`./setup_secrets.sh`). Participants
   can also store them interactively by running `01_required_setup.ipynb`.
3. **The base tables** (`accounts`, `customers`, `merchants`, `transactions`,
   `account_links`, `account_labels`) exist in
   `graph-on-databricks.graph-enriched-schema`. The demo owner loads them with
   `enrichment-pipeline/upload_and_create_tables.sh`. Participants can also
   create and load them interactively by running `00_setup_data.ipynb`, which
   fetches the committed CSVs from GitHub and writes the same tables. The
   `customers` table feeds the KYC identity layer in `03_neo4j_ingest` and
   `06_kyc_walkthrough`.

## Alternative Options

- **Skip 03–06** if the demo owner already ran the full `enrichment-pipeline/`
  pipeline. The Gold tables and enriched graph already exist, so you can run
  `02_genie_silver_questions.ipynb` for the before/after reveal and go straight
  to analysis.
- **Run GDS in the Aura Query tab** instead of the Python-client notebook
  (`04_gds_enrichment.ipynb`). See `aura_gds_guide.md` for the step-by-step
  algorithm guide, including the WCC identity-resolution steps that back
  `06_kyc_walkthrough.ipynb`.

## Notebook Reference

**`00_setup_data.ipynb`** *(dedicated or serverless)*: Creates and loads the six
Silver base tables (`accounts`, `customers`, `merchants`, `transactions`,
`account_links`, `account_labels`) in `graph-on-databricks.graph-enriched-schema`. Fetches
the committed CSVs and `ground_truth.json` from the public GitHub repo, writes
them to a Unity Catalog Volume, creates the tables with column comments, and
loads the data. The notebook equivalent of
`enrichment-pipeline/upload_and_create_tables.sh`. Run once if the admin has not
already loaded the base tables.

**`01_required_setup.ipynb`**: Stores Neo4j credentials and both Genie Space IDs
in the `neo4j-graph-engineering` scope, then verifies the Aura connection. Run
once on the dedicated cluster if the admin has not already populated the scope.

**`02_genie_silver_questions.ipynb`** *(serverless)*: Runs the before/after
reveal live against both Genie Spaces. A tabular warm-up confirms Genie is
working. An analytics challenge shows it handling joins and conditional
aggregates. Then three anchor before/after pairs run side by side (merchant
favorites, book share, investigator review queue), followed by two validation
pairs (merchant ring-candidate share; high-volume account community membership).
The gap between each before and after answer is the argument for the pipeline.

**`03_neo4j_ingest.ipynb`** *(dedicated cluster)*: Load Silver into Neo4j. Reads
the Delta tables and writes them as a property graph: `:Account` and
`:Merchant` nodes, `TRANSACTED_WITH` (Account → Merchant) and `TRANSFERRED_TO`
(Account → Account) relationships. Its final section also loads the KYC identity
layer from `customers`: `:Customer` / `:Phone` / `:Address` nodes joined by
`OWNS` / `HAS_PHONE` / `HAS_ADDRESS`, with the uniqueness constraints that make
customers who share a phone or address MERGE onto one identifier node. This is
the layer `06_kyc_walkthrough.ipynb` resolves over.

**`04_gds_enrichment.ipynb`** *(dedicated cluster)*: Run GDS, patterns become
columns. Runs three GDS algorithms via the `graphdatascience` Python client and
writes the results back to each Account node:
- **PageRank** → `risk_score` (centrality in the transfer network)
- **Louvain** → `community_id` (each fraud ring becomes one community)
- **Node Similarity** → `similarity_score` (Jaccard overlap of shared-merchant sets)

**`05_pull_gold_tables.ipynb`** *(dedicated cluster)*: Enrich, results land in
Gold. Reads the enriched Account nodes and similarity relationships back from
Neo4j and writes three Gold tables that the AFTER Genie space queries:
- **`gold_accounts`**: account metadata plus `risk_score`, `community_id`,
  `similarity_score`, community aggregates (`community_size`,
  `community_avg_risk_score`, `community_risk_rank`, `inbound_transfer_events`),
  and the derived flags `is_ring_community` and `fraud_risk_tier`
- **`gold_account_similarity_pairs`**: pairwise similarity scores with a
  `same_community` flag
- **`gold_fraud_ring_communities`**: one row per Louvain community with
  `member_count`, `avg_risk_score`, `avg_similarity_score`, `is_ring_candidate`,
  and `top_account_id`

**`06_kyc_walkthrough.ipynb`** *(dedicated cluster)*: KYC identity resolution and
provenance, the beats a warehouse cannot reach with the money-movement graph
alone. Runs after `05_pull_gold_tables`. Projects the identity layer loaded in
`03_neo4j_ingest`, runs Weakly Connected Components to resolve customers who
share phones or addresses into one identity cluster, and writes four graph
features back to each `:Account`: `shared_phone_count`, `shared_address_count`,
`identity_cluster_id`, and `identity_cluster_size`. It then builds a thin
knowledge layer (`:Policy` / `:BusinessTerm` / `:BusinessRule` / `:DataSource`)
and classifies every shared-identity customer with a `:CLASSIFIED_AS` edge that
names the policy, definition, and source columns behind the call. The four KYC
columns land on `gold_accounts` beside `risk_score` and `community_id`, so the
AFTER Genie space can answer synthetic-identity questions. The notebook closes
with a presenter walkthrough. `KYC_DEMO.md` is the full operator-and-presenter
guide this notebook implements for the workshop path.

## Reference Material

- [`../docs/demo-guide/genie-questions.md`](../docs/demo-guide/genie-questions.md):
  copy-paste question bank organized by category
- `GENIE_SETUP.md`: where the live Genie Space configuration comes from
  (`enrichment-pipeline/setup/provision_genie_spaces.py` +
  `enrichment-pipeline/genie_instructions.md` + UC column comments), plus the
  workshop-specific before/after narrative for the "hub of a money movement
  network" question
- `aura_gds_guide.md`: step-by-step GDS algorithm guide for the Neo4j Aura Query
  tab, an alternative to the Python-client notebook, covering both the fraud
  algorithms (`04_gds_enrichment`) and the WCC identity resolution
  (`06_kyc_walkthrough`)
- [`../KYC_DEMO.md`](../KYC_DEMO.md): the full KYC operator-and-presenter guide
  that `06_kyc_walkthrough.ipynb` implements, including the planted story ring
  and expected values
- `diagrams/`: architecture diagrams for the workshop

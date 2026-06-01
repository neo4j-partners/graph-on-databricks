# Enrichment Pipeline: Admin Setup and CLI Job Runner

The one-time admin setup and CLI-driven job runner for the graph enrichment
pipeline. It generates synthetic fraud data, loads Delta tables into Unity
Catalog, configures secrets, provisions Genie Spaces, submits pipeline stages as
unattended Databricks Jobs, runs Neo4j ingest and GDS, pulls enriched Gold
tables, and validates output against ground truth.

The notebooks under `workshop/` do the same work interactively in a live kernel.
The scripts here wrap that logic as Databricks Python tasks that run unattended
via the CLI. For the architecture overview and the shared `.env` + secret setup,
see the top-level [README](../README.md#common-setup).

## Quick Start (from scratch)

After the root [Common Setup](../README.md#common-setup) (`.env`, secrets, and
base tables) and the [Prerequisites](#prerequisites) below (cluster libraries,
CLI auth), run the whole pipeline with one command. The orchestrator re-runs the
shared upload and secret steps idempotently, then does the graph work. The
synthetic dataset is already committed in `finance-genie/data/`, so data
generation is not part of the happy path:

```bash
cd enrichment-pipeline
./run_existing_data_pipeline.py        # full 16-step orchestrator
```

This validates the committed data, uploads tables, provisions Genie Spaces, runs
the BEFORE baseline, ingests into Neo4j, runs GDS, pulls the three Gold tables,
validates them against ground truth, and runs the AFTER Genie observation. Each
step prints an explicit header and heartbeat output.

When it finishes you have: the five Silver base tables, an enriched Neo4j graph,
the three Gold tables (`gold_accounts`, `gold_account_similarity_pairs`,
`gold_fraud_ring_communities`), and recorded BEFORE and AFTER Genie runs in the
results volume.

### Regenerate the dataset (optional)

Only if you want to change the dataset size, seed, or fraud parameters:

```bash
uv run setup/generate_data.py          # writes to finance-genie/data/
```

Tuning constants live in `config.py` (read from `finance-genie/.env`). To verify
the structural fraud patterns of freshly generated data before any GDS run:

```bash
uv run diagnostics/verify_fraud_patterns.py
```

## Prerequisites

- **Local `.env` symlink to the parent.** The CLI job runner (`uv run python -m
  cli submit ...`) reads `.env` from the current directory, so it does not pick
  up the shared `finance-genie/.env` on its own. Link the local file to the
  parent so the CLI and the pipeline scripts share one source of truth (and one
  `DATABRICKS_PROFILE`):

  ```bash
  cd enrichment-pipeline
  ln -sf ../.env .env
  ```

- **Databricks CLI** authenticated against your workspace. The shell scripts call
  the CLI directly, so an expired or missing token causes a
  `failed during request visitor` error.

  ```bash
  brew install databricks/tap/databricks          # macOS, if needed
  databricks auth login --host https://<your-workspace> --profile <profile-name>
  databricks auth status                           # verify the token is valid
  ```

  With a named profile, set `DATABRICKS_CONFIG_PROFILE=<profile>` in `.env` or
  export it before running the scripts.
- **Neo4j Spark Connector JAR** as a cluster library:
  `org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3`
- **graphdatascience** as a cluster library (PyPI)
- **Databricks secret scope** `neo4j-graph-engineering` with `uri`, `username`,
  `password`, `genie_space_id` (written by the root Common Setup)
- **uv** installed locally (`brew install uv` or `pip install uv`)

Confirm the cluster is ready before submitting any job:

```bash
uv run validation/validate_cluster.py
```

## Alternative Options

### Run with existing data, full pipeline

The Quick Start uses `run_existing_data_pipeline.py`. Override the per-step
timeout when needed:

```bash
PIPELINE_STEP_TIMEOUT_SECONDS=10800 ./run_existing_data_pipeline.py
```

### Resume or subset the orchestrator

Resume from a later numbered step after a transient failure, or stop early:

```bash
PIPELINE_START_STEP=11 ./run_existing_data_pipeline.py     # skip steps 1-10
PIPELINE_STOP_STEP=5   ./run_existing_data_pipeline.py     # run steps 1-5 only
```

### Run stage-by-stage via the CLI

To drive individual stages instead of the orchestrator, submit them as
Databricks Python tasks. Upload the job scripts first (required whenever scripts
are added or renamed):

```bash
uv run python -m cli upload --all      # upload jobs/ scripts + sql/gold_schema.sql
uv run python -m cli submit <script>   # submit one stage
uv run python -m cli logs              # inspect the most recent run
uv run python -m cli clean --yes       # clean up workspace files and run history
```

The numbered stages, in order:

```bash
uv run python -m cli submit 01_genie_run_before.py     # BEFORE baseline
uv run python -m cli submit 02_neo4j_ingest.py         # push Delta tables into Neo4j
uv run setup/run_gds.py                                # run GDS (local; --force to recompute)
uv run validation/verify_gds.py                        # verify GDS outputs vs ground truth
uv run python -m cli submit 03_pull_gold_tables.py     # pull Gold tables (optional, see below)
uv run python -m cli submit 04_validate_gold_tables.py # data-correctness gate
uv run python -m cli submit 05_genie_run_after.py      # AFTER observation
```

`05_genie_run_after.py` picks one question per category by default. Pass
`SAMPLERS=` to select a subset:

```bash
uv run python -m cli submit 05_genie_run_after.py SAMPLERS=cat1_portfolio,cat4_operational
```

### Optional: pull Gold tables

`03_pull_gold_tables.py` is optional for the deployed `graph-fraud-analyst` app,
which reads ring, risky-account, and central-account data live from Neo4j via
Cypher. The Gold tables exist for two narrower cases: the Genie quickstart, so
Genie has tables to query before any Load action runs; and a fallback path if
Aura is unreachable. Skip it unless you need either case.

### Optional: diagnostics

Run directly (not via the CLI), from inside `enrichment-pipeline/`:

```bash
uv run validation/validate_neo4j.py        # raw Neo4j connection
uv run validation/validate_neo4j_graph.py  # node/edge counts after ingestion
uv run validation/diagnose_similarity.py   # Node Similarity / Jaccard diagnostics
uv run diagnostics/verify_fraud_patterns.py # structural fraud-pattern checks on raw data
```

All validation scripts read credentials from `finance-genie/.env`.

## Stage Reference

The orchestrator runs the local admin setup, then submits cluster jobs and runs
GDS against Aura:

```
┌─────────────────────────────────────────────────────────────────┐
│  Local machine, one-time setup                                  │
│  generate_data.py        → finance-genie/data/ (5 CSVs + JSON)  │
│  upload_and_create_tables.sh → Unity Catalog: 5 Delta tables    │
│  setup_secrets.sh        → Databricks secret scope              │
│  provision_genie_spaces.py → before-GDS + after-GDS Spaces      │
│  01_genie_run_before.py  → BEFORE baseline logged               │
└──────────────────────────┬──────────────────────────────────────┘
                           │  python -m cli submit
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Databricks cluster                                             │
│  02_neo4j_ingest.py                                             │
│    reads:  accounts, account_labels, merchants, transactions,   │
│            account_links                                         │
│    writes: :Account + :Merchant nodes                           │
│            TRANSACTED_WITH + TRANSFERRED_TO rels                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Neo4j Spark Connector
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Neo4j Aura                                                     │
│  setup/run_gds.py  (runs locally via graphdatascience)          │
│    PageRank        → risk_score                                 │
│    Louvain         → community_id                               │
│    Node Similarity → similarity_score + :SIMILAR_TO rels        │
│  validation/verify_gds.py → verifies vs ground_truth.json       │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Neo4j Spark Connector
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Databricks cluster                                             │
│  03_pull_gold_tables.py  → gold_accounts,                       │
│                            gold_account_similarity_pairs,       │
│                            gold_fraud_ring_communities          │
│  04_validate_gold_tables.py → 6 checks vs ground_truth.json     │
│  05_genie_run_after.py   → AFTER observation artifact           │
└─────────────────────────────────────────────────────────────────┘
```

### BEFORE Genie (`01_genie_run_before.py`)

Runs three structural-discovery questions plus a teaser against the BEFORE space
to capture the baseline before enrichment. The misses are not Genie failures:
Genie answers each structural question, but it answers a different question than
the one asked. Network centrality and community membership do not exist as
columns in the Silver tables, so no SQL query can produce them. The run records
the gap explicitly against `ground_truth.json`.

| Case | Question | After-GDS criterion (BEFORE is expected to miss) |
|------|----------|----------------|
| `hub_detection` | "Are there accounts that seem to be the hub of a money movement network that are potentially fraudulent?" | top-20 precision > 0.70 |
| `community_structure` | "Find groups of accounts transferring money heavily among themselves." | max Louvain ring coverage > 0.80 |
| `merchant_overlap` | "Which pairs of accounts have visited the most merchants in common?" | same-ring fraction > 0.60 with ≥5 pairs |
| `teaser_portfolio` | "What share of accounts sits in communities flagged as ring candidates, broken out by region?" | not graded; reported as not available on this catalog |

### Neo4j Ingest (`02_neo4j_ingest.py`)

Pushes the five Delta tables into Neo4j as a property graph: fetches credentials
from the secret scope, clears the graph, writes `:Account` (accounts LEFT JOIN
account_labels) and `:Merchant` nodes, creates uniqueness constraints, writes
`TRANSACTED_WITH` (Account → Merchant) and `TRANSFERRED_TO` (Account → Account)
relationships, then prints counts.

### GDS Pipeline (`setup/run_gds.py`)

Runs the GDS algorithms against Aura using the `graphdatascience` Python client.
No cluster required. It is the canonical entry point: it delegates to
`validation/run_gds.py` (the single source of truth for algorithm parameters) and
adds an idempotency check, so a fully-populated graph is a no-op. Use `--force`
to recompute.

| Property | Algorithm |
| --- | --- |
| `risk_score` | PageRank |
| `community_id` | Louvain |
| `betweenness_centrality` | Betweenness (sampled) |
| `similarity_score` | max JACCARD over `:SIMILAR_TO` edges from Node Similarity |

It also creates `:SIMILAR_TO` relationships and the `account_community_id` /
`account_risk_score` lookup indexes. The deployed `graph-fraud-analyst` app
requires these properties to be populated.

### Verify GDS (`validation/verify_gds.py`)

Checks all five signal properties against ground truth and prints a pass/fail
summary. Confirms PageRank separation, Louvain ring coverage, and Node Similarity
ratios. Run after `run_gds.py` and before pulling Gold tables. Exits non-zero on
any failure.

### Pull Gold Tables (`03_pull_gold_tables.py`)

Reads GDS features back from Neo4j and writes `gold_accounts`,
`gold_account_similarity_pairs`, and `gold_fraud_ring_communities` to Delta,
following the same DDL-first pattern as the base tables (`sql/gold_schema.sql`,
uploaded alongside the job scripts). Optional, as noted above.

### Validate Gold Tables (`04_validate_gold_tables.py`)

Data-correctness gate. Runs six checks against the three Gold tables, joining
against `ground_truth.json` from the UC Volume. All joins key on `account_id`,
not `community_id`, which drifts across GDS runs. Exits non-zero on any failure.

1. `gold_fraud_ring_communities` has exactly 10 rows with `is_ring_candidate=true`
2. Each ring-candidate community is dominated by a single ground-truth ring covering ≥ 80% of its home ring
3. All ring-candidate communities have `member_count` BETWEEN 50 AND 200
4. `fraud_risk_tier='high'` covers ≥ 95% of the 1,000 ring-member accounts
5. For each ring-candidate community, `top_account_id` is a member of the dominant ring per `ground_truth.json`
6. In `gold_account_similarity_pairs`, `same_community=true` holds for ≥ 95% of pairs where both accounts are in the same ring per `ground_truth.json`

### AFTER Genie (`05_genie_run_after.py`)

Picks one question from each of five category samplers against the AFTER space,
captures the SQL and rows Genie returns, and writes a JSON artifact to
`RESULTS_VOLUME_DIR`. No grading; compare the artifact against the BEFORE
baseline. Each question runs up to `GENIE_TEST_RETRIES` times (default 2).

| Sampler | Category |
|---------|----------|
| `cat1_portfolio` | Portfolio composition over structural segments |
| `cat2_cohort` | Cohort comparisons across risk tiers |
| `cat3_community_rollup` | Rollups over ring-candidate communities |
| `cat4_operational` | Operational and investigator workload |
| `cat5_merchant` | Merchant-side questions |

## Project Structure

```
enrichment-pipeline/
├── pyproject.toml              # uv project; all dependencies
├── config.py                   # loads ../.env, exposes all tuning constants
├── run_existing_data_pipeline.py # 16-step orchestrator over committed data
├── upload_and_create_tables.sh # applies sql/schema.sql, uploads CSVs, loads Delta tables
├── setup_secrets.sh            # stores Neo4j credentials in Databricks secrets
├── genie_instructions.md       # instructions text embedded in Genie Spaces
├── logs/                       # local mirror of UC Volume artifacts
├── setup/                      # one-time local admin scripts
│   ├── generate_data.py        # generates synthetic fraud dataset to finance-genie/data/
│   ├── run_gds.py              # canonical GDS entry point (idempotent)
│   ├── provision_genie_spaces.py # configures before/after Genie Spaces
│   ├── checks_structural.py    # structural check helpers for verify_fraud_patterns.py
│   ├── checks_genie_csv.py     # Genie CSV / GDS output check helpers
│   └── report.py               # report rendering and JSON snapshot IO
├── diagnostics/                # optional regression checks
│   └── verify_fraud_patterns.py # checks structural properties of generated data
├── sql/                        # all DDL in one place
│   ├── schema.sql              # base table DDL with UC column comments
│   └── gold_schema.sql         # gold table DDL with UC column comments
├── cli/
│   ├── __init__.py             # Runner instantiation (scripts_dir="jobs")
│   └── __main__.py             # python -m cli entry point
├── jobs/                       # scripts submitted via python -m cli submit
│   ├── 01_genie_run_before.py  # BEFORE space runner: 3 structural questions + teaser
│   ├── 02_neo4j_ingest.py      # push Delta tables into Neo4j as a property graph
│   ├── 03_pull_gold_tables.py  # pull GDS features back to Delta gold tables
│   ├── 04_validate_gold_tables.py # data-correctness gate for the three gold tables
│   ├── 05_genie_run_after.py   # AFTER space runner: one question per category sampler
│   ├── cat1_portfolio.py … cat5_merchant.py # AFTER question banks
│   ├── _cluster_bootstrap.py   # cluster bootstrap helpers
│   ├── _demo_utils.py          # Genie API + check helpers
│   ├── _genie_run_artifact.py  # shared artifact schema + loader
│   ├── _gold_constants.py      # shared thresholds for pull and validate
│   └── _neo4j_secrets.py       # loads Neo4j credentials from the secret scope
└── validation/                 # local preflight and diagnostic scripts
    ├── _common.py              # shared helpers
    ├── validate_neo4j.py       # connection check
    ├── validate_cluster.py     # cluster state and required library check
    ├── validate_neo4j_graph.py # node/edge count and structure checks
    ├── run_gds.py              # GDS algorithm source of truth
    ├── verify_gds.py           # verifies GDS outputs, prints summary report
    └── diagnose_similarity.py  # Jaccard ratio diagnostics
```

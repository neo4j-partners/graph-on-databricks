# finance-genie-dbxcarta

A standalone Python package that consumes **published** dbxcarta as a normal
versioned dependency to build a Neo4j semantic layer over the Finance Genie
Lakehouse, evaluate text-to-SQL accuracy across three context arms, and run a
read-only local demo. It imports no dbxcarta source and does not require the
dbxcarta checkout to be present.

This is the consumer described in `dbxcarta/docs/proposals/published.md`. It
differs from `graph-on-databricks/sql-semantics`, which pins editable local
paths to a sibling dbxcarta checkout. Here, `pyproject.toml` pins dbxcarta by
version with no `[tool.uv.sources]`.

## Catalog scope

The semantic layer is built over the single Finance Genie catalog
`graph-enriched-lakehouse.graph-enriched-schema`, owned by
`finance-genie/enrichment-pipeline`:

- Base tables: `accounts`, `merchants`, `transactions`, `account_links`,
  `account_labels`
- Gold (graph-derived) tables: `gold_accounts`,
  `gold_account_similarity_pairs`, `gold_fraud_ring_communities`

The same catalog holds the dbxcarta ops volume (`graph-enriched-volume`), the
run-summary table, and the uploaded question set, so there is no separate ops
catalog to bootstrap. The upstream pipeline owns table creation; the
run-summary table is created automatically on the first ingest.

## Layout

```text
finance-genie/dbxcarta/
├── pyproject.toml              # pinned dbxcarta deps, no source overrides
├── databricks.yml              # ingest + client jobs (consumer-owned DAB)
├── dbxcarta-overlay.env        # committed, secret-free dbxcarta CLI config
├── .env.sample                 # standalone local-demo config (copy to .env)
├── questions.json              # 12-question eval fixture (graph-enriched-lakehouse)
├── dbxcarta-dist/              # vendored dbxcarta wheels (committed simulate-publish index)
├── scripts/stage_wheelhouse.sh # maintainer: refresh dbxcarta-dist from a dbxcarta build
├── src/finance_genie_dbxcarta/
│   ├── __init__.py             # re-exports `preset`
│   ├── preset.py               # StandardPreset(questions_file=...)
│   └── local_demo.py           # read-only local CLI
└── tests/                      # non-live tests
```

## Three entry points

### 1. Ingest (build the semantic layer)

`databricks.yml` job `finance_genie_dbxcarta_ingest` runs the published
`dbxcarta-ingest` entry point on a classic cluster: it reads Unity Catalog
metadata, writes embeddings and the Neo4j semantic graph, and creates the run
summary table.

### 2. Eval (text-to-SQL benchmark)

`databricks.yml` job `finance_genie_dbxcarta_client` runs the published
`dbxcarta-client` entry point: it benchmarks `questions.json` across the
`no_context`, `schema_dump`, and `graph_rag` arms and reports per-arm metrics
(attempted, parsed, executed, non_empty, exec_rate, correct_rate). The three
arms are a progression, not three attempts at one task; `graph_rag` matching or
beating `schema_dump` on `correct_rate` is the result being checked.

### 3. Local demo (read-only CLI)

`local_demo.py` answers a single question with graph context locally, with no
Databricks job. It allows only `SELECT`, `WITH`, and `EXPLAIN`.

## Simulate-publish: shipping dbxcarta without PyPI

dbxcarta is not yet on PyPI. The dbxcarta wheels are **vendored** into the
committed `dbxcarta-dist/` directory, and both the local `uv sync` and the
cluster jobs resolve from there. Because the wheels are in-repo and the
find-links path is relative, a new developer just runs `uv sync`, with no
dbxcarta checkout needed.

```
  dbxcarta checkout                 finance-genie/dbxcarta
  ─────────────────                 ──────────────────────
  uv build --package core ─┐
  uv build --package client├─► dist/
  uv build --package spark ┘     │
                                 │  scripts/stage_wheelhouse.sh (maintainer only)
                                 ▼
                          dbxcarta-dist/  (COMMITTED, vendored)
                                 │
                  ┌──────────────┴───────────────┐
                  ▼                               ▼
        uv.toml (COMMITTED)            databricks.yml `whl:` libraries
        find-links ./dbxcarta-dist     ./dbxcarta-dist/dbxcarta_*.whl
                  │                               │
              uv sync                      bundle upload → cluster
        local dev: preset, tests,         ingest + client
        local demo
```

- **Local** (`uv sync`, local demo, tests): a committed `uv.toml` supplies
  `find-links = ["./dbxcarta-dist"]`. `uv.lock` is committed too (the relative
  path is portable). See `dbxcarta/docs/reference/simulate-publish.md`.
- **Cluster** (`databricks.yml`): the bundle ships the same vendored wheels as
  `whl:` libraries from `./dbxcarta-dist`. Third-party deps (neo4j, pydantic)
  still install from PyPI.

Refreshing the vendored wheels is a maintainer step, run only when dbxcarta
changes: rebuild the dbxcarta wheels, then run `./scripts/stage_wheelhouse.sh`
and commit `dbxcarta-dist/`.

When dbxcarta is published: delete `uv.toml` and `dbxcarta-dist/`, bump the pins
in `pyproject.toml` and `databricks.yml`'s `dbxcarta_version` to the first
published version, and flip the `whl: ./dbxcarta-dist/...` lines in
`databricks.yml` to the `pypi:` lines shown in its comments.

## Who does what

The dbxcarta wheels are vendored in `dbxcarta-dist/`, so a new developer resolves
and runs entirely from this project. Only refreshing those wheels reaches into
dbxcarta. The full flow spans three places:

| Step | Runs in | What it does |
|------|---------|--------------|
| (maintainer) Refresh dbxcarta wheels | **dbxcarta** + this project | Rebuild dbxcarta wheels via the [local publishing guide](../../../dbxcarta/docs/reference/simulate-publish.md), then `./scripts/stage_wheelhouse.sh` and commit `dbxcarta-dist/`. New developers skip this. |
| Populate the catalog | **finance-genie/enrichment-pipeline** | Create the `graph-enriched-lakehouse` data the semantic layer is built over. |
| Provision the secret scope | **finance-genie** (`setup_secrets.sh`) | Put `NEO4J_*` in `dbxcarta-neo4j-finance-genie`. |
| Resolve + configure | **finance-genie/dbxcarta** | `uv sync` (resolves from `dbxcarta-dist/`), `.env`, the overlay. |
| Readiness + upload questions | **finance-genie/dbxcarta** | dbxcarta CLI against this project's overlay. |
| Run jobs | **finance-genie/dbxcarta** | `databricks bundle` ingest then client. |
| Local demo | **finance-genie/dbxcarta** | Read-only CLI. |

## Setup

The dbxcarta wheels are vendored in `dbxcarta-dist/` and committed, so there is no
dbxcarta build to run and no sibling checkout to clone. Resolve and configure from
this project:

```bash
cd finance-genie/dbxcarta

# Resolve dbxcarta from the vendored wheels (uv.toml find-links ./dbxcarta-dist):
uv sync

# Copy the local-demo env template and fill in credentials:
cp .env.sample .env
```

Check readiness and upload the question set. These use the dbxcarta CLI but run here,
against this project's overlay and preset, so the work is finance-genie-side:

```bash
uv run dbxcarta preset finance_genie_dbxcarta:preset --check-ready \
  --env-file dbxcarta-overlay.env

uv run dbxcarta preset finance_genie_dbxcarta:preset --upload-questions \
  --env-file dbxcarta-overlay.env
```

## Run the jobs (ingest then client) — finance-genie/dbxcarta

The vendored `dbxcarta-dist/` wheels are shipped as bundle `whl:` libraries, so
no staging step is needed here.

```bash
# Deploy and run. Provide the preprovisioned cluster and warehouse.
databricks bundle deploy \
  --var="cluster_id=<cluster-id>" --var="warehouse_id=<warehouse-id>"
databricks bundle run finance_genie_dbxcarta_ingest \
  --var="cluster_id=<cluster-id>" --var="warehouse_id=<warehouse-id>"
# After ingest finishes:
databricks bundle run finance_genie_dbxcarta_client \
  --var="cluster_id=<cluster-id>" --var="warehouse_id=<warehouse-id>"
```

The cluster must allow `SINGLE_USER` classic compute with task-level Maven
libraries (the Neo4j Spark connector), and the secret scope
`dbxcarta-neo4j-finance-genie` must hold `NEO4J_URI`, `NEO4J_USERNAME`, and
`NEO4J_PASSWORD`. The ingest entry point reads those from the scope itself.

## Run the local demo — finance-genie/dbxcarta

```bash
# List the question set
uv run python -m finance_genie_dbxcarta.local_demo questions
# Check connectivity and graph content
uv run python -m finance_genie_dbxcarta.local_demo preflight
# Answer one question with retrieved graph context
uv run python -m finance_genie_dbxcarta.local_demo ask --question-id fg_q01 --show-context
# Ad-hoc read-only query
uv run python -m finance_genie_dbxcarta.local_demo sql \
  "SELECT COUNT(*) FROM \`graph-enriched-lakehouse\`.\`graph-enriched-schema\`.accounts"
```

## Sequencing

The local demo and the non-live tests run today against the wheelhouse. The
ingest and client jobs additionally require the upstream Finance Genie catalog
to be populated, the secret scope provisioned, and a preprovisioned cluster and
warehouse. They cannot complete end to end until those are in place.

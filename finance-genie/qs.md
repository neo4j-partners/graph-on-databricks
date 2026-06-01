# Finance Genie Documentation Cleanup & Organize Plan

This is a working plan for reorganizing three READMEs so a reader can find one
common setup, one happy path per project, and clearly-labeled alternatives. It
guides the later README edits; it is not the edits themselves.

## Problem

The docs make it hard to figure out how to actually run the project.

1. **Main `README.md`** mixes shared setup, two architecture diagrams, and a
   project map, but never gives one "here is the path to follow." The two path
   sections describe ASCII diagrams but do not link to the READMEs that run each
   path. It also has stale references:
   - `apx-demo/` (L10) — that project is now `graph-fraud-analyst/`
   - `demo-guide/` (L77, 146, 148, 162, 176) — actual path is `docs/demo-guide/`
   - `SCOPING_GUIDE.md` (L140) — does not exist
2. **`enrichment-pipeline/README.md`** leads with a 60-line ASCII diagram and a
   numbered 1–12 sequence with prerequisites and optional flows interleaved.
   There is no clean quick start. The one-command orchestrator
   (`run_existing_data_pipeline.py`) is buried mid-document as "optional," even
   though it is the fastest path. The 1–12 step numbers do not match the
   orchestrator's internal 16 steps, and resume/subset flows are scattered.
3. **`workshop/README.md`** is closer, but the prerequisite state, the minimal
   notebook path, and the optional branches (skip 02–04 if the admin pre-ran the
   pipeline; `06_train_model` off-path; Aura Query-tab alternative to the Python
   client) are not cleanly separated.

## Goals & principles

- One common setup, defined once at the root, linked from everywhere.
- Each runnable project README opens with a **Quick Start (from scratch)** before
  any alternatives.
- Alternatives (resume, subset, optional stages, manual paths) go under a
  clearly separated **Alternative options** heading, never interleaved with the
  happy path.
- Every path section in the main README links to the README that runs it.
- All internal links resolve.
- Consistent heading vocabulary across READMEs:
  `Quick Start (from scratch)` → `Prerequisites` → `Alternative options` → `Reference`.

## Verified facts

- Shared setup = root `finance-genie/.env` (copied from `.env.sample`) +
  `./setup_secrets.sh`, which writes three scoped secret scopes:
  `neo4j-graph-engineering`, `simple-finance-analyst`, `mcp-neo4j-secrets`.
- `enrichment-pipeline/run_existing_data_pipeline.py` is a 16-step orchestrator
  with `PIPELINE_START_STEP`, `PIPELINE_STOP_STEP`,
  `PIPELINE_STEP_TIMEOUT_SECONDS` env controls.
- Individual stages run via `uv run python -m cli upload --all` then
  `uv run python -m cli submit <script>`; local GDS via `uv run setup/run_gds.py`.
- Workshop notebooks: `00_required_setup` → `01_genie_silver_questions` →
  `02_neo4j_ingest` → `03_gds_enrichment` → `04_pull_gold_tables`, with
  `06_train_model` off-path/optional. `aura_gds_guide.md` is an alternative to
  `03`.
- READMEs present: `enrichment-pipeline/README.md`, `workshop/README.md`,
  `simple-finance-agent/README.md`, `neo4j-mcp-demo/README.md`.
  `simple-finance-agent` is the endpoint the MCP path links to;
  `neo4j-mcp-demo` is the connection setup it depends on.

## Shared setup (the common path to extract)

Canonical one-time setup block. Lives in the main README and is linked, not
duplicated, from the subproject READMEs:

1. `cd finance-genie && cp .env.sample .env`, then fill in Databricks, Neo4j,
   and Genie values.
2. `./setup_secrets.sh --profile <profile>` — writes the three secret scopes.
3. **Upload data and create tables**

   ```
   cd enrichment-pipeline
   ./upload_and_create_tables.sh
   ```

   The dataset is checked into `finance-genie/data/` so participants can browse
   the CSVs and `ground_truth.json` directly. The upload step reads that shared
   data dir, uploads the five CSVs and `ground_truth.json` to the Unity Catalog
   Volume, applies `sql/schema.sql` to create all five base tables with Unity
   Catalog column-level comments, then loads data via `INSERT OVERWRITE`.
   Requires `DATABRICKS_WAREHOUSE_ID` in `finance-genie/.env`.

   Generating data is optional — only run `uv run setup/generate_data.py
   --output ../data` if you want to change the dataset (size, seed, fraud
   parameters). Otherwise the committed `finance-genie/data/` is used as-is.

   Schema and data are separate by design:
   - `sql/schema.sql` defines column types and Unity Catalog column descriptions
     (the contract Genie reads)
   - `INSERT OVERWRITE` loads data without touching the schema; column comments
     survive every re-run
   - `CREATE OR REPLACE TABLE` in `sql/schema.sql` is idempotent; no manual drop
     steps needed
4. Pointer: "Now pick a path below."

Keep the existing scope → consumer → contents table:

| Scope | Used by | Contents |
|---|---|---|
| `neo4j-graph-engineering` | `enrichment-pipeline/` jobs and workshop notebooks | Neo4j URI, username, password, before/after Genie Space IDs |
| `simple-finance-analyst` | `simple-finance-analyst` real backend | Neo4j URI, username, password, analyst Genie Space ID |
| `mcp-neo4j-secrets` | `neo4j-mcp-demo` and MCP-backed agents | AgentCore OAuth gateway/client credentials, when `.mcp-credentials.json` is available |

## Main `README.md` reorg outline

Proposed top-to-bottom structure:

- **Title + one-paragraph what-this-is** — keep the before/after framing,
  condensed from the current "Overview."
- **Common Setup** — the shared block above, with the secret-scope table.
- **Choose your path** — a short decision table:
  - Want enriched Gold columns plus the workshop? → Path A
  - Want live MCP graph access through an agent? → Path B
- **Path A — Graph-Enriched Lakehouse** — keep the ASCII diagram, add links:
  - Admin / CI setup → `enrichment-pipeline/README.md`
  - Hands-on notebooks → `workshop/README.md`
  - Presenter narrative → `docs/demo-guide/` (fixed path)
- **Path B — MCP-Backed Simple Agent** — keep the ASCII diagram, add links:
  - Agent endpoint → `simple-finance-agent/README.md`
  - MCP connection setup it depends on → `neo4j-mcp-demo/README.md`
- **Project Map** — condense; fix `apx-demo/` → `graph-fraud-analyst/` and
  `demo-guide/` → `docs/demo-guide/`.
- **Further reading** — `ARCHITECTURE.md`, slides. Remove the `SCOPING_GUIDE.md`
  link (the file does not exist).

### Stale-link punch-list (main README)

| Current | Line(s) | Fix |
|---|---|---|
| `apx-demo/` | L10 | `graph-fraud-analyst/` |
| `demo-guide/` | L77, 146, 148, 162, 176 | `docs/demo-guide/` |
| `SCOPING_GUIDE.md` | L140 | remove the link (file does not exist) |

## `enrichment-pipeline/README.md` reorg outline

Proposed structure:

- **One-paragraph what-this-is** + pointer back to root Common Setup. Do not
  re-document `.env`/secrets in full.
- **Quick Start (from scratch)** — minimal happy path, promoted to the top.
  The dataset is already committed in `finance-genie/data/`, so data generation
  is not part of the happy path:
  ```
  cd enrichment-pipeline
  ./run_existing_data_pipeline.py        # full 16-step orchestrator
  ```
  One-line note on what you end up with: base tables, GDS run, gold tables, and
  BEFORE/AFTER Genie runs.
- **Regenerate the dataset (optional)** — only if you want to change data size,
  seed, or fraud parameters:
  ```
  uv run setup/generate_data.py --output ../data
  ```
- **Prerequisites** — CLI auth, cluster libraries (Neo4j Spark Connector JAR,
  `graphdatascience`), `validate_cluster.py` check. Kept after Quick Start so the
  happy path is visible first.
- **Alternative options** — clearly separated subsections:
  - *Run with existing data* — `run_existing_data_pipeline.py` without
    regenerating.
  - *Resume / subset* — `PIPELINE_START_STEP`, `PIPELINE_STOP_STEP`,
    `PIPELINE_STEP_TIMEOUT_SECONDS`.
  - *Run stage-by-stage via CLI* — the current numbered `submit` sequence, moved
    here as the manual alternative.
  - *Optional: pull Gold tables* — note it is optional for the deployed app.
  - *Optional diagnostics* — `verify_fraud_patterns.py`, `diagnose_similarity.py`.
- **Stage reference** — keep the detailed per-stage descriptions (current
  steps 7–12 content) and the ASCII diagram, moved below the runnable sections
  as reference, not as the lead.
- **Project structure** — keep as-is at the end.

## `workshop/README.md` reorg outline

Proposed structure:

- **One-paragraph what-this-is** + audience.
- **Quick Start (from scratch)** — minimal participant path: confirm prereq
  state, then run notebooks `00 → 01 → 02 → 03 → 04` in order, noting serverless
  vs dedicated cluster per notebook.
- **Prerequisites** — what the admin must have already run in
  `enrichment-pipeline/` (base tables loaded, Genie Spaces provisioned,
  `neo4j-graph-engineering` scope populated); cluster library requirement; link
  to root Common Setup.
- **Alternative options:**
  - *Skip 02–04* if the admin pre-ran the full enrichment pipeline (jump to
    query/analysis).
  - *Run GDS in the Aura Query tab* instead of the Python client
    (`aura_gds_guide.md`).
  - *Optional: `06_train_model.ipynb`* (off the 15-minute path).
- **Notebook reference** — keep the detailed per-notebook descriptions as
  reference below the runnable path.
- **Reference material** — keep (`genie-guide.md`, `GENIE_SETUP.md`,
  `aura_gds_guide.md`, `diagrams/`).

## Cross-cutting consistency rules

- All three READMEs point to the single root Common Setup; none re-document
  `.env`/secrets in full.
- Same heading vocabulary everywhere:
  `Quick Start (from scratch)` → `Prerequisites` → `Alternative options` → `Reference`.

## Code changes required for the moved data directory

The dataset now lives in `finance-genie/data/`, but three references still
hardcode `enrichment-pipeline/data/`. These must be repointed at the parent
`finance-genie/data/` before the upload/orchestrator steps work:

| File | Reference | Change |
|---|---|---|
| `enrichment-pipeline/upload_and_create_tables.sh` | `DATA_DIR="${SCRIPT_DIR}/data"` (L59) | point at `${SCRIPT_DIR}/../data` |
| `enrichment-pipeline/run_existing_data_pipeline.py` | `ROOT_DIR / "data" / file_name` (L60) | use `ROOT_DIR.parent / "data"` |
| `enrichment-pipeline/setup/generate_data.py` | `--output` default `./data` (L451) | default to `../data` |

Also update the script header comments and any prose referencing
`enrichment-pipeline/data/` to say `finance-genie/data/`.

## Files this plan will touch (in the follow-up edit pass)

- `finance-genie/README.md`
- `finance-genie/enrichment-pipeline/README.md`
- `finance-genie/workshop/README.md`
- `finance-genie/enrichment-pipeline/upload_and_create_tables.sh` (data path)
- `finance-genie/enrichment-pipeline/run_existing_data_pipeline.py` (data path)
- `finance-genie/enrichment-pipeline/setup/generate_data.py` (default output dir)

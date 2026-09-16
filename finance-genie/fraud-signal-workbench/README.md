# Fraud Signal Workbench

The Fraud Signal Workbench is a Databricks App built with
[apx](https://github.com/databricks-solutions/apx), FastAPI, and React. It runs
live Cypher against Neo4j Aura to surface candidate rings, risky accounts, and
central accounts. An analyst can then materialize a selected subgraph into
Delta tables and analyze it through Genie.

## Naming compatibility

The repository folder uses the product name `fraud-signal-workbench`. Existing
Databricks App, bundle, Python-package, and environment-variable identifiers
retain `graph-fraud-analyst` or `GRAPH_FRAUD_ANALYST_*`. Keeping those runtime
identifiers stable prevents the folder rename from creating a second remote app
or requiring a new service principal and grants.

Architecture at a glance:

| Screen | Backend | Data source |
| --- | --- | --- |
| Search (rings, risky, hubs) | Live Cypher | Aura node properties written by `enrichment-pipeline/setup/run_gds.py` |
| Load (materialize subgraph) | Cypher → Delta `CREATE OR REPLACE TABLE` | Neo4j → SQL warehouse |
| Analyze (Genie) | Genie Conversation API | Delta tables written by Load |

## Deploy to Databricks

### Prerequisites

- Complete the repository's canonical `make demo` setup so the shared data,
  Aura graph, GDS properties, Gold schema, and Genie Spaces exist.
- Install `uv`, `apx`, and the Databricks CLI.
- Authenticate the Databricks CLI against the target workspace.
- Grant the deployed app service principal the Unity Catalog and secret-scope
  permissions described below.

### 1. Configure the shared environment

The whole `finance-genie` repo shares a single `.env` at the repo root. If it does not exist yet, copy the sample and fill in values:

```bash
cp ../.env.sample ../.env
```

Required values are documented in `../.env.sample` under the Fraud Signal
Workbench section, plus the workspace settings at the top.

| Variable | Description |
| --- | --- |
| `DATABRICKS_PROFILE` | Profile name from `~/.databrickscfg`. |
| `GRAPH_FRAUD_ANALYST_WAREHOUSE_ID` | SQL warehouse the Load step uses to write Delta tables. |
| `GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID` | Genie Space ID that queries the Load-materialized Delta tables. |
| `GRAPH_FRAUD_ANALYST_CATALOG` | Unity Catalog catalog (default `graph-on-databricks`). |
| `GRAPH_FRAUD_ANALYST_SCHEMA` | Unity Catalog schema (default `graph-enriched-schema`). |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Local-dev only. The deployed app reads these from the `neo4j-graph-engineering` UC secret scope (bound in `databricks.yml`). |

The [canonical setup](../README.md#canonical-setup) supplies the Neo4j graph,
GDS properties, secret scope, and Genie Spaces this app uses. It intentionally
does not deploy the workbench or grant its service principal access.

### 2. Deploy

```bash
./scripts/deploy.sh
```

The script sources `.env`, validates the required IDs, then runs two CLI calls:

1. `databricks bundle deploy` uploads the build, creates the app resource, and attaches the warehouse and Genie Space from `databricks.yml`.
2. `databricks bundle run graph-fraud-analyst-app` pushes the uploaded source to the app's compute and starts uvicorn.

`bundle deploy` alone leaves the app `UNAVAILABLE`. The `bundle run` step is what makes the URL serve traffic, so both must succeed.

To deploy and stream live app logs in the same shell:

```bash
./scripts/deploy.sh --log
```

That runs both steps above and then tails `databricks apps logs graph-fraud-analyst --follow` until you ctrl-c.

### 3. Grant Unity Catalog access to the app service principal

The first deploy auto-provisions a service principal for the app (display name
`app-XXXXXX graph-fraud-analyst`). SQL warehouse operations run as that service
principal, not as the logged-in user, so it needs Unity Catalog grants on the
Gold-table schema. Without these grants the Load and Analyze operations fail
with an `INSUFFICIENT_PERMISSIONS` response.

Find the SP's `service_principal_client_id` once:

```bash
databricks apps get graph-fraud-analyst --profile "$DATABRICKS_PROFILE" \
  | grep service_principal_client_id
```

Then run these statements against the warehouse, substituting the client ID and
the configured catalog and schema when they differ from the defaults:

```sql
GRANT USE CATALOG ON CATALOG `graph-on-databricks`
  TO `<service_principal_client_id>`;
GRANT USE SCHEMA  ON SCHEMA  `graph-on-databricks`.`graph-enriched-schema`
  TO `<service_principal_client_id>`;
GRANT SELECT      ON SCHEMA  `graph-on-databricks`.`graph-enriched-schema`
  TO `<service_principal_client_id>`;
GRANT CREATE TABLE ON SCHEMA `graph-on-databricks`.`graph-enriched-schema`
  TO `<service_principal_client_id>`;
GRANT MODIFY      ON SCHEMA  `graph-on-databricks`.`graph-enriched-schema`
  TO `<service_principal_client_id>`;
```

Verify:

```sql
SHOW GRANTS `<service_principal_client_id>`
  ON SCHEMA `graph-on-databricks`.`graph-enriched-schema`;
```

You should see `USE CATALOG`, `USE SCHEMA`, `SELECT`, `CREATE TABLE`, and
`MODIFY`. Read privileges support verification and analysis; `CREATE TABLE` and
`MODIFY` let the Load step replace the materialized Delta tables. Apply these
grants once for each workspace where the app is deployed.

### 4. Grant the app SP READ on the Neo4j secret scope

The Search and Load endpoints connect to Neo4j Aura through the app SP. The credentials live in the `neo4j-graph-engineering` UC secret scope (referenced as resources in `databricks.yml`). The bundle deploy declares the resource bindings, but UC does not auto-grant scope ACLs; do it once:

```bash
databricks secrets put-acl neo4j-graph-engineering \
  <service_principal_client_id> READ \
  --profile "$DATABRICKS_PROFILE"
```

Verify:

```bash
databricks secrets list-acls neo4j-graph-engineering --profile "$DATABRICKS_PROFILE"
```

You should see a row with `permission: READ` for the app SP. If you skip this step, the app's startup lifespan logs `Neo4j connectivity check failed`, uvicorn exits, and the URL serves "App Not Available".

### 5. Verify or refresh Neo4j GDS properties

The deployed app expects four node properties on every `:Account` in Aura:
`risk_score` (PageRank), `community_id` (Louvain),
`betweenness_centrality` (sampled Betweenness), and `similarity_score` (maximum
Jaccard similarity from Node Similarity). The canonical setup populates them.
Run the setup script directly when you need to verify or recompute them:

```bash
cd ../enrichment-pipeline
uv run setup/run_gds.py            # idempotent: no-op if already populated
uv run setup/run_gds.py --force    # recompute and overwrite
```

The script checks current coverage first and exits 0 if the properties are already present. Without this setup, the `/api/search/*` endpoints return empty arrays (and Load fails its quality checks).

### 6. Open

The deploy script prints the app URL. Sign in with OAuth, then walk Screen 1 (Search) to Screen 2 (Load) to Screen 3 (Analyze).

Prerequisites for the deployed app to return data:

1. The Aura instance configured by `NEO4J_URI` is reachable from Databricks Apps egress and has the four GDS node properties populated (step 5).
2. The Genie Space referenced by `GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID` points at the same UC schema the Load step writes to.
3. The app SP has been granted UC schema access (step 3) and Neo4j secret-scope READ (step 4).

The deployed workbench does not invoke `../enrichment-pipeline/` at runtime.
Search reads come from Aura through Cypher, and Load materializes the three Gold
tables on demand. The canonical `make demo` workflow remains the supported way
to prepare the shared dataset, Aura graph, GDS properties, and Genie Spaces
before the app is deployed.

---

## Local development

Use the project-local wrapper. It sets `PATH` to this project's `.venv/bin`, rebuilds the venv if it has stale shebangs (e.g. after a directory rename), and forwards everything to `apx dev`.

```bash
./scripts/dev.sh start          # backend + frontend + OpenAPI watcher
./scripts/dev.sh status         # check what's running
./scripts/dev.sh logs -f        # stream logs
./scripts/dev.sh stop           # stop everything
./scripts/dev.sh restart        # restart backend, keep port
./scripts/dev.sh check          # tsc + ty type checks
```

The dev URL prints on `start` (typically `http://localhost:9001`). Hot reload is active: edits to `.tsx` files refresh the browser instantly; edits to `.py` files restart uvicorn automatically.

The backend reads `~/.databrickscfg` (the profile named in `../.env`) plus the Neo4j credentials from `../.env` (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`). Local dev talks to the same Aura and the same SQL warehouse as the deployed app, so a smoke walk in your browser exercises the same code path the demo does.

### Tests and type checks

```bash
uv run pytest
apx dev check          # TypeScript + Python type checks
```

### Production build

```bash
apx build              # builds .build/ for bundle deploy
```

---

## What's inside

- `src/graph_fraud_analyst/backend/` FastAPI service. Routes in `router.py`, business logic in `services/`, config in `core/_config.py`.
- `src/graph_fraud_analyst/ui/` React + Vite + TanStack Router frontend. Routes in `routes/`, shared state in `lib/flowContext.tsx`, generated OpenAPI client in `lib/api.ts`.
- `scripts/deploy.sh` env-driven bundle deploy with optional log tailing.
- `app.yml` Databricks Apps runtime entrypoint and env wiring.
- `databricks.yml` bundle definition (resources, target, variables).

The API contract is defined by
[`backend/models.py`](./src/graph_fraud_analyst/backend/models.py) and
[`backend/router.py`](./src/graph_fraud_analyst/backend/router.py). The frontend
client in [`ui/lib/api.ts`](./src/graph_fraud_analyst/ui/lib/api.ts) is generated
from that OpenAPI contract.

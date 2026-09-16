# Semantic Investigation Copilot

This directory contains the isolated Neocarta prototype for the Finance Genie
semantic investigation demo described in
[`../work-proposals/finance-demo.md`](../work-proposals/finance-demo.md).

The Phase 2 runtime ingests metadata for one Unity Catalog schema into a
dedicated Neo4j semantic store. It does not read or store source row values.
Neocarta then exposes the catalog through a stdio MCP server with catalog and
full-text retrieval tools.

## Runtime boundary

- `semantic-investigation-copilot/.env` is the one local source of runtime
  configuration. It is git-ignored and loaded explicitly by every runner.
- `.env.example` is the committed, redacted variable contract.
- The default local Neo4j instance listens only on loopback ports `17474` and
  `17687` and persists to the `finance-neocarta-data` Docker volume.
- A dedicated remote Neo4j or Aura instance is also supported, but the Python
  write path requires the explicit `NEOCARTA_ALLOW_REMOTE_STORE=true` opt-in.
- Ingestion and validation also refuse any target containing core Finance Genie
  operational labels such as `Account`, `Customer`, `Phone`, or `Address`.
- Do not copy values from the Finance Genie operational graph into this store.
  It contains schema metadata only.

The current prototype uses Neocarta `0.8.1` from the local checkout at
`/Users/ryanknight/projects/neo4j-labs/neocarta`, commit
`ba6bf7945bf9c60640c664a03ccc26d0013996bf`.

## Prerequisites

- Docker with Compose support
- `uv`
- Access to the configured Databricks SQL warehouse
- A working Databricks CLI profile, or a short-lived personal access token
- Access to the `databricks-gte-large-en` serving endpoint

Python 3.12 and all project dependencies are managed by `uv`.

## Configure

From this directory:

```bash
cp .env.example .env
```

Fill in the local Neo4j password and Databricks settings. The preferred local
Databricks path is an existing CLI profile:

```dotenv
DATABRICKS_HOST=https://dbc-example.cloud.databricks.com
DATABRICKS_PROFILE=your-profile
DATABRICKS_WAREHOUSE_ID=your-warehouse-id
```

The ingest runner uses the Databricks SDK to obtain an OAuth bearer token from
that profile. As a fallback, set `DATABRICKS_TOKEN` and either provide
`DATABRICKS_SERVER_HOSTNAME` plus `DATABRICKS_HTTP_PATH`, or keep `DATABRICKS_HOST`
plus `DATABRICKS_WAREHOUSE_ID` so the runner can derive them. Do not commit the
resulting `.env`.

Embedding credentials are not required in Phase 2. They are deferred until
embedding-backed retrieval is enabled in Phase 3. The provider and endpoint are
already selected and smoke-tested through the same Databricks profile:

```dotenv
EMBEDDING_MODEL=databricks/databricks-gte-large-en
```

## Install and ingest

```bash
make install
make validate-embeddings
make ingest
```

Run `make neo4j-up` before ingestion only when `.env` targets the local
loopback instance. For a dedicated remote store, set
`NEOCARTA_ALLOW_REMOTE_STORE=true` and do not start the Compose service.

`make ingest` runs the installed `finance-semantic-ingest` command with
`value_sample_limit=0`. It loads the configured catalog and schema, writes only
metadata, and records the Neocarta graph version.

## Validate

```bash
make validate
make validate-embeddings
make validate-mcp
make lint
make test
```

`make validate` checks node and relationship counts, required uniqueness
constraints, online indexes, the configured catalog and schema, and the absence
of both `Value` nodes and `HAS_VALUE` relationships.

`make validate-mcp` launches the real Neocarta stdio server, lists its tools,
and proves both catalog and full-text retrieval with `gold_accounts` and
`identity_cluster_id`. It does not call an embedding provider.

`make validate-embeddings` makes one non-persistent request to the configured
Databricks endpoint and verifies that it returns a non-empty vector. The current
endpoint returns 1,024 dimensions.

To run the server for an MCP client:

```bash
make mcp
```

Use the full command path in client configuration so the client does not depend
on its current directory:

```json
{
  "command": "uv",
  "args": [
    "--directory",
    "/Users/ryanknight/projects/databricks/graph-on-databricks/finance-genie/semantic-investigation-copilot",
    "run",
    "finance-semantic-mcp"
  ]
}
```

## Persistence and clean rebuild

For the local Compose store, ordinary shutdown preserves the semantic store:

```bash
make neo4j-down
make neo4j-up
make validate
```

Neocarta schema ingestion is additive. When source metadata changes, remove the
local prototype volume and ingest from a clean store. The following procedure
deletes only the dedicated local `finance-neocarta-data` volume:

```bash
docker compose --env-file .env down --volumes
make neo4j-up
make ingest
make validate
make validate-mcp
```

For a remote store, do not use the Compose cleanup command. Provision a fresh
dedicated database or explicitly clear only the Neocarta metadata graph through
an approved remote maintenance procedure.

## Versioned artifacts

- `src/` contains the installable Python command modules.
- `mappings/semantic-mappings.json` contains the five verified business concept
  mappings.
- `mappings/graph-asset-representation.json` records the selected operational
  graph metadata adapter.
- `validation/phase-1-validation.json` records live source validation.
- `validation/phase-2-validation.json` records runtime, store, persistence, and
  MCP acceptance evidence.

The curated mappings are versioned inputs. The Neo4j volume is rebuildable
runtime state and is not a source artifact.

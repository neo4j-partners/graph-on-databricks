# Semantic Investigation Copilot

This directory contains the isolated Neocarta prototype for the Finance Genie
semantic investigation demo described in
[`../work-proposals/finance-demo.md`](../work-proposals/finance-demo.md).

The Phase 2 runtime ingests metadata for one Unity Catalog schema into a
dedicated local Neo4j instance. It does not read or store source row values.
Neocarta then exposes the catalog through a stdio MCP server with catalog and
full-text retrieval tools.

## Runtime boundary

- `semantic-investigation-copilot/.env` is the one local source of runtime
  configuration. It is git-ignored and loaded explicitly by every runner.
- `.env.example` is the committed, redacted variable contract.
- The local Neo4j instance listens only on loopback ports `17474` and `17687`
  and persists to the `finance-neocarta-data` Docker volume.
- The Python write path refuses any `NEO4J_URI` whose host is not loopback.
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
embedding-backed retrieval is enabled in Phase 3.

## Install and ingest

```bash
make install
make neo4j-up
make ingest
```

`make ingest` runs `ingest_databricks.py` with `value_sample_limit=0`. It loads
the configured catalog and schema, writes only metadata, and records the
Neocarta graph version.

## Validate

```bash
make validate
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
    "python",
    "serve_mcp.py"
  ]
}
```

## Persistence and clean rebuild

Ordinary shutdown preserves the semantic store:

```bash
make neo4j-down
make neo4j-up
make validate
```

Neocarta schema ingestion is additive. When source metadata changes, remove the
prototype volume and ingest from a clean store. The following procedure deletes
only the dedicated local `finance-neocarta-data` volume:

```bash
docker compose --env-file .env down --volumes
make neo4j-up
make ingest
make validate
make validate-mcp
```

## Versioned artifacts

- `mappings/semantic-mappings.json` contains the five verified business concept
  mappings.
- `mappings/graph-asset-representation.json` records the selected operational
  graph metadata adapter.
- `validation/phase-1-validation.json` records live source validation.
- `validation/phase-2-validation.json` records runtime, store, persistence, and
  MCP acceptance evidence.

The curated mappings are versioned inputs. The Neo4j volume is rebuildable
runtime state and is not a source artifact.

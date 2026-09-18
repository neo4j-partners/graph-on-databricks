# Finance Genie Lakehouse Metadata Demo

This demo copies metadata from one configured Databricks Unity Catalog schema
and from the Finance Genie operational graph into a dedicated local Neo4j
store. NeoCarta is the metadata graph and its standard MCP server exposes
catalog and search tools for that graph.

The store holds metadata only. Ingest runs with `value_sample_limit=0` and the
schema-map extractor calls only Neo4j schema procedures, so no table row and no
operational property value is ever written into it. The store also does not
retain a project-specific semantic mapping, business-concept model, predicates,
or cross-source paths.

The Streamlit app on top of the store is a separate reader. It queries the SQL
warehouse and the operational graph directly, read-only, to show the financial
data the map describes and to run the queries that map grounds. See
[ui-v2.md](./ui-v2.md) for its design.

## Scope

The source is exactly one `DATABRICKS_CATALOG` and one `DATABRICKS_SCHEMA`.
Tables and views are searchable as NeoCarta `:Table` nodes. NeoCarta currently
does not retain Unity Catalog `table_type`, so the demo does not distinguish a
view from a base table.

Multi-schema ingestion, cross-catalog joins, generalized source namespacing,
incremental reconciliation, remote-store maintenance, and cross-source mapping
are out of scope. The Neo4j store is disposable runtime data.

Three connections are in scope. The two source connections are read-only; the
dedicated NeoCarta store is written only by metadata and embedding ingestion:

| Source | Read by | What it supplies |
|---|---|---|
| Databricks SQL warehouse | ingest, app | Catalog metadata, sample rows, query results |
| Finance Genie operational Neo4j | schema ingest, app | Schema metadata, and a bounded subgraph for the app |
| NeoCarta semantic store | ingest, validation, MCP server, app | The metadata graph and its search vectors |

The ingest commands read metadata alone. Only the app reads rows and graph
instances, and only for display and for the queries it runs.

## Setup

Create the local environment file and set the required credentials:

```bash
cp .env.example .env
make install
make neo4j-up
make ingest
make neo4j-schema-ingest
make validate
make validate-embeddings
make validate-neo4j-schema
make validate-mcp
```

`make ingest` uses `DatabricksSchemaConnector` with `value_sample_limit=0`, so
it reads only Unity Catalog `information_schema`. It then uses NeoCarta's
`LiteLLMEmbeddingsConnector` to embed table and column names, types, and
descriptions, store the vectors on their metadata nodes, and create the
corresponding vector indexes.
`make validate-mcp` starts the standard NeoCarta MCP server and checks schema
inventory plus table and column hybrid retrieval.

## Query the semantic map from the CLI

The `finance-semantic-query` command demonstrates the complete NeoCarta path:

1. Send the natural-language question to the separately running NeoCarta MCP server.
2. Retrieve matching table, column, and graph-schema context from the semantic map.
   NeoCarta uses hybrid vector and full-text search for tables and columns when
   the indexes created by ingestion are present.
3. Ask the configured Databricks Foundation Model endpoint to generate SQL using
   only that retrieved context.
4. Stop if the generated query declares an identifier that NeoCarta did not
   retrieve.
5. Execute the grounded SQL through `databricks api` and print the returned rows.

Build and validate the semantic store first, and configure the Databricks CLI
profile named by `DATABRICKS_PROFILE` in `.env`. The profile needs `CAN USE` on
the configured SQL warehouse and `SELECT` on the configured catalog and schema.
The command also requires the `LLM_ENDPOINT_NAME` configured in `.env`.

Start NeoCarta in a separate terminal and leave it running for the duration of
your queries:

```bash
make mcp
```

`make mcp` runs the server with MCP's streamable HTTP transport, bound only to
`127.0.0.1` at `http://127.0.0.1:8000/mcp`. It is deliberately separate from
the query process: stdio MCP is point-to-point, so a server left running over
stdio cannot be shared by a later CLI invocation. `make validate-mcp` still
launches a temporary stdio server for its integration check.

Stop the persistent server with `make mcp-stop`. The target only stops a
streamable HTTP `finance-semantic-mcp` process and refuses to stop an unrelated
program that happens to use port 8000.

### CLI examples

All CLI section headings, tool names, and pass/fail markers use ANSI colors.
Color is always enabled and requires no option.

Run the built-in semantic-layer showcase with no question:

```bash
uv run finance-semantic-query
```

The showcase runs three retrieval tests before the end-to-end lakehouse query:

1. Literal table and column identifiers exercise the full-text signal.
2. Conceptual business language exercises vector similarity.
3. Mixed conceptual and literal language exercises hybrid fusion.

NeoCarta registers the strongest available search strategy for each metadata
label. With both vector and full-text indexes present, the registered hybrid
tool supplies both branches, so the showcase reports the real MCP tool used
instead of claiming that separate full-text and vector tools were registered.

Run one question without the showcase when you want the shorter workflow:

```bash
uv run finance-semantic-query \
  "Which fraud rings share an identity cluster?"
```

To run the showcase tests followed by your own final question:

```bash
uv run finance-semantic-query --showcase \
  "Which accounts moved money to a high-risk account?"
```

The query client connects to `http://127.0.0.1:8000/mcp`. To use another
loopback port, start the server and point the client at the same URL:

```bash
make mcp MCP_PORT=8010
uv run finance-semantic-query \
  --mcp-url http://127.0.0.1:8010/mcp \
  "Which fraud rings share an identity cluster?"
```

Stop a custom-port server with `make mcp-stop MCP_PORT=8010`.

If the MCP server is not reachable, the query exits with status 2 and prints
the server URL plus the `make mcp` recovery command. It does not start an
embedded NeoCarta process automatically.

Override the `.env` profile for one invocation when needed:

```bash
uv run finance-semantic-query \
  --profile my-workspace-profile \
  "Which accounts moved money to a high-risk account?"
```

The command prints the tables and columns returned by MCP, the generated SQL,
the identifier grounding trace, and up to 10 result rows. Databricks CLI
authentication is reused for the Statement Execution API call; no token is
written to disk by the command. For this command, the selected profile takes
precedence over the optional `DATABRICKS_TOKEN` fallback so model generation
and SQL execution use the same identity. Keep the configured warehouse
identity read-only because generated-query safety is enforced by permissions,
not by SQL string inspection. Grounding verifies that identifiers came from
NeoCarta; it does not prove that the generated SQL is logically correct, so the
command always prints the SQL before it executes it.

Set `DATABRICKS_INGEST_GOVERNED_TAGS=true` only when the source uses governed
tags and the configured identity can list Databricks tag policies. This adds
NeoCarta governance-tag definitions; direct object-tag assignments remain an
upstream NeoCarta connector enhancement.

## Operational Neo4j schema map

`make neo4j-schema-ingest` reads the operational Neo4j connection from the
parent Finance Genie `.env` and writes a minimal, source-derived map to the
dedicated semantic store configured in this directory's `.env`. It records
source-reported label sets, relationship types, reported property names and
types, and the statistics-based relationship endpoints available from Neo4j.
The schema-ingest command never reads operational node, relationship, or
property values.

The source identity needs access to `db.labels`, `db.relationshipTypes`,
`db.schema.nodeTypeProperties`, and `db.schema.relTypeProperties`.
`db.schema.visualization` is optional: if it is unavailable, the map is still
created without endpoint edges and records that limitation. Neo4j documents
that visualization endpoints are statistics-based and can include possible
rather than observed combinations.

Use `make neo4j-schema-context` to print the persisted map. Use
`make validate-neo4j-schema` to compare it with a fresh metadata-only source
extraction. The schema-ingest command replaces only its own source-scoped map,
so it is safe to rerun against the dedicated semantic store.

## App

`ui-v2.md` specifies a three-page Streamlit app over the built store, and it
is implemented. Run it with `make app`.

| Group | Page | Shows |
|---|---|---|
| Data and its map | Lakehouse | Live sample rows for a selected table, and the same table traced in the NeoCarta `Database` / `Schema` / `Table` / `Column` map, on one screen driven by one selector |
| Data and its map | Operational graph | A bounded subgraph around a selected account, coloured by `risk_score`, and the same label traced in the NeoCarta `Node` / `Relationship` / `Property` map |
| Ask | Ask | The MCP retrieval trace, the SQL and Cypher built from exactly what it retrieved, and the results of running them |

Each data page shows the real data and the map that describes it on one
screen. The two systems come back together on Ask, where one question
retrieves both halves of the map and queries both sources.

The app executes generated queries, so read-only is enforced at the connection
and never by inspecting the generated string. The warehouse principal holds
`SELECT` on the one configured schema. The operational graph is reached by a
read-only Neo4j user through read transactions, so a write clause fails at the
server. Every sample query carries a `LIMIT`, and every rendered subgraph
carries a depth and node cap.

`config.assert_semantic_store_target` and
`config.assert_no_operational_graph_nodes` still guard the store target before
any connection. They keep the operational graph from being mistaken for the
metadata store.

## Rebuild

NeoCarta's schema loader is additive. When Unity Catalog metadata changes,
rebuild the dedicated local store instead of re-ingesting into it:

```bash
docker compose --env-file .env down --volumes
make neo4j-up
make ingest
make neo4j-schema-ingest
make validate
make validate-embeddings
make validate-mcp
```

This removes only the `finance-neocarta-data` Docker volume. Do not use this
command against a remote store or an operational graph.

## Embeddings

`make ingest` creates and stores embeddings from each table or column's name,
type, and description. Blank optional fields are omitted, so metadata without a
description is still searchable by vector. NeoCarta skips nodes that already
have an `embedding`, so rerunning the step backfills missing vectors without
recomputing existing ones. To run that backfill without repeating Unity Catalog
ingestion, use:

```bash
make embeddings
make validate-embeddings
```

`make validate-embeddings` probes the configured Databricks embedding endpoint,
then verifies complete stored-vector coverage, vector dimensions, and online
Neo4j indexes. The same `EMBEDDING_MODEL` is used by the NeoCarta MCP server to
embed queries. If the model changes to one with a different vector dimension,
rebuild the disposable semantic store so the stored vectors and indexes are
created consistently.

## Future NeoCarta enhancement

If consumers need to distinguish views from base tables, add a
backwards-compatible `table_type` property to NeoCarta's core `Table` model,
preserve the existing Unity Catalog `tables.table_type` value through the
Databricks transformer and loader, and return it from the standard table-context
tools. A property is preferable to a separate `:View` label because both assets
share the same containment and column model.

# Semantic Investigation Copilot

This project copies the metadata for one Databricks Unity Catalog schema into a
separate Neo4j database. It then exposes that metadata through a local stdio
MCP server. The server retrieves curated business concepts and their linked
Databricks and operational Neo4j schema representations.

The project stores schema metadata only. It does not read or store source table
rows, customer data, account data, phone numbers, addresses, or transfer values.

Neocarta provides the schema connector and the MCP server. The project pins
Neocarta `0.8.1` to Git commit
`ba6bf7945bf9c60640c664a03ccc26d0013996bf`. During ingestion, its
`DatabricksSchemaConnector` writes Unity Catalog metadata to Neo4j. During MCP
use, its stdio server provides the catalog tools plus the demo-owned
`get_business_concept_context` vector-retrieval tool.

## Architecture

```text
+---------------------------+
| Finance Genie             |
| make demo                 |
+-------------+-------------+
              |
              | creates source tables
              v
+---------------------------+
| Databricks SQL warehouse  |
| one Unity Catalog schema  |
+-------------+-------------+
              |
              | schema metadata only
              v
+---------------------------+        uses
| finance-semantic-ingest   +------------------------+
|                            |                        |
+-------------+-------------+                        v
              |                          +---------------------------+
              |                          | Neocarta 0.8.1            |
              |                          | pinned Git revision       |
              |                          | reproducible locked source |
              |                          | DatabricksSchemaConnector  |
              |                          | and stdio MCP server       |
              |                          +-------------+-------------+
              v                                        |
+---------------------------+                          |
| Dedicated Neo4j store     |<-------------------------+
| catalog, glossary, graph  |       metadata writes
| schema, and embeddings    |
+-------------+-------------+
              |
              | catalog, full-text, and vector search
              v
+---------------------------+        serves
| finance-semantic-mcp      +------------------------> MCP client
+---------------------------+
```

## Summary

- **Purpose:** Give an MCP client a searchable catalog for one Finance Genie
  schema.
- **Source:** A Databricks SQL warehouse and the catalog and schema named in
  this project's `.env` file.
- **Store:** A dedicated Neo4j database that contains catalog, glossary,
  lakehouse schema, graph-schema, mapping, and embedding metadata.
- **Search:** MCP tools expose catalog lookup and vector retrieval for the five
  curated business concepts.
- **Boundary:** The project rejects a store that contains core Finance Genie
  operational labels. It also rejects remote stores until you explicitly
  approve a dedicated remote metadata store.
- **Demo:** `finance-semantic-demo` retrieves shared identity, prepares fixed
  read-only SQL and Cypher, and shows the known synthetic eight-account fixture.

## Quick start

There are two separate flows. **Ingestion** builds or refreshes the semantic
metadata store. **Retrieval** lets an MCP-capable agent search that already
ingested store. Run ingestion once before retrieval, and rerun it only when the
configured Unity Catalog schema or the versioned semantic mappings change.

### 1. Build the semantic metadata store

The configured Finance Genie tables must exist before ingestion. If they do not,
complete the [parent setup](../README.md) from the `finance-genie` directory:

```bash
make demo
```

Then configure and ingest this project:

```bash
cd semantic-investigation-copilot
cp .env.example .env
# Edit .env with your dedicated metadata-store and Databricks settings.
make install
make neo4j-up
make ingest
make validate
make validate-graph
```

This creates the dedicated Neo4j metadata store, copies only the configured
Unity Catalog schema metadata, loads the reviewed mappings, and creates the
business-concept embeddings. It does not expose a service for an agent yet.

### 2. Let an agent retrieve semantic context through MCP

First verify the installed server against the ingested store:

```bash
make validate-mcp
```

Then add the following server definition to the MCP configuration of an agent
running on this computer. Replace the path with your clone path:

```json
{
  "mcpServers": {
    "finance-semantic": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/finance-genie/semantic-investigation-copilot",
        "run",
        "finance-semantic-mcp"
      ]
    }
  }
}
```

Restart or reload the agent after saving its configuration. The agent launches
the stdio server when it needs it; do not start `make mcp` separately for an
agent that uses this configuration. Ask the agent to use
`get_business_concept_context` for a business phrase such as `shared identity`,
or use the catalog and full-text tools to inspect the configured schema.

The MCP server retrieves semantic metadata and the reviewed Databricks/Neo4j
schema mappings. It does **not** query Finance Genie table rows or the
operational graph. An agent that needs to execute the SQL or Cypher suggested by
the semantic context needs separate, explicitly configured data-access tools.

This stdio configuration is the right setup for a local demo or a local desktop
agent. It is not a network endpoint for a hosted agent. A production deployment
would need a separately operated MCP transport, service identity, secret
management, and authorization policy; this project does not provide those.

## Requirements

- **Docker Compose:** Runs the local dedicated Neo4j metadata store.
- **uv:** Installs and runs the Python project.
- **Databricks access:** Connects to the configured SQL warehouse and reads its
  schema metadata.
- **Databricks profile or token:** Authenticates the SQL connection. A CLI
  profile is the normal local option.
- **Embedding endpoint access:** Generates business-concept embeddings during
  ingestion and supports vector retrieval. A separate command checks the
  endpoint directly.
- **Git access during installation:** Resolves the pinned Neocarta revision on
  the first dependency installation.

Python 3.12 is managed by `uv` with the project dependencies.

## Detailed walkthrough

### Ingestion path

Complete sections 1 through 6 in order to build the semantic metadata store.
They are the only steps that write schema metadata or embeddings to Neo4j.

#### 1. Prepare the Finance Genie source data

The semantic store needs tables that already exist in Databricks. The parent
project creates the shared Finance Genie environment and its demo data.

```bash
cd finance-genie
cp .env.sample .env
# Add your Databricks and Neo4j settings to .env.
make demo
```

Use the [parent README](../README.md) for the required values and the full
shared-environment setup.

#### 2. Create this project's configuration

This project uses its own `.env` file. Each command loads only the supported
connection variables from this file, rejects unknown keys, and clears optional
connection values that exist only in the surrounding shell.

```bash
cd semantic-investigation-copilot
cp .env.example .env
```

Set the following values in `.env`:

- **`NEO4J_URI`:** The dedicated metadata-store address. The default local
  address is `bolt://127.0.0.1:17687`.
- **`NEO4J_USERNAME` and `NEO4J_PASSWORD`:** The credentials for that dedicated
  store.
- **`NEO4J_DATABASE`:** The Neo4j database that holds the metadata.
- **`DATABRICKS_HOST`:** Your Databricks workspace URL.
- **`DATABRICKS_PROFILE`:** Your Databricks CLI profile name. This is the
  preferred local authentication method.
- **`DATABRICKS_WAREHOUSE_ID`:** The SQL warehouse that exposes the source
  schema.
- **`DATABRICKS_CATALOG` and `DATABRICKS_SCHEMA`:** The one Unity Catalog
  schema to copy into the metadata store.
- **`EMBEDDING_MODEL`:** The Databricks embedding endpoint used during ingest
  and retrieval. The default is `databricks/databricks-gte-large-en`.

You can set `DATABRICKS_SERVER_HOSTNAME` and `DATABRICKS_HTTP_PATH` instead of
deriving them from the workspace URL and warehouse ID. You can also set
`DATABRICKS_TOKEN` when a CLI profile is unavailable.

Keep `.env` local. It contains credentials and is ignored by Git.

#### 3. Choose a safe Neo4j store

The default Compose service starts a dedicated Neo4j instance. It listens only
on this computer:

- **Browser port:** `17474`
- **Bolt port:** `17687`
- **Docker volume:** `finance-neocarta-data`

Start the local store:

```bash
make neo4j-up
```

The project allows a remote store only when it is a dedicated metadata store.
Set `NEOCARTA_ALLOW_REMOTE_STORE=true` only after you confirm that condition.
Do not point this project at the Finance Genie operational graph. The commands
check for `Account`, `Customer`, `Phone`, and `Address` labels and stop when
they find them.

Do not run `make neo4j-up` when `.env` points to a dedicated remote store.

#### 4. Install the project

Install the Python dependencies and the pinned Neocarta dependency:

```bash
make install
```

The lockfile resolves Neocarta from its Git repository at the exact revision in
`pyproject.toml`. The runtime does not depend on the state of a local Neocarta
checkout.

#### 5. Build the semantic metadata graph

Run the ingest command after the local store is ready and the Databricks schema
exists:

```bash
make ingest
```

The command copies one catalog and schema into Neo4j, loads the versioned
Neocarta glossary CSVs, creates explicit lakehouse and graph-schema mappings,
and embeds the five business concepts. It sets `value_sample_limit=0`, so it
does not copy row values.

Ingestion adds metadata to the current store. Use a clean local store when the
source schema changes and you need an exact rebuild.

#### 6. Validate the metadata store

Check the result after ingestion:

```bash
make validate
make validate-graph
```

These commands confirm all of the following:

- **Required metadata:** The exact base database, schema, table, column, and
  relationship counts match the validation contract.
- **Value boundary:** No `Value` nodes or `HAS_VALUE` relationships exist.
- **Target schema:** The configured catalog and schema contain the expected 17
  Finance Genie tables and `gold_accounts.identity_cluster_id`.
- **Database health:** Every expected index has the required type and online
  state, and every expected node-key constraint targets the `id` property.
- **Store isolation:** The database does not contain the protected operational
  labels.
- **Semantic graph:** The exact glossary, mapping, graph-asset, relationship,
  embedding, and index counts match the semantic-graph contract.

After a successful check, `make record-graph` refreshes the corresponding
versioned evidence file.

### Retrieval path: validate and connect an agent

The remaining retrieval steps use the existing metadata store. They do not
ingest source tables or grant an agent access to source data.

#### 7. Check the embedding endpoint

Run this command when you want to confirm endpoint access:

```bash
make validate-embeddings
```

The command sends one fixed text string to the configured Databricks embedding
endpoint. It reports the vector count and dimensions. It does not save the text
or vector.

#### 8. Validate the MCP server

Run the MCP check after ingestion:

```bash
make validate-mcp
```

This command starts the real stdio server and checks that it can:

- list the expected MCP tools,
- list only the configured catalog and schema,
- return the complete catalog-qualified 17-table schema,
- find `gold_accounts` through catalog lookup and table full-text search,
- find `identity_cluster_id` through column full-text search, and
- retrieve `shared_identity` first through the 1,024-dimensional business-term
  vector index with both system mappings attached.

The business-concept check calls the configured embedding provider once.

#### 9. Optionally run the focused retrieval demo

```bash
make demo
make validate-demo
```

The demo performs live semantic retrieval, then prints fixed parameterized SQL
and Cypher examples without executing them. The validator executes those two
prepared read-only checks and requires the same eight accounts in identity
cluster `367` from both source systems.

After successful checks, `make record-demo` refreshes the prepared trace and
`make record-demo-validation` refreshes the executed cross-source evidence.

#### 10. Configure an agent to use the MCP server

The MCP server is a local stdio process. An MCP client, such as a desktop agent
running on this computer, should start and stop it. Do not run `make mcp` in a
separate terminal for that client; it will wait for MCP messages on standard
input and does not provide an HTTP URL or interactive shell.

Add this server definition to the agent's MCP configuration, replacing the
project path with your local clone path:

```json
{
  "mcpServers": {
    "finance-semantic": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/finance-genie/semantic-investigation-copilot",
        "run",
        "finance-semantic-mcp"
      ]
    }
  }
}
```

The server loads its configuration from this project's `.env`; do not duplicate
credentials in the agent configuration. Reload the agent, then have it call
`get_business_concept_context` for a concept such as `shared identity`, or use
the catalog tools to inspect schema metadata. The response is semantic context
only. To execute any retrieved SQL or Cypher, the agent must have separate,
appropriately authorized tools for Databricks or the operational Neo4j graph.

This stdio configuration is for a local agent. A hosted agent needs an MCP
service with a production transport plus managed identity, secrets, and
authorization; this project does not deploy that service.

For manual testing with an MCP-capable inspector or test client, start the
stdio process with:

```bash
make mcp
```

### Maintenance and development

#### 11. Revalidate the source mappings

The source-mapping validator reads the live Unity Catalog schema and the
operational Finance Genie graph. It does not change either system. Databricks
settings come from this project's `.env`; operational Neo4j settings come from
the parent `finance-genie/.env` used by the enrichment pipeline.

```bash
make validate-sources
```

The command verifies every table, column, join, predicate, graph label,
relationship type, property, and path claimed by
`mappings/semantic-mappings.json`. Use the recording target only when the live
checks pass and the versioned evidence needs to be refreshed:

```bash
make record-sources
```

This replaces `validation/source-mapping-validation.json` with the observed types,
nullability, counts, fixture IDs, mapping digest, and replay commands. The
recording target first runs the enrichment pipeline's nine read-only GDS and
KYC checks, so a refreshed artifact cannot bypass that acceptance gate.

#### 12. Run code checks

Run the local tests and formatting checks before changing this project:

```bash
make check
```

The check target runs formatting and lint checks followed by tests for
configuration, store isolation, semantic loading, retrieval, source validation,
and the prepared demo contract.

#### 13. Stop, restart, or rebuild the local store

Stop the local store without removing its data:

```bash
make neo4j-down
```

Start it again and verify the saved metadata:

```bash
make neo4j-up
make validate
```

Rebuild the local store when source metadata changes. This command removes only
the dedicated `finance-neocarta-data` Docker volume. It deletes the metadata
stored in that local volume.

```bash
docker compose --env-file .env down --volumes
make neo4j-up
make ingest
make validate
make validate-graph
make validate-mcp
make validate-demo
```

For a remote store, create a fresh dedicated database or use an approved
maintenance procedure. Do not use the local Compose cleanup command against a
remote store.

## Versioned reference files

- **`src/`:** The installable commands for ingestion, validation, and the MCP
  server.
- **`mappings/semantic-mappings.json`:** Five reviewed business-concept
  mappings for shared identity, KYC review, transfer exposure, fraud-ring
  candidates, and high risk.
- **`mappings/graph-asset-representation.json`:** The implemented metadata
  model for operational graph assets.
- **`mappings/*.csv`:** Versioned Neocarta glossary and table/column tag inputs.
- **`validation/`:** Recorded evidence from source and runtime checks.

The JSON mappings and CSVs are versioned source inputs. The Neo4j Docker volume
is rebuildable runtime data; it contains metadata and embeddings, not source
records.

## Inspect the Finance Semantic Layer in Neo4j Console

Connect Neo4j Browser or Neo4j Console to the dedicated Finance semantic-store
database, then run these read-only Cypher queries. The store contains metadata
only. It does not contain Finance Genie source rows or operational graph
entities.

### Count semantic-layer nodes by label

```cypher
MATCH (node)
UNWIND labels(node) AS label
RETURN label, count(*) AS node_count
ORDER BY node_count DESC, label
```

### Visualize the Unity Catalog hierarchy

```cypher
MATCH (database:Database)-[has_schema:HAS_SCHEMA]->(schema:Schema)
      -[has_table:HAS_TABLE]->(table:Table)
WHERE database.name = 'graph-on-databricks'
  AND schema.name = 'graph-enriched-schema'
RETURN database, has_schema, schema, has_table, table
LIMIT 25
```

### Inspect the `gold_accounts` table and its columns

```cypher
MATCH (:Database {name: 'graph-on-databricks'})-[:HAS_SCHEMA]
      ->(:Schema {name: 'graph-enriched-schema'})-[:HAS_TABLE]
      ->(table:Table {name: 'gold_accounts'})-[:HAS_COLUMN]->(column:Column)
RETURN table.name AS table,
       column.name AS column,
       column.type AS data_type,
       column.nullable AS nullable,
       column.description AS description
ORDER BY column.name
```

### Follow the `shared_identity` concept to its mapped assets

```cypher
MATCH (concept:BusinessConcept {id: 'shared_identity'})
OPTIONAL MATCH (concept)-[mapping:MAPS_TO_TABLE|MAPS_TO_COLUMN|MAPS_TO_GRAPH_ASSET]->(asset)
RETURN concept.name AS concept,
       type(mapping) AS mapping_type,
       labels(asset) AS asset_labels,
       asset.name AS asset_name,
       asset.owner_name AS property_owner
ORDER BY mapping_type, asset_name
```

### Visualize the same concept mapping as a graph

```cypher
MATCH path = (concept:BusinessConcept {id: 'shared_identity'})
             -[:MAPS_TO_TABLE|MAPS_TO_COLUMN|MAPS_TO_GRAPH_ASSET]->(asset)
RETURN path
```

### Inspect the metadata representation of the operational graph

```cypher
MATCH (database:GraphDatabase)-[:HAS_NODE_LABEL]->(label:GraphNodeLabel)
OPTIONAL MATCH (label)-[:HAS_PROPERTY]->(property:GraphProperty)
RETURN database.name AS graph_database,
       label.name AS node_label,
       collect(property.name) AS properties
ORDER BY node_label
```

### Confirm search indexes are online

```cypher
SHOW INDEXES
YIELD name, type, state, labelsOrTypes, properties
WHERE name IN [
  'businessterm_full_text_index',
  'businessterm_vector_index',
  'table_full_text_index',
  'column_full_text_index'
]
RETURN name, type, state, labelsOrTypes, properties
ORDER BY name
```

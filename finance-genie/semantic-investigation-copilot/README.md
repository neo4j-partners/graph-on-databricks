# Finance Genie Lakehouse Metadata Demo

This demo uses NeoCarta to build a local semantic map for one Databricks schema and the Finance Genie Neo4j graph.

- **Semantic map:** A searchable map of tables, columns, node labels, relationship types, and property names.
- **Metadata only:** The map stores source structure and descriptions. It does not copy table rows or operational graph property values.
- **MCP server:** A local server that lets the query command find relevant context in the semantic map.
- **Grounded SQL:** SQL created from the metadata returned by MCP. The command checks every SQL identifier against that metadata before it runs the query.

## Quick Start Setup

Set up the local semantic store once before you run the demo.

### 1. Set configuration

```bash
cd semantic-investigation-copilot
cp .env.example .env
```

Set these values in `.env`:

- **Local semantic store:** Set `NEO4J_PASSWORD` for the local Neo4j container.
- **Databricks source:** Set `DATABRICKS_HOST`, `DATABRICKS_PROFILE`, `DATABRICKS_WAREHOUSE_ID`, `DATABRICKS_CATALOG`, and `DATABRICKS_SCHEMA`.
- **Databricks models:** Set `EMBEDDING_MODEL` and `LLM_ENDPOINT_NAME` to endpoints available in your workspace.

The parent `finance-genie/.env` must also contain the Finance Genie operational Neo4j connection. `make neo4j-schema-ingest` reads that connection to build the graph schema map.

### 2. Build and check the semantic store

```bash
make install
make neo4j-up
make ingest
make neo4j-schema-ingest
make validate
make validate-embeddings
make validate-neo4j-schema
make validate-mcp
```

- **`make ingest`:** Reads Unity Catalog metadata and creates table and column search vectors.
- **`make neo4j-schema-ingest`:** Reads the Finance Genie graph schema and adds it to the semantic map.
- **Validation commands:** Check the local store, vectors, graph schema map, and MCP search.

## Demo Walkthrough

This is the easiest demo flow after setup.

### 1. Start the MCP server

Open one terminal and leave this command running:

```bash
make mcp
```

The server listens at `http://127.0.0.1:8000/mcp`.

### 2. Run the showcase

Open a second terminal in `semantic-investigation-copilot`. Run:

```bash
uv run finance-semantic-query
```

The showcase tests three search styles, then runs one complete Lakehouse question.

- **Literal search:** Finds exact table and column names.
- **Conceptual search:** Finds related business terms.
- **Hybrid search:** Combines literal and conceptual search.

### 3. Try a question

Run one question without the showcase:

```bash
uv run finance-semantic-query \
  "Which fraud rings share an identity cluster?"
```

Run the showcase, then your own question:

```bash
uv run finance-semantic-query --showcase \
  "Which accounts moved money to a high-risk account?"
```

Stop the server when you finish:

```bash
make mcp-stop
```

## Query the Semantic Map from the CLI

The `finance-semantic-query` command demonstrates the complete NeoCarta path:

1. **Send the question:** The command sends your question to the local MCP server.
2. **Find context:** MCP returns matching tables, columns, and graph schema metadata.
3. **Create SQL:** The configured Databricks model creates SQL from that returned context.
4. **Check SQL:** The command stops when the SQL uses an identifier that MCP did not return.
5. **Run the query:** The command runs the SQL through Databricks and prints the results.

The command uses the Databricks CLI profile from `DATABRICKS_PROFILE`. That profile needs permission to use the SQL warehouse and read the configured catalog and schema.

## Optional Commands

- **Run the app:** `make app`
- **Show the graph schema map:** `make neo4j-schema-context`
- **Rebuild the local store:** Run `docker compose --env-file .env down --volumes`, then repeat the setup commands. This removes the local `finance-neocarta-data` Docker volume.

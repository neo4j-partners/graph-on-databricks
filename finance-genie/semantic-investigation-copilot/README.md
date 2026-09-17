# Finance Genie Lakehouse Metadata Demo

This demo copies metadata from one configured Databricks Unity Catalog schema
into a dedicated local Neo4j store. NeoCarta is the metadata graph and its
standard MCP server exposes catalog and search tools for that graph.

The demo reads only Unity Catalog metadata and operational Neo4j schema
metadata. It does not read table rows or operational graph values, and it does
not retain a project-specific semantic mapping, business-concept model,
predicates, or cross-source paths.

## Scope

The source is exactly one `DATABRICKS_CATALOG` and one `DATABRICKS_SCHEMA`.
Tables and views are searchable as NeoCarta `:Table` nodes. NeoCarta currently
does not retain Unity Catalog `table_type`, so the demo does not distinguish a
view from a base table.

Multi-schema ingestion, cross-catalog joins, generalized source namespacing,
incremental reconciliation, remote-store maintenance, and cross-source mapping
are out of scope. The Neo4j store is disposable runtime data.

## Setup

Create the local environment file and set the required credentials:

```bash
cp .env.example .env
make install
make neo4j-up
make ingest
make neo4j-schema-ingest
make validate
make validate-neo4j-schema
make validate-mcp
```

`make ingest` uses `DatabricksSchemaConnector` with `value_sample_limit=0`, so
it reads only Unity Catalog `information_schema`. `make validate-mcp` starts the
standard NeoCarta MCP server and checks schema inventory plus table and column
full-text retrieval.

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
It never reads operational node, relationship, or property values.

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

## Optional embeddings

Catalog and full-text retrieval work directly from schema metadata. Run
`make validate-embeddings` only to verify the configured embedding endpoint;
embeddings are optional and are not written by the ingest command.

## Future NeoCarta enhancement

If consumers need to distinguish views from base tables, add a
backwards-compatible `table_type` property to NeoCarta's core `Table` model,
preserve the existing Unity Catalog `tables.table_type` value through the
Databricks transformer and loader, and return it from the standard table-context
tools. A property is preferable to a separate `:View` label because both assets
share the same containment and column model.

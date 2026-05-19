# Graph-Enriched Lakehouse

Graph enrichment connects Neo4j Graph Data Science to a Databricks Lakehouse as a silver-to-gold pipeline stage. The pipeline reads Silver tables from Unity Catalog, loads the records into Neo4j as a property graph, runs graph algorithms against the network, and writes the results back to the Gold layer as plain Delta columns. Genie, SQL warehouses, dashboards, and downstream ML read those columns without modification. The analytics stack stays unchanged. The catalog gains dimensions it could not carry before.

---

## Projects

### [Agentic Commerce](./agentic-commerce/README.md)

A Databricks-hosted agentic commerce example backed by Neo4j. The assistant uses a Neo4j product knowledge graph, GraphRAG retrieval, and graph-backed memory to search products, diagnose issues, remember customer preferences, and personalize recommendations. The project also includes a Databricks App demo client and deployment pipeline for Mosaic AI Model Serving.

Start here:

- [agentic-commerce/README.md](./agentic-commerce/README.md): project overview, setup, deployment, and validation.
- [agentic-commerce/docs/agentic-commerce.md](./agentic-commerce/docs/agentic-commerce.md): design narrative for GraphRAG plus agent memory.
- [agentic-commerce/demo-client/README.md](./agentic-commerce/demo-client/README.md): local and deployed demo client workflow.

### [Finance Genie](./finance-genie/README.md)

A fraud-surfacing demo for Databricks account teams and partners. Financial crime is a network problem: fraud rings operate as connected patterns across many accounts and transactions, and the individual event looks clean while the connected pattern does not. A high-level synthetic fraud dataset loads into Neo4j Aura as a property graph. PageRank, Louvain community detection, and Node Similarity run against the projection and write `risk_score`, `community_id`, and `similarity_score` back to the Gold layer as plain Delta columns: centrality, community membership, and structural similarity materialized where every Databricks tool can reach them.

The demo runs in two phases. The BEFORE space queries unenriched Silver tables: Genie handles standard BI questions cleanly, then falls short on structural-discovery questions because network topology does not exist in flat rows. The AFTER space queries the enriched Gold tables: portfolio composition by risk tier, cohort comparisons across community membership, operational workload estimates, and merchant-side analysis conditioned on structural membership. Questions that require no graph knowledge to read, over a catalog that did not carry those dimensions before the pipeline ran.

Start here:

- [finance-genie/README.md](./finance-genie/README.md): project overview and navigation.
- [finance-genie/ARCHITECTURE.md](./finance-genie/ARCHITECTURE.md): stage-by-stage pipeline reference, signal parameters, and what each GDS algorithm guarantees.
- [finance-genie/SCOPING_GUIDE.md](./finance-genie/SCOPING_GUIDE.md): where the pattern applies, dataset sizing, and production-scale calibration.
- [finance-genie/TALK_TRACK.md](./finance-genie/TALK_TRACK.md): one-slide field script for account teams and partner SEs.
- [finance-genie/automated/README.md](./finance-genie/automated/README.md): CLI-driven job runner, Genie non-determinism discussion, and automated validation.
- [finance-genie/workshop/README.md](./finance-genie/workshop/README.md): notebook sequence for live demo delivery.

---

## Neo4j + Databricks Integrations Showcased

- **Silver-to-Gold graph enrichment**: Neo4j Graph Data Science reads Silver tables from Unity Catalog, runs graph algorithms, and writes results back to the Gold layer as plain Delta columns.
- **Graph signals as Delta columns**: PageRank centrality, Louvain community membership, and Node Similarity scores materialized into Delta so Genie, SQL warehouses, dashboards, and ML read them without graph knowledge.
- **Neo4j Aura as a managed pipeline stage**: a hosted property graph slots between medallion layers with no change to the surrounding analytics stack.
- **Genie over graph-enriched tables**: natural-language BI against Gold tables that now carry network topology dimensions the flat catalog could not express.
- **GraphRAG retrieval on Databricks**: a Neo4j product knowledge graph backs GraphRAG search and personalized recommendations served through Mosaic AI Model Serving.
- **Graph-backed agent memory**: customer preferences and history persisted in Neo4j and read back by a Databricks-hosted agent.
- **Databricks Apps client**: a deployed demo client exercising the graph-backed serving endpoint end to end.

---

## Service Topology

How the Databricks services connect to Neo4j. Each hop is a service boundary, not an algorithm or a table.

### Enrichment pipeline (Gold tables)

```
        ┌──────────────────────────────────────────────────────────────────────────────────────┐
        │                            Fraud Analyst App Client                                    │
        └──────────────────────────────────────────────────────────────────────────────────────┘
                  │                                                                  │
                  │ reads Delta                                                      │ asks questions
                  ▼                                                                  ▼
                         Databricks Unity Catalog
            ┌────────────────────────────────────────────────┐       ┌──────────────────────┐
            │   Silver Delta tables        Gold Delta ────────┼─────► │  Databricks Genie    │
            └────────────────────────────────────────────────┘       │  SQL Warehouse       │
                  │ read                          ▲ write            │  Dashboards          │
                  ▼                                │                  └──────────────────────┘
        ┌──────────────────────┐        ┌──────────────────────┐
        │  Databricks Classic  │        │  Databricks Classic  │
        │   Compute (job)      │        │   Compute (job)      │
        └──────────────────────┘        └──────────────────────┘
                  │                                ▲
                  ▼                                │
        ┌──────────────────────┐        ┌──────────────────────┐
        │  Neo4j Spark         │        │  Neo4j Spark         │
        │  Connector (write)   │        │  Connector (read)    │
        └──────────────────────┘        └──────────────────────┘
                  │                                ▲
                  ▼                                │
            ┌────────────────────────────────────────────────┐
            │                Neo4j (Graph + GDS)              │
            └────────────────────────────────────────────────┘
```

- **Fraud Analyst App Client** sits on top and is the entry point. It reads Delta tables through Unity Catalog and asks questions through Databricks Genie, with no Neo4j connection of its own.
- **Databricks Classic Compute** runs the ingest and pull-back jobs. The Neo4j Spark Connector is a cluster library, so these jobs run on classic job clusters rather than serverless.
- **Neo4j Spark Connector** is the only bridge in and out of Neo4j. It writes the graph on the way in and reads enriched node properties on the way out.
- **Neo4j** holds the property graph and runs the graph algorithms. It is the system of record for structure.
- **Databricks Unity Catalog** governs both ends: Silver Delta tables in, Gold Delta tables out.
- **Databricks Genie**, SQL Warehouses, and dashboards sit off to the right and read the Gold Delta tables directly through Unity Catalog, with no Neo4j connection of their own.

### MCP-backed simple agent (live graph)

```
        Analyst ──► Databricks Supervisor Agent
                     (routes the question)
                              │
              ┌───────────────┴───────────────┐
              │ graph evidence                 │ silver-table BI
              ▼                                 ▼
    ┌──────────────────────┐        ┌──────────────────────┐
    │  Finance             │        │   Genie Space        │
    │  agent endpoint      │        │  (Unity Catalog      │
    │  (Model Serving)     │        │   Silver Delta)      │
    └──────────────────────┘        └──────────────────────┘
              │ Databricks MCP proxy            │
              ▼                                 │
    ┌──────────────────────┐                    │
    │  UC HTTP connection  │                    │
    │  (MCP enabled)       │                    │
    └──────────────────────┘                    │
              │ AgentCore gateway / Neo4j MCP   │
              ▼                                 │
    ┌──────────────────────┐                    │
    │  Neo4j (Graph + GDS) │                    │
    └──────────────────────┘                    │
              │                                 │
              └────────► Supervisor ◄───────────┘
                         synthesis
```

- **Databricks Supervisor Agent** is the entry point. It routes graph questions down the left branch and Silver-table business questions down the right branch.
- **Simple finance agent endpoint** is a Databricks Model Serving endpoint. It reaches Neo4j through the **Databricks MCP proxy**, never through a Spark Connector or Gold tables.
- **UC HTTP connection (MCP enabled)** is the governed Unity Catalog boundary that fronts the external MCP server.
- **AgentCore gateway / Neo4j MCP** is the bridge into Neo4j for this path, the MCP analog of the Spark Connector.
- **Neo4j** holds the property graph and the GDS evidence. It is queried live rather than precomputed into Delta.
- **BEFORE Genie Space** sits off to the right and reads Silver Delta through Unity Catalog, with no Neo4j connection of its own.
- **Supervisor synthesis** combines the graph rationale and the Silver-table business context into one answer.

### Agentic commerce agent (live graph + memory)

```
        ┌──────────────────────────────────────────────┐
        │      Databricks Apps Agentic Commerce Client   │
        └──────────────────────────────────────────────┘
                  │
                  ▼
        ┌───────────────────────┐        ┌──────────────────────┐
        │  Databricks Model     │ ─────► │  Foundation Model API │
        │  Serving endpoint     │        │  (Claude Sonnet)      │
        │  (MLflow CommerceChatAgent)  │ ─────► │  BGE Embeddings       │
        └───────────────────────┘        └──────────────────────┘
                  │ neo4j driver (live Cypher)
                  ▼
        ┌────────────────────────────────────────────────┐
        │       Neo4j (Knowledge Graph + Memory)          │
        └────────────────────────────────────────────────┘
                  ▲
                  │ Neo4j Spark Connector (bulk load)
        ┌──────────────────────┐
        │  Databricks Classic  │
        │   Compute (job)      │
        └──────────────────────┘
                  ▲
                  │ read
        ┌────────────────────────────────────────────────┐
        │     Databricks Unity Catalog — Delta tables     │
        └────────────────────────────────────────────────┘
```

- **Databricks Apps demo client** is the entry point. It calls the serving endpoint and never touches Neo4j directly.
- **Databricks Model Serving endpoint** hosts the LangGraph agent as an MLflow ChatAgent. It queries Neo4j live through the **neo4j Python driver**, not through a Spark Connector.
- **Foundation Model API** and **BGE Embeddings** sit off to the right. The endpoint calls them for reasoning and vector search, with no Neo4j connection of their own.
- **Neo4j** holds the product knowledge graph and the agent memory graph. It is queried live at request time.
- **Databricks Classic Compute** with the **Neo4j Spark Connector** runs once at build time to bulk-load the graph from Delta. The Spark Connector is a cluster library, so this runs on a classic job cluster.
- **Databricks Unity Catalog** governs the Delta tables the loader reads from.

# Graph-Enriched Lakehouse: Finance Genie

[Project website and slides](https://neo4j-partners.github.io/graph-on-databricks/)

Finance Genie shows what becomes possible when Neo4j GDS runs as a silver-to-gold
enrichment stage inside a Databricks Lakehouse. The demo has a before and an
after. The BEFORE space answers standard BI questions over flat Silver tables but
silently substitutes a different answer when asked about network structure such
as centrality and community membership. The AFTER space queries graph-derived columns
(`risk_score`, `community_id`, `similarity_score`) that GDS materialized back into
Gold, and answers a question class that did not exist in the Silver layer.

## Common Setup

Every subproject shares one environment file and one set of Databricks secrets,
defined once at the repo root.

1. **Create the shared `.env`:**

   ```bash
   cd finance-genie
   cp .env.sample .env
   # Edit .env: fill in Databricks, Neo4j, Genie, and MCP values.
   ```

2. **Provision Databricks secrets** from the same root env file:

   ```bash
   ./setup_secrets.sh --profile <databricks-profile>
   ```

   The setup writes separate secret scopes for separate runtime surfaces, so one
   operator workflow does not give every app access to every secret:

   | Scope | Used by | Contents |
   |---|---|---|
   | `neo4j-graph-engineering` | `enrichment-pipeline/` jobs and workshop notebooks | Neo4j URI, username, password, before/after Genie Space IDs |
   | `simple-finance-analyst` | `simple-finance-analyst` real backend | Neo4j URI, username, password, analyst Genie Space ID |
   | `mcp-neo4j-secrets` | `neo4j-mcp-demo` and MCP-backed agents | AgentCore OAuth gateway/client credentials, when `.mcp-credentials.json` is available |

3. **Upload data and create the base tables:**

   ```bash
   cd enrichment-pipeline
   ./upload_and_create_tables.sh
   ```

   The synthetic dataset is committed in `finance-genie/data/`, so you can browse
   the five CSVs and `ground_truth.json` directly. This step uploads them to the
   Unity Catalog Volume, applies `sql/schema.sql` to create the five base tables
   with column-level comments (the contract Genie reads), then loads the data via
   `INSERT OVERWRITE`. Requires `DATABRICKS_WAREHOUSE_ID` in `finance-genie/.env`.
   Regenerating the dataset is optional and covered in
   [enrichment-pipeline/README.md](./enrichment-pipeline/README.md).

Now pick a path below.

## Choose Your Path

| You want to... | Follow | Runnable assets |
|---|---|---|
| Show graph structure becoming reusable Databricks data products (enriched Gold columns) | **Path A: Graph-Enriched Lakehouse** | [enrichment-pipeline/](./enrichment-pipeline/README.md), [workshop/](./workshop/README.md) |
| Show live graph evidence retrieved through MCP by an agent, beside Genie | **Path B: MCP-Backed Simple Agent** | [simple-finance-agent/](./simple-finance-agent/README.md), [neo4j-mcp-demo/](./neo4j-mcp-demo/README.md) |

## Path A: Graph-Enriched Lakehouse

The original before/after demo path. Neo4j GDS runs as a silver-to-gold
enrichment stage, and Databricks Genie queries graph-derived features after they
have been materialized as ordinary Gold Delta columns.

```text
                     finance-genie/enrichment-pipeline
                  setup, jobs, validation, CI
                              |
                              v
+--------------------------------------------------------------------+
| Databricks Unity Catalog                                           |
| Silver tables: accounts, merchants, transactions, account_links,   |
| account_labels                                                     |
+-------------------------------+------------------------------------+
                                |
                                | Neo4j Spark Connector
                                v
+--------------------------------------------------------------------+
| Neo4j Aura                                                         |
| Property graph + GDS                                               |
| PageRank -> risk_score                                             |
| Louvain -> community_id                                            |
| Node Similarity -> similarity_score                                |
+-------------------------------+------------------------------------+
                                |
                                | pull enriched results
                                v
+--------------------------------------------------------------------+
| Databricks Unity Catalog                                           |
| Gold tables: gold_accounts, gold_account_similarity_pairs,         |
| gold_fraud_ring_communities                                        |
+-------------------------------+------------------------------------+
                                |
                                v
+--------------------------------------------------------------------+
| AFTER Genie Space, dashboards, SQL, ML                             |
| Queries graph-derived columns like normal warehouse fields          |
+--------------------------------------------------------------------+
```

How to run each piece:

- **Admin / CI setup** (data, tables, secrets, jobs, GDS, validation):
  [enrichment-pipeline/README.md](./enrichment-pipeline/README.md)
- **Hands-on notebooks** (the participant-facing walkthrough):
  [workshop/README.md](./workshop/README.md)
- **Presenter narrative** (talk track, questions, slides):
  [docs/demo-guide/](./docs/demo-guide/)

Use this path when the point is that graph structure can become reusable
Databricks data products. The graph evidence enters Databricks as stable Gold
columns that any downstream Databricks workflow can consume without calling Neo4j
at query time.

## Path B: MCP-Backed Simple Agent

The live graph-evidence path. Neo4j GDS still computes the structural evidence,
but the evidence is retrieved through MCP by a simple finance agent. A Databricks
Supervisor Agent can be configured manually to route graph questions to this
endpoint and Silver-table business questions to the BEFORE Genie Space.

```text
+--------------------------------------------------------------------+
| Analyst question                                                   |
+-------------------------------+------------------------------------+
                                |
                                v
+--------------------------------------------------------------------+
| Databricks Supervisor Agent                                        |
| Routes graph discovery first, business impact second               |
+---------------+------------------------------------+---------------+
                |                                    |
                | graph candidate retrieval          | silver-table analysis
                v                                    v
+------------------------------------+   +----------------------------+
| Simple finance agent endpoint      |   | BEFORE Genie Space          |
| finance-genie/simple-finance-agent |   | Silver/base Delta tables    |
| No Genie calls, no Gold dependency |   | accounts, merchants,        |
+---------------+--------------------+   | transactions, account_links |
                |                        +--------------+-------------+
                | Databricks MCP proxy                  |
                v                                       |
+------------------------------------+                  |
| UC HTTP connection with MCP enabled|                  |
| finance-genie/neo4j-mcp-demo       |                  |
+---------------+--------------------+                  |
                |                                       |
                | AgentCore gateway / Neo4j MCP         |
                v                                       |
+------------------------------------+                  |
| Neo4j Aura + GDS evidence          |                  |
| fraud-ring candidates, graph       |                  |
| rationale, account IDs             |                  |
+---------------+--------------------+                  |
                |                                       |
                +-------------------+-------------------+
                                    v
+--------------------------------------------------------------------+
| Supervisor synthesis                                               |
| Combines graph rationale with Silver-table business context         |
+--------------------------------------------------------------------+
```

How to run each piece:

- **Agent endpoint** (the deployable MCP-backed finance agent):
  [simple-finance-agent/README.md](./simple-finance-agent/README.md)
- **MCP connection it depends on** (UC HTTP connection, AgentCore gateway):
  [neo4j-mcp-demo/README.md](./neo4j-mcp-demo/README.md)

Use this path when the point is live graph tool access beside Genie, without
persisting graph-enriched Gold tables. This repo deploys the MCP-backed agent
endpoint; Supervisor Agent and Genie wiring are Databricks-side setup.

## Project Map

Finance Genie contains several related but separate projects. They share the same
core claim: relationship structure belongs in the Databricks analytical workflow,
either as graph-enriched Gold columns or as live graph evidence routed through an
agent.

| Directory | What it is | When to use |
|---|---|---|
| [`enrichment-pipeline/`](./enrichment-pipeline/README.md) | Admin and CI implementation of the Gold-table pipeline: generates data, uploads tables, configures secrets, provisions Genie Spaces, submits jobs, runs ingest and GDS, pulls Gold tables, validates output. | Preparing the shared environment before a workshop or demo, and unattended/regression runs. |
| [`workshop/`](./workshop/README.md) | Participant-facing notebooks that walk through the same enrichment idea interactively. | Running the demo hands-on on Databricks. |
| [`docs/demo-guide/`](./docs/demo-guide/) | Narrative and presenter collateral: before/after framing, recommended questions, speaker notes, slides. | Preparing the positioning and talk track. |
| [`neo4j-mcp-demo/`](./neo4j-mcp-demo/README.md) | The external MCP integration: AgentCore OAuth, UC HTTP connection with MCP, tool discovery, LangGraph agent, Model Serving endpoint. | Enabling live graph access through MCP. |
| [`simple-finance-agent/`](./simple-finance-agent/README.md) | The deployable graph-only MCP-backed finance agent endpoint. | Pairing with a Supervisor Agent that routes graph vs business questions. |
| [`simple-finance-analyst/`](./simple-finance-analyst/) | Flask web app for exploring fraud rings in Neo4j and analyzing via Genie. | A UI for analysts over the graph evidence. |
| [`graph-fraud-analyst/`](./graph-fraud-analyst/) | Full-stack React + FastAPI Fraud Signal Workbench (Search, Load, Analyze). | A production-style investigation workbench. |

Quick pointers:

- **Presenter prep:** [docs/demo-guide/prep-guide.md](./docs/demo-guide/prep-guide.md) for the story, questions, and slides.
- **Workshop participants:** [workshop/README.md](./workshop/README.md) for the notebook sequence and cluster prerequisites.
- **Demo owner / CI:** [enrichment-pipeline/README.md](./enrichment-pipeline/README.md) for data, tables, secrets, validation, and CLI commands.
- **MCP setup:** [neo4j-mcp-demo/README.md](./neo4j-mcp-demo/README.md) for the Databricks external MCP connection and validation.
- **Simple finance agent:** [simple-finance-agent/README.md](./simple-finance-agent/README.md) for endpoint deployment and Supervisor handoff.

## Further Reading

- [ARCHITECTURE.md](./ARCHITECTURE.md): design rationale, GDS algorithm choices, and integration patterns.
- [Full Finance Genie deck](https://neo4j-partners.github.io/graph-on-databricks/slides.html)
- [15-minute Finance Genie deck](https://neo4j-partners.github.io/graph-on-databricks/slides-15min.html)

# Graph-Enriched Lakehouse: Finance Genie

[Project website and slides](https://neo4j-partners.github.io/graph-on-databricks/)

Finance Genie shows what becomes possible when Neo4j GDS runs as a silver-to-gold
enrichment stage inside a Databricks Lakehouse. The demo has a before and an
after. The BEFORE space answers standard BI questions over flat Silver tables but
silently substitutes a different answer when asked about network structure such
as centrality and community membership. The AFTER space queries graph-derived columns
(`risk_score`, `community_id`, `similarity_score`) that GDS materialized back into
Gold, and answers a question class that did not exist in the Silver layer.

## Canonical Setup

One command establishes the shared Finance Genie environment. It prepares the
Silver lakehouse tables, Neo4j property graph and GDS results, Gold tables,
Databricks secret scope, and canonical BEFORE and AFTER Genie Spaces.

```bash
cd finance-genie
cp .env.sample .env
# Fill in Databricks workspace, compute, warehouse, and Aura credentials.
make demo
```

On its first run, `make demo` creates the two Genie Spaces and records their IDs
in the local, untracked `.env`. Later runs reconcile the same spaces. The
committed synthetic dataset is used by default; use `make data` only when you
deliberately want a new dataset.

`make demo` updates the shared UC tables and clears then reloads the configured
Neo4j graph. Run `make check` for the read-only Databricks, Neo4j, and data
preflight.

This setup deliberately does **not** deploy an optional product. The MCP agent
needs external OAuth credentials and a serving endpoint; the Fraud Signal
Workbench needs an app deployment and service-principal grants; the Virtual
Graph demo needs a Virtual Graph created in Aura. Use the project-specific
instructions only after the canonical environment is ready.

Now pick a path below.

## Choose Your Path

| You want to... | Follow | Runnable assets |
|---|---|---|
| Show graph structure becoming reusable Databricks data products (enriched Gold columns) | **Path A: Graph-Enriched Lakehouse** | [enrichment-pipeline/](./enrichment-pipeline/README.md), [workshop/](./workshop/README.md) |
| Show live graph evidence retrieved through MCP by an agent, beside Genie | **Path B: Neo4j MCP Graph Agent** | [neo4j-mcp-graph-agent/](./neo4j-mcp-graph-agent/README.md) |
| Give investigators a guided Search → Load → Analyze application | **Path C: Fraud Signal Workbench** | [fraud-signal-workbench/](./fraud-signal-workbench/README.md) |

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

- **Admin / CI setup** (the implementation behind `make demo`):
  [enrichment-pipeline/README.md](./enrichment-pipeline/README.md)
- **Hands-on notebooks** (the participant-facing walkthrough):
  [workshop/README.md](./workshop/README.md)
- **Presenter narrative** (talk track, questions, slides):
  [docs/demo-guide/](./docs/demo-guide/)

Use this path when the point is that graph structure can become reusable
Databricks data products. The graph evidence enters Databricks as stable Gold
columns that any downstream Databricks workflow can consume without calling Neo4j
at query time.

## Path B: Neo4j MCP Graph Agent

The live graph-evidence path. Neo4j GDS still computes the structural evidence,
but the evidence is retrieved through MCP by a graph-only agent. A Databricks
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
| Neo4j MCP graph agent endpoint     |   | BEFORE Genie Space          |
| neo4j-mcp-graph-agent project      |   | Silver/base Delta tables    |
| No Genie calls, no Gold dependency |   | accounts, merchants,        |
+---------------+--------------------+   | transactions, account_links |
                |                        +--------------+-------------+
                | Databricks MCP proxy                  |
                v                                       |
+------------------------------------+                  |
| UC HTTP connection with MCP enabled|                  |
| Provisioned by graph-agent project |                  |
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

Run the end-to-end connection bootstrap, validation, and agent deployment from
[neo4j-mcp-graph-agent/README.md](./neo4j-mcp-graph-agent/README.md).

Use this path when the point is live graph tool access beside Genie, without
persisting graph-enriched Gold tables. This repo deploys the MCP-backed agent
endpoint; Supervisor Agent and Genie wiring are Databricks-side setup.

## Path C: Fraud Signal Workbench

The investigator-facing application path. Its React UI and FastAPI backend query
Neo4j directly for candidate rings, risky accounts, and central accounts. The
analyst selects evidence to materialize into Delta tables and then analyzes
those tables through Genie.

```text
Analyst → React UI → FastAPI → Neo4j Aura
                         │
                         └→ selected subgraph → Delta tables → Genie
```

Use this path for a guided investigation workflow rather than a general
conversational agent. See
[fraud-signal-workbench/README.md](./fraud-signal-workbench/README.md) for
deployment, permissions, and local-development instructions.

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
| [`neo4j-mcp-graph-agent/`](./neo4j-mcp-graph-agent/README.md) | The external MCP integration and deployable graph-only agent endpoint: AgentCore OAuth, UC HTTP connection, tool discovery, and Model Serving. | Enabling live graph access through MCP or pairing with a Supervisor Agent. |
| [`fraud-signal-workbench/`](./fraud-signal-workbench/README.md) | Full-stack React + FastAPI analyst workbench (Search, Load, Analyze). | Investigating fraud signals through direct Neo4j, Delta, and Genie integration. |

Quick pointers:

- **Presenter prep:** [docs/demo-guide/prep-guide.md](./docs/demo-guide/prep-guide.md) for the story, questions, and slides.
- **Workshop participants:** [workshop/README.md](./workshop/README.md) for the notebook sequence and cluster prerequisites.
- **Demo owner / CI:** [enrichment-pipeline/README.md](./enrichment-pipeline/README.md) for data, tables, secrets, validation, and CLI commands.
- **Neo4j MCP graph agent:** [neo4j-mcp-graph-agent/README.md](./neo4j-mcp-graph-agent/README.md) for connection setup, endpoint deployment, and Supervisor handoff.
- **Fraud Signal Workbench:** [fraud-signal-workbench/README.md](./fraud-signal-workbench/README.md) for the analyst investigation UI.

## Further Reading

- [ARCHITECTURE.md](./ARCHITECTURE.md): design rationale, GDS algorithm choices, and integration patterns.
- [Production scoping guide](./docs/SCOPING_GUIDE.md): calibration, evaluation, and operational boundaries beyond the teaching dataset.
- [Full Finance Genie deck](https://neo4j-partners.github.io/graph-on-databricks/slides.html)
- [15-minute Finance Genie deck](https://neo4j-partners.github.io/graph-on-databricks/slides-15min.html)

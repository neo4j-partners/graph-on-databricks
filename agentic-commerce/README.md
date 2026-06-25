# Agentic Commerce

Agentic Commerce is a Databricks-hosted shopping assistant backed by Neo4j. It can search products, diagnose product issues, answer GraphRAG-backed support questions, remember user preferences, and use those preferences for personalized recommendations.

The deployment path builds a local `retail_agent` wheel, uploads it to a Unity Catalog volume, and submits Databricks Python wheel entry points with `databricks-job-runner`. For design background, see [Agentic Commerce: GraphRAG Meets Agent Memory on Neo4j](docs/agentic-commerce.md). For lower-level GraphRAG notes, see [Developer's Guide: GraphRAG on Databricks](docs/DevelopersGuideGraphRAG-Databricks.md).

## Why Graph + Databricks for Retail AI

Retail recommendation and support systems built on flat data models hit a ceiling quickly. Vector search finds semantically similar products, but it cannot answer "which products in the customer's preferred brand also have the performance attributes they care about, and what issues have other customers reported with those specific models?" That question requires traversing relationships, not ranking embeddings.

This demo builds a shopping assistant that treats product data as a graph:

- **Product relationships**: Products connect to categories, brands, and attributes as first-class graph nodes.
- **Source knowledge**: Support tickets, reviews, and knowledge articles link directly to the products they describe.
- **Agent memory**: Customer preferences accumulate as a persistent subgraph, retrievable by semantic similarity across sessions.
- **Query pattern**: Agent responses combine graph traversal with semantic retrieval, grounding answers in both structured product relationships and unstructured knowledge content.

### Neo4j

Neo4j stores and traverses the relationship graph natively:

- **Cypher traversal**: Multi-hop product relationship queries are single Cypher statements. The SQL equivalent is a chain of joins that grows with each hop.
- **GraphRAG layer**: Source knowledge documents are chunked, entities and symptoms extracted, and nodes linked back to the product graph. Retrieval uses both vector similarity and graph proximity, improving answer specificity compared to a flat vector index on the same content.
- **Agent memory**: Facts and preferences store as graph nodes and accumulate across sessions without fine-tuning the model.

### Databricks

Databricks provides the execution environment, the LLM, and the embedding service:

- **Model Serving**: The agent runs as an MLflow ChatAgent, registered in Unity Catalog and deployed to a REST endpoint.
- **LLM inference**: `databricks-claude-sonnet-4-6` handles reasoning and generation.
- **Embeddings**: `databricks-bge-large-en` generates embeddings for both the GraphRAG index and the memory layer.
- **Unity Catalog**: Holds registered model versions and the wheel artifacts that Databricks Jobs use to load and build the graph.

Neo4j owns the relationship and retrieval layer. Databricks owns inference, deployment, and model lifecycle.

## What This Repo Contains

- An MLflow `ChatAgent` model implemented in `retail_agent/agent/serving.py`.
- A LangGraph ReAct agent with product, knowledge, memory, preference, commerce, reasoning, and diagnostic tools.
- Databricks job entry points for product graph loading, GraphRAG loading, model deployment, and endpoint verification.
- Neo4j graph schemas for product relationships, GraphRAG retrieval, and agent memory.
- Lakehouse data generation scripts for optional SQL and Genie-style analytics demos.
- A stub Mosaic AI multi-agent supervisor for future Genie plus KG-agent routing.

## Prerequisites

1. Python 3.12 or newer.
2. `uv` installed locally.
3. Databricks CLI configured with a profile that can access the target workspace.
4. A running Databricks cluster for job steps.
5. Unity Catalog catalog, schema, and volume:
   - `retail_assistant`
   - `retail`
   - `retail_volume`
6. A Neo4j database reachable from Databricks.
7. Databricks model serving access to:
   - `databricks-claude-sonnet-4-6`
   - `databricks-bge-large-en`

The product loader uses Spark and the Neo4j Spark Connector. Use a dedicated-access cluster and install:

```text
org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3
```

## Quick Start

Install local dependencies:

```bash
uv sync
```

Create `.env` from `.env.sample` and fill in the Databricks and Neo4j values:

```bash
cp .env.sample .env
```

Upload Neo4j credentials into the Databricks secret scope used by serving:

```bash
./retail_agent/scripts/setup_databricks_secrets.sh --profile <profile>
```

The script reads `NEO4J_URI` and `NEO4J_PASSWORD` from `.env` and writes them to the `retail-agent-secrets` scope. The runner treats these Neo4j values as local setup inputs and does not forward the password as a job parameter.

Validate the Databricks configuration:

```bash
uv run python -m cli validate
```

Run the full pipeline:

```bash
uv run python -m cli pipeline --all
```

For step-by-step deployment, pipeline modes, focused testing, and individual commands, see [docs/runbook.md](docs/runbook.md).

Run the demo client locally after the serving endpoint is deployed:

```bash
cd demo-client
cp .env.sample .env
apx dev start
```

Open `http://localhost:9000`. Use `apx dev status`, `apx dev logs`, and `apx dev stop` to manage the local app. See [demo-client/README.md](demo-client/README.md) for full local checks, runtime settings, backend smoke tests, and deployment commands.

## Architecture

```text
+------------------------+
| Developer machine      |
| uv + .env + CLI        |
+-----------+------------+
            |
            | build and upload retail_agent wheel
            v
+------------------------+          +-----------------------------+
| Unity Catalog Volume   |          | Databricks Workspace        |
| wheels/retail_agent    |          | one-time wheel job submits  |
+-----------+------------+          +--------------+--------------+
            |                                      |
            | wheel dependency                     | submit tasks
            v                                      v
+---------------------------------------------------------------+
| Databricks Job Cluster                                        |
| 1. load product graph and source knowledge into Neo4j          |
| 2. build GraphRAG chunks, entities, relationships, indexes     |
| 3. log/register/deploy the agent model                         |
| 4. run endpoint, retriever, and knowledge verification         |
+----------------------------+----------------------------------+
                             |
                             | deploys and verifies
                             v
+---------------------------------------------------------------+
| Databricks Model Serving                                      |
| MLflow ChatAgent + LangGraph ReAct agent + ChatDatabricks LLM |
+----------------------------+----------------------------------+
                             |
                             | reads and writes
                             v
+---------------------------------------------------------------+
| Neo4j                                                         |
| Product graph + GraphRAG retrieval graph + agent memory       |
+---------------------------------------------------------------+

Optional analytics path:

+------------------------+          +-----------------------------+
| Lakehouse generator    |          | Delta tables / SQL / Genie  |
| synthetic retail CSVs  +--------->| analytics demos             |
+------------------------+          +-----------------------------+
```

### Agent Tools

| Tool group | Purpose |
|------------|---------|
| Product tools | Product search, product details, related products |
| Knowledge tools | GraphRAG semantic search, hybrid keyword/vector search, product issue diagnosis |
| Memory tools | Session-scoped remember, recall, and semantic memory search |
| Preference tools | User-scoped long-term preference tracking and profile retrieval |
| Commerce tools | Preference-aware product recommendations using knowledge graph traversal |
| Reasoning tools | Store and recall multi-step reasoning traces |
| Diagnostics | Validate serving-time tool injection and Neo4j/memory initialization |

### Data Layers

| Layer | Main nodes and relationships | Built by |
|-------|------------------------------|----------|
| Product graph | `Product`, `Category`, `Brand`, `Attribute`; `IN_CATEGORY`, `MADE_BY`, `HAS_ATTRIBUTE`, `SIMILAR_TO`, `BOUGHT_TOGETHER` | `retail-agent-load-products` |
| Source knowledge | `KnowledgeArticle`, `SupportTicket`, `Review`; source document relationships to products | `retail-agent-load-products` |
| GraphRAG layer | `Document`, `Chunk`, `Feature`, `Symptom`, `Solution`; retrieval and product shortcut relationships | `retail-agent-load-graphrag` |
| Agent memory | `Message`, `Preference`, `Fact`, `Task` and memory vector indexes | `neo4j-agent-memory` at serving time |
| Lakehouse analytics | Generated retail CSVs uploaded as Delta tables for SQL and Genie demos | `retail_agent.scripts.generate_transactions`, `retail_agent.scripts.lakehouse_tables` |

Databricks provides the job execution environment, MLflow model registry, Model Serving endpoint, LLM endpoint, embedding endpoint, Unity Catalog volume for wheels, and optional Delta Lake tables for analytics demos.

## Project Structure

```text
cli/
`-- __main__.py                       # project CLI entry point

retail_agent/
|-- agent/                            # ChatAgent adapter, LangGraph agent, config, supervisor stub
|-- tools/                            # catalog, knowledge, memory, preferences, reasoning, commerce, diagnostics
|-- integrations/                     # Databricks and Neo4j integration helpers
|-- deployment/                       # Databricks wheel entry points
|-- demos/                            # endpoint and retriever checks
|-- data/                             # product catalog and source knowledge fixtures
`-- scripts/                          # lakehouse generation and secret setup helpers

demo-client/                          # optional frontend/backend demo client
docs/                                 # architecture and implementation notes
tests/                                # local tests
```

## Docs

| Document | Description |
|----------|-------------|
| [Deployment Runbook](docs/runbook.md) | Pipeline modes, step-by-step deployment, focused testing, individual commands, and local validation |
| [Lakehouse Data](docs/lakehouse.md) | Optional SQL analytics data generation for Genie-style demos |
| [Supervisor Stub](docs/supervisor.md) | Future multi-agent supervisor design and implementation notes |
| [Agentic Commerce: GraphRAG Meets Agent Memory on Neo4j](docs/agentic-commerce.md) | Design background and architecture narrative |
| [Developer's Guide: GraphRAG on Databricks](docs/DevelopersGuideGraphRAG-Databricks.md) | Lower-level GraphRAG implementation notes |

# Aircraft GraphRAG: Neo4j + Databricks in Action

Neo4j and Databricks solve different halves of the same problem. Databricks handles volume and governance: time-series sensor data, aggregations, and SQL analytics across a fleet. Neo4j handles topology and traversal: which components are connected, which systems share failure patterns, which maintenance events cascade across aircraft. Together they form a complete intelligence platform that AI agents can query through natural language.

This sample shows that partnership in action using an Aircraft Digital Twin. A 20-aircraft fleet is modeled in Neo4j as a connected graph of aircraft, systems, components, maintenance events, and flights. Maintenance manuals are chunked, embedded with Databricks Foundation Model APIs, and stored as graph nodes. GraphRAG retrievers combine vector similarity with graph traversal to return richer, more connected context than vector search alone.

## The Business Problem

Maintenance teams work with two kinds of knowledge: structured records (which component failed, on which flight, at which airport) and unstructured documentation (how to diagnose and repair it). These are usually stored in separate systems that cannot be queried together.

A technician asking "what components are most likely to fail on the V2500 engine during high-cycle operations?" has to manually cross-reference a maintenance manual against a work order history. Neither system knows about the other.

GraphRAG closes that gap. The graph connects the manual to the physical components it describes. A retriever can find the relevant manual section by semantic similarity, then follow graph relationships to the actual fleet components and their maintenance histories, all in a single query.

## What Each Platform Does

**Databricks** provides the foundation model APIs for generating embeddings, the compute for running notebooks, and the governance layer (Unity Catalog) for production deployments. In the full workshop this sample is drawn from, Databricks also holds the high-volume sensor telemetry that a Genie space queries with natural language SQL.

**Neo4j** stores the connected topology: aircraft, systems, components, sensors, flights, airports, delays, and maintenance events as nodes and relationships. It also holds the GraphRAG layer: Document and Chunk nodes linked to the components they describe, plus vector and fulltext indexes for retrieval.

Databricks answers "how much?" and "how often?" Neo4j answers "how is this connected?" and "what is affected?" Most real maintenance questions need both.

## What the Notebooks Build

| Notebook | What it does |
|---|---|
| `01_etl_to_neo4j` | Loads the aircraft topology from committed CSVs into Neo4j |
| `02_gds_louvain` | Runs Louvain community detection to cluster maintenance events (optional) |
| `03_data_and_embeddings` | Chunks two maintenance manuals, generates embeddings via Databricks Foundation Model APIs, builds vector and fulltext indexes, cross-links chunks to graph nodes |
| `04_graphrag_retrievers` | Vector retriever and VectorCypher retriever: find a manual chunk by similarity, then traverse the graph to connected components and maintenance events |
| `05_hybrid_retrievers` | Hybrid retriever combining vector similarity and fulltext search |

Required path: **01 → 03 → 04 → 05**. Notebook 02 is optional and requires the GDS plugin.

## The Data

The Aircraft Digital Twin covers a 20-aircraft fleet across four models (A320-200, A321neo, B737-800, E190). All data ships with the project in `data/` so the notebooks run from a fresh clone.

**Graph nodes:** Aircraft, System, Component, Sensor, Airport, Flight, Delay, MaintenanceEvent, Removal

**Relationships:** HAS_SYSTEM, HAS_COMPONENT, HAS_SENSOR, HAS_EVENT, OPERATES_FLIGHT, DEPARTS_FROM, ARRIVES_AT, HAS_DELAY, AFFECTS_SYSTEM, AFFECTS_AIRCRAFT, HAS_REMOVAL, REMOVED_COMPONENT

**Manuals:** `MAINTENANCE_A320.md` (V2500 engine) and `MAINTENANCE_B737.md` (CFM56 engine)

Notebook 03 adds the GraphRAG layer: Document, Chunk, and OperatingLimit nodes linked to graph components via FROM_DOCUMENT, NEXT_CHUNK, APPLIES_TO, and HAS_LIMIT relationships.

## Prerequisites

- **Neo4j:** An Aura free tier instance is enough. Notebook 02 additionally needs the GDS plugin (Aura Professional or higher).
- **Databricks:** A workspace with Foundation Model APIs enabled, for notebooks 03-05. Embeddings use `databricks-bge-large-en`; generation uses `databricks-meta-llama-3-3-70b-instruct`, both via the MLflow deployments client.
- **Python packages:** `neo4j` for notebooks 01-02; `neo4j-graphrag` and `mlflow` for notebooks 03-05. Each notebook installs its dependencies with `%pip`.

Notebooks 01 and 02 run anywhere with only the Neo4j driver and the committed data. The Databricks Foundation Model dependency starts at notebook 03.

## Loading Data

Each data-loading notebook has a `DATA_SOURCE` setting:

```python
# "github"  -> raw files from the public repo (default, zero setup)
# "local"   -> a local clone (./data)
# "volume"  -> a Unity Catalog volume you have populated
DATA_SOURCE = "github"
```

The default reads from the committed `data/` directory over GitHub HTTPS. Open a notebook and run it with nothing to upload or provision. For private data or locked-down workspaces, switch to `"local"` or `"volume"`.

## Where This Fits

This sample is extracted from the [databricks-neo4j-lab](https://github.com/neo4j-partners/databricks-neo4j-lab) workshop, focused on the GraphRAG core. The full workshop adds a Genie space for sensor telemetry analytics and a no-code Agent Bricks Supervisor that routes questions to Neo4j or Genie based on what each platform does best.

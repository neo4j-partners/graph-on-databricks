# aircraft-graphrag

A standalone GraphRAG sample over an Aircraft Digital Twin graph. Load the topology into Neo4j, run a Graph Data Science algorithm, embed two maintenance manuals, and build retrievers over the result. The data ships with the project, so the notebooks run from a fresh clone with no workspace pre-provisioning.

The sample is extracted from the [databricks-neo4j-lab](https://github.com/neo4j-partners/databricks-neo4j-lab) workshop, trimmed to the GraphRAG core: no Unity Catalog volume, no setup CLIs, no multi-agent supervisor.

## What's here

```
aircraft-graphrag/
  data/                  # committed CSVs + two maintenance manuals (~400 KB)
  notebooks/
    01_etl_to_neo4j.ipynb              # load the topology with the Neo4j Python driver
    02_gds_louvain_maintenance.ipynb   # GDS Louvain over the maintenance chain (optional)
    03_data_and_embeddings.ipynb       # chunk + embed two manuals, build indexes, cross-link
    04_graphrag_retrievers.ipynb       # vector + VectorCypher retrievers
    05_hybrid_retrievers.ipynb         # hybrid (vector + fulltext) retrievers
  data_utils.py          # data loader, Databricks model wrappers, Neo4j + pipeline helpers
  .env.sample            # Neo4j credentials
```

## Run order

```
01_etl_to_neo4j            loads the aircraft topology
  -> 02_gds_louvain        reads topology, writes community_id          (optional branch)
  -> 03_data_and_embeddings loads manuals, builds chunks + indexes
       -> 04_graphrag_retrievers  reads chunks + indexes + topology
       -> 05_hybrid_retrievers    reads chunks + both indexes
```

Required path: **01 -> 03 -> 04 -> 05**. Notebook **02** is an optional Graph Data Science branch; it is not a prerequisite for the retrievers.

## Prerequisites

- A Neo4j instance and its credentials. Aura free tier is enough for a graph this size. Notebook 02 additionally needs the **GDS plugin** (Aura Professional or higher).
- For notebooks 03-05, a **Databricks workspace with Foundation Model APIs enabled**. Embeddings use `databricks-bge-large-en` and generation uses `databricks-meta-llama-3-3-70b-instruct`, both reached through the MLflow deployments client.
- Python packages: `neo4j` (notebooks 01-02) and `neo4j-graphrag` plus `mlflow` (notebooks 03-05). Each notebook installs what it needs with `%pip` in its first cell.

Notebooks 01 and 02 use only the Neo4j driver and the committed data, so they run anywhere. The Foundation Model dependency starts at notebook 03.

## Where the data comes from: the `DATA_SOURCE` switch

Each data-loading notebook has a `DATA_SOURCE` setting in its configuration cell:

```python
# "github"  -> raw files from the public repo (default, zero setup)
# "local"   -> a local clone (./data)
# "volume"  -> a Unity Catalog volume you have populated
DATA_SOURCE = "github"
```

The default reads the committed `data/` directory straight from GitHub over HTTPS, so you open a notebook and run it with nothing to upload or provision.

> **Caveat:** loading from a raw GitHub URL fetches over the public internet. That suits this public sample dataset and demo workspaces. For private data or locked-down workspaces, set `DATA_SOURCE = "local"` (run from a clone) or `"volume"` (point `data_utils.VOLUME_DATA_PATH` at a volume you have populated).

## The data

The Aircraft Digital Twin models a 20-aircraft fleet across four models (A320-200, A321neo, B737-800, E190). The sample keeps the connected topology and drops the high-volume sensor telemetry (`nodes_readings.csv`), which is the Databricks Lakehouse half of the original workshop and is not used by any retriever.

- **Nodes:** Aircraft, System, Component, Sensor, Airport, Flight, Delay, MaintenanceEvent, Removal
- **Relationships:** HAS_SYSTEM, HAS_COMPONENT, HAS_SENSOR, HAS_EVENT, OPERATES_FLIGHT, DEPARTS_FROM, ARRIVES_AT, HAS_DELAY, AFFECTS_SYSTEM, AFFECTS_AIRCRAFT, HAS_REMOVAL, REMOVED_COMPONENT
- **Manuals:** `MAINTENANCE_A320.md` (V2500 engine) and `MAINTENANCE_B737.md` (CFM56 engine)

Notebook 03 adds the GraphRAG layer on top: Document, Chunk, and OperatingLimit nodes, plus `FROM_DOCUMENT`, `NEXT_CHUNK`, `APPLIES_TO`, and `HAS_LIMIT` relationships.

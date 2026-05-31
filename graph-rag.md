# Proposal: A Standalone GraphRAG Example for graph-on-databricks

## Summary

This proposes a new self-contained project under `graph-on-databricks` that extracts a small graph sample and a short notebook series from the `databricks-neo4j-lab` workshop. The existing workshop is a multi-phase, admin-provisioned lab: it depends on a Unity Catalog volume populated by setup CLIs, an Aura instance loaded by `lab_setup/populate_aircraft_db`, and a sequence of five labs that build toward a multi-agent supervisor. That coupling makes it a poor fit for someone who wants to read one short example and run it.

The new project keeps only the GraphRAG core: load a graph into Neo4j, run one Graph Data Science algorithm, chunk and embed maintenance documentation, and build retrievers over the result. It ships its own data, loads that data with no workspace pre-provisioning, and runs end to end from a fresh clone.

## Proposed name

**`aircraft-graphrag`**

It follows the existing naming convention in the repo. The current projects name their domain plus their technique: `agentic-commerce`, `finance-genie`, `sql-semantics`. `aircraft-graphrag` names the dataset (the Aircraft Digital Twin) and the technique (GraphRAG), so it reads consistently alongside the others and is unambiguous in the project list.

Alternatives, if a different emphasis is wanted:

| Name | Emphasis | Trade-off |
|------|----------|-----------|
| `aircraft-graphrag` (recommended) | Dataset + technique | Matches existing convention directly |
| `maintenance-copilot` | The use case (a maintenance Q&A assistant) | Reads well but hides that it is a GraphRAG sample |
| `graphrag-starter` | Generic entry point | Clear intent, but loses the aircraft framing the data carries |

The rest of this proposal uses `aircraft-graphrag`.

## Scope: what the sample includes and excludes

The workshop dataset spans two databases. The Aircraft Digital Twin splits time-series sensor telemetry into Databricks Delta tables and the connected topology into Neo4j. GraphRAG needs only the connected side, so the sample drops the telemetry entirely.

**Included (the graph sample):**

- Aircraft, System, and Component topology
- Maintenance events and removals
- Flights, delays, and airports (used by the GDS example)
- Two maintenance manuals for document chunking and embeddings

**Excluded:**

- `nodes_readings.csv` (22.5 MB of hourly sensor telemetry). This belongs to the Databricks Lakehouse half of the dual-database story and is not used by any retriever.
- The Genie space, the Supervisor Agent, the Neo4j MCP server, and the per-user provisioning CLIs (Labs 4 and 5).

Dropping the readings file is what makes the sample shippable. The remaining topology CSVs plus two maintenance manuals total roughly 350 KB, well within what a Git repository should carry directly.

## Data directory: precreated and committed

The project ships a `data/` directory copied from `databricks-neo4j-lab/lab_setup/aircraft_digital_twin_data/`, minus the readings file:

```
aircraft-graphrag/
  data/
    nodes_aircraft.csv          # ~1 KB
    nodes_systems.csv           # ~3 KB
    nodes_components.csv        # ~16 KB
    nodes_sensors.csv           # ~9 KB
    nodes_flights.csv           # ~62 KB
    nodes_delays.csv            # ~14 KB
    nodes_airports.csv          # ~1 KB
    nodes_maintenance.csv       # ~30 KB
    nodes_removals.csv          # ~14 KB
    rels_aircraft_system.csv
    rels_system_component.csv
    rels_system_sensor.csv
    rels_component_event.csv
    rels_event_aircraft.csv
    rels_event_system.csv
    rels_aircraft_flight.csv
    rels_flight_departure.csv
    rels_flight_arrival.csv
    rels_flight_delay.csv
    rels_aircraft_removal.csv
    rels_component_removal.csv
    MAINTENANCE_A320.md         # ~31 KB, V2500 engine (Airbus narrowbody)
    MAINTENANCE_B737.md         # ~37 KB, CFM56 engine (Boeing narrowbody)
```

The full set above is roughly 350 KB. There is no generator to run and no admin step to provision a volume. The data is the artifact. The two manuals cover the two engine families the retriever examples query (V2500 and CFM56), so the side-by-side retrieval comparisons in notebooks 04 and 05 have material from more than one aircraft model to discriminate between.

## Loading data from the committed directory (answering the GitHub question)

The workshop reads CSVs from a Unity Catalog volume path that an admin populates ahead of time:

```python
DATA_PATH = "/Volumes/databricks-neo4j-lab/lab-schema/lab-volume"
```

That is the single biggest barrier to a standalone run. The proposal removes it by reading the committed `data/` directory directly. Because the data is small and lives in the repo, the loader can fetch each file straight from the raw GitHub URL, so the notebook needs no local checkout, no volume, and no upload step:

```python
# Standalone default: read straight from the committed data directory on GitHub.
DATA_BASE = (
    "https://raw.githubusercontent.com/neo4j-partners/"
    "graph-on-databricks/main/aircraft-graphrag/data"
)

def load_csv(filename: str):
    return pd.read_csv(f"{DATA_BASE}/{filename}")
```

This is the recommended default, and it answers the question directly: yes, the notebooks can point at the GitHub `data/` directory and load from there, which is the easiest possible start. A user opens the notebook, runs it, and the data arrives over HTTPS.

To keep it usable inside a governed workspace too, the configuration cell exposes a single switch:

```python
# "github"  -> read raw files from the repo (default, zero setup)
# "local"   -> read from a local clone (./data)
# "volume"  -> read from a Unity Catalog volume you have populated
DATA_SOURCE = "github"
```

The loader resolves `DATA_BASE` from that switch and nothing else in the notebook changes. The standalone path stays the default; the volume path remains available for anyone who wants the governed pattern.

One caveat to record in the README: loading from a raw GitHub URL fetches over the public internet, so it suits a public sample dataset and demo workspaces. For private data or locked-down workspaces, users switch to `local` or `volume`.

## Notebook series

Five simplified notebooks, modeled on the workshop notebooks the request named, in two folders that mirror the workshop structure:

```
aircraft-graphrag/
  notebooks/
    01_etl_to_neo4j.ipynb              # from Lab_2/01_aircraft_etl_to_neo4j
    02_gds_louvain_maintenance.ipynb   # from Lab_2/03_gds_louvain_maintenance
    03_data_and_embeddings.ipynb       # from Lab_3/03_data_and_embeddings
    04_graphrag_retrievers.ipynb       # from Lab_3/04_graphrag_retrievers
    05_hybrid_retrievers.ipynb         # from Lab_3/06_hybrid_retrievers
```

| Notebook | Source notebook | What it teaches | Simplifications |
|----------|-----------------|-----------------|-----------------|
| `01_etl_to_neo4j` | `Lab_2/01_aircraft_etl_to_neo4j` | Read the committed CSVs, load Aircraft, System, Component nodes and their relationships into Neo4j, verify with Cypher | Reads from `data/` over GitHub by default instead of a UC volume; loads via the Python driver so it runs without the Spark Connector cluster add-on |
| `02_gds_louvain_maintenance` | `Lab_2/03_gds_louvain_maintenance` | Build a fault co-occurrence projection and run Louvain community detection over maintenance faults, writing `community_id` back to Aircraft nodes | Drops the Section 6 step that joins sensor readings from Databricks, since the readings table is out of scope; keeps the pure-graph algorithm story |
| `03_data_and_embeddings` | `Lab_3/03_data_and_embeddings` | Load both maintenance manuals, chunk them, generate embeddings, create the vector and fulltext indexes, cross-link chunks to the aircraft topology | Loads `data/MAINTENANCE_A320.md` and `data/MAINTENANCE_B737.md`; keeps `SimpleKGPipeline` entity extraction so the graph carries operating limits |
| `04_graphrag_retrievers` | `Lab_3/04_graphrag_retrievers` | Vector retriever, then `VectorCypherRetriever` examples that enrich chunks with document context, adjacent chunks, and aircraft topology, ending in a full GraphRAG answer | Trimmed to the clearest two or three retriever examples rather than all four |
| `05_hybrid_retrievers` | `Lab_3/06_hybrid_retrievers` | Hybrid (vector + fulltext) retrieval and a side-by-side comparison against pure vector search | Kept close to the original; it is already a compact "optional" notebook |

Each notebook keeps the workshop's single Configuration cell at the top for Neo4j credentials, plus the `DATA_SOURCE` switch described above. Notebooks 03 through 05 reuse a trimmed `data_utils.py` lifted from `Lab_3_Semantic_Search/data_utils.py`, carrying the `DatabricksEmbeddings`, `DatabricksLLM`, `Neo4jConnection`, and `run_pipeline` helpers. The embedder and LLM defaults stay as the workshop sets them: `databricks-bge-large-en` for embeddings and `databricks-meta-llama-3-3-70b-instruct` for generation, both served through the Databricks Foundation Model APIs.

## Dependency order

The notebooks form a chain. Each depends on the graph state the previous one leaves behind:

```
01_etl_to_neo4j            loads topology
  -> 02_gds_louvain        reads topology, writes community_id          (optional branch)
  -> 03_data_and_embeddings loads manuals, builds chunks + indexes
       -> 04_graphrag_retrievers  reads chunks + indexes + topology
       -> 05_hybrid_retrievers    reads chunks + both indexes
```

Notebook 02 is an optional branch: it demonstrates Graph Data Science on the same graph but is not a prerequisite for the retriever notebooks. The README states the required path (01 -> 03 -> 04 -> 05) and marks 02 as optional, the same way Lab 3 marks `06_hybrid_retrievers` optional.

## Project layout

```
aircraft-graphrag/
  README.md              # what it is, prerequisites, run order, the DATA_SOURCE switch and its caveat
  data/                  # committed CSVs + two maintenance manuals (~400 KB)
  notebooks/             # the five notebooks above
  data_loader.py         # data loaders + Neo4j connection (neo4j + stdlib only)
  data_utils.py          # embedder / LLM / SimpleKGPipeline helpers from Lab 3 (re-exports data_loader)
  .env.sample            # NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
```

The top-level `graph-on-databricks/README.md` gains one entry under Projects, written in the same voice as the `agentic-commerce` and `finance-genie` entries, pointing at `aircraft-graphrag/README.md`.

## Prerequisites for a user

- A Neo4j instance (Aura free tier is enough for a graph this size) and its three credentials.
- A Databricks workspace with Foundation Model APIs enabled, for the embedder and LLM. Notebooks 03 through 05 call `databricks-bge-large-en` and `databricks-meta-llama-3-3-70b-instruct`.
- `neo4j`, `neo4j-graphrag`, and `pandas`. No Spark Connector cluster add-on, no Unity Catalog volume, no setup CLI.

Notebook 01 (load) and notebook 02 (GDS) need only Neo4j; the Foundation Model dependency starts at notebook 03 where embeddings begin.

## What gets reused versus rewritten

- **Reused as-is:** the CSV and maintenance manual content, the GDS Louvain Cypher, the `SimpleKGPipeline` extraction schema, the retriever examples and their Cypher, and the `DatabricksEmbeddings` / `DatabricksLLM` / `Neo4jConnection` helpers.
- **Rewritten:** the data-loading layer, which moves from the Spark Connector reading a UC volume to the Python driver reading the committed `data/` directory; and the configuration cells, which add the `DATA_SOURCE` switch and drop the volume path as the default.

## Decisions

1. **Name:** `aircraft-graphrag`. Confirmed.
2. **GDS notebook:** Louvain community detection on maintenance faults. Confirmed.
3. **Manuals:** two manuals, `MAINTENANCE_A320.md` (V2500 engine) and `MAINTENANCE_B737.md` (CFM56 engine). They cover the two engine families the retriever examples query, so the vector-versus-hybrid comparisons in notebooks 04 and 05 have more than one aircraft model to discriminate between.
4. **GitHub loading default:** reading raw files from the public repo is the default `DATA_SOURCE`, with `local` and `volume` as alternatives and the public-internet caveat recorded in the README. Confirmed.

## Implementation plan

Build it in the order the notebooks run, so each step can be tested against a live Neo4j before the next one depends on it.

**Status (built and committed under `aircraft-graphrag/`):** all files are written. Every notebook's structure is validated as nbformat 4.5 and every code cell parses. The live-execution checks remain open: they need a Neo4j instance and a Databricks workspace with Foundation Model APIs, which this environment does not have. Those boxes are called out below and are the remaining work before the sample is proven end to end.

### 1. Scaffold the project
- [x] Create `aircraft-graphrag/` with `data/`, `notebooks/`, `data_utils.py`, `README.md`, and `.env.sample`.
- [x] Add `.env.sample` with `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`.

### 2. Stage the data
- [x] Copy the topology CSVs from `databricks-neo4j-lab/lab_setup/aircraft_digital_twin_data/` into `data/`, leaving out `nodes_readings.csv`.
- [x] Copy `MAINTENANCE_A320.md` and `MAINTENANCE_B737.md` into `data/`.
- [x] Confirm the directory size. Actual total is ~400 KB (21 CSVs + 2 manuals).

### 3. Trim the shared helpers
- [x] Adapt `Lab_3_Semantic_Search/data_utils.py` into the project. Split into two modules so the loader notebooks need only `neo4j`: `data_loader.py` (loaders + `Neo4jConnection`, neo4j + stdlib only) and `data_utils.py` (`DatabricksEmbeddings`, `DatabricksLLM`, `run_pipeline`, extraction schema; re-exports `data_loader`).
- [x] Keep `DatabricksEmbeddings`, `DatabricksLLM`, `Neo4jConnection`, `run_pipeline`, and the extraction schema. Drop `VolumeDataLoader`.
- [x] Add the `DATA_SOURCE` switch (`github` / `local` / `volume`) with `load_csv` and `load_text` helpers that resolve the base from it. Verified the CSV header detection against the staged data.

### 4. Notebook 01 — ETL to Neo4j
- [x] Adapt `Lab_2/01_aircraft_etl_to_neo4j` (plus the full loader from `02_load_neo4j_full`): read CSVs via `load_csv`, load all nodes and relationships through the Python driver with `UNWIND`, verify counts with Cypher.
- [ ] **Run it against a fresh Neo4j and confirm node and relationship counts.** (needs a Neo4j instance)

### 5. Notebook 02 — GDS Louvain (optional branch)
- [x] Adapt `Lab_2/03_gds_louvain_maintenance`: fault co-occurrence projection, Louvain, write `fault_community` back to Aircraft.
- [x] Drop the Section 6 step that joins sensor readings; keep a pure-graph critical-event-rate insight instead.
- [ ] **Run it and confirm communities are written.** (needs a Neo4j instance with the GDS plugin)

### 6. Notebook 03 — Data and embeddings
- [x] Adapt `Lab_3/03_data_and_embeddings`: load both manuals, chunk, embed with `databricks-bge-large-en`, create the vector and fulltext indexes, cross-link chunks to topology.
- [ ] **Run it and confirm chunks, embeddings, and indexes exist.** (needs Neo4j + Databricks Foundation Model APIs)

### 7. Notebooks 04 and 05 — Retrievers
- [x] Adapt `Lab_3/04_graphrag_retrievers`: vector retriever plus three `VectorCypherRetriever` examples (adjacent chunks, topology, operating limits), ending in a full GraphRAG answer.
- [x] Adapt `Lab_3/06_hybrid_retrievers`: hybrid retrieval and a vector-versus-hybrid comparison across the two manuals (V2500 and CFM56 queries).
- [ ] **Run both end to end and confirm answers come back.** (needs Neo4j + Databricks Foundation Model APIs)

### 8. Document and wire up
- [x] Write `aircraft-graphrag/README.md`: what it is, prerequisites, run order (01 -> 03 -> 04 -> 05, with 02 optional), the `DATA_SOURCE` switch, and the public-internet caveat.
- [x] Add one `aircraft-graphrag` entry to the top-level `graph-on-databricks/README.md` Projects section.
- [ ] **Run all five notebooks from a clean clone with `DATA_SOURCE = "github"` to confirm a zero-setup start.** (needs Neo4j + Databricks, and the `data/` directory pushed to the `main` branch so the raw URLs resolve)

# Virtual Graph Demo

A small [uv](https://docs.astral.sh/uv/) Python demo that connects to the Finance
Genie Neo4j Virtual Graph and runs two sets of queries: the basic exploration and
visualization queries from
[`../docs/basic-graph-examples.md`](../docs/basic-graph-examples.md) (`--basic`),
and the plain-Cypher fraud-signal queries from
[`../docs/plain-cypher-examples.md`](../docs/plain-cypher-examples.md) (the default).
Each query is translated to SQL by Aura and executed against the backing
Databricks warehouse.

## Prerequisites

- `uv` installed.
- A `finance-genie/.env.azure` (the parent directory) with the Aura connection set:

  ```
  NEO4J_URI=neo4j+s://<instance>.graph-engine.neo4j.io
  NEO4J_USERNAME=neo4j
  NEO4J_PASSWORD=<password>
  ```

  The demo reads it directly; no copy is needed.

- A Virtual Graph created over the Finance Genie Silver tables, following
  [`../VIRTUAL_GRAPH.md`](../VIRTUAL_GRAPH.md), with the node types named
  `:Account` and `:Merchant`. If your model uses the generated table-name labels
  (`:accounts` / `:merchants`), adjust the labels in `queries.py`.

## Run

```bash
cd virtual-graph-demo-v3
uv run main.py --basic      # run the basic exploration / visualization queries
uv run main.py              # run every Virtual-Graph-compatible (✓) fraud query
uv run main.py --all        # also attempt the ✗ cycles query (expected to fail)
uv run main.py --query 9    # run a single fraud query by its number
uv run main.py --rows 5     # cap the rows printed per query
```

`--basic` runs the warm-up queries: counts, breakdowns, and small anchored
traversals that visualize well in the Aura Workspace. The graph-shaped ones print
only a row count in the CLI; paste them into the Workspace Query tab to see the
graph. The demo picks and prints the anchor account and merchant ids it uses.

`uv run` resolves and installs the dependencies (`neo4j`, `python-dotenv`) into a
local virtual environment on first run.

## Notes

- The `CYPHER 25` directive shown in the doc is omitted here because the Virtual
  Graph translation layer runs plain Cypher. Add it back if you point the demo at a
  loaded Aura graph instead.
- Query 5 (layering cycles) is marked **Virtual Graph: ✗** because it uses a
  variable-length path the translator does not yet cover. It runs only with `--all`,
  and the resulting error is caught and printed rather than stopping the run.
- These queries surface *candidates*, not confirmed fraud. See the interpretation
  caveats at the end of the source doc.

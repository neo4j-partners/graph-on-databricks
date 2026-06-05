# Virtual Graph Demo

A small [uv](https://docs.astral.sh/uv/) Python demo that connects to the Finance
Genie Neo4j Virtual Graph. It is currently set up to **test a GDS Session + PageRank**
against the Virtual Graph, following [`../docs/gds-guide.md`](../docs/gds-guide.md).

GDS is not an in-database plugin on the Virtual Graph, so the classic
`CALL gds.graph.project('account_transfers', 'Account', ...)` form is rejected. The
supported path is a **GDS Session**: pass a memory config to the Cypher-projection form
of `gds.graph.project(...)` to provision an ephemeral session, then stream PageRank
against the named in-memory graph. `gds_pagerank.py` probes that path over the Account
peer-to-peer transfer network (`Account` nodes + `TRANSFERRED_TO` relationships) and
reports the exact outcome, so a clean rejection is itself an informative result.

**Keeping the projection small.** Projecting all ~300k transfers is a full edge scan
and the slow step. Following the performance lessons in
[`../docs/plain-cypher-examples-v2.md`](../docs/plain-cypher-examples-v2.md) (a 7-day
window cut a comparable query from ~223k rows / ~24.8s to ~22k rows / ~3.5s), the
projection is scoped by a **time window**: only `TRANSFERRED_TO` edges newer than
`max(transfer_timestamp) - N days` are projected. The script runs in two steps: a cheap
`count(t)` **sizing query** first (no session, so you can see the projection size and
tune `--since-days` before paying to provision one), then the same windowed `MATCH`
projected into the session. The resulting PageRank measures centrality in the recent
money-flow graph.

The original plain-Cypher fraud-signal queries from
[`../docs/plain-cypher-examples.md`](../docs/plain-cypher-examples.md) are **commented
out** (the `QUERIES` list in `queries.py` and the runner in `main.py`). To restore
them, uncomment both.

## Prerequisites

- `uv` installed.
- A `finance-genie/.env` (the parent directory) with the Aura connection set:

  ```
  NEO4J_URI=neo4j+s://<instance>.graph-engine.neo4j.io
  NEO4J_USERNAME=neo4j
  NEO4J_PASSWORD=<password>
  ```

  This is the same `.env` produced by the Common Setup in
  [`../README.md`](../README.md). The demo reads it directly; no copy is needed.

- A Virtual Graph created over the Finance Genie Silver tables, following
  [`../VIRTUAL_GRAPH.md`](../VIRTUAL_GRAPH.md), with the node types named
  `:Account` and `:Merchant`. If your model uses the generated table-name labels
  (`:accounts` / `:merchants`), adjust the labels in `gds_pagerank.py` (and in
  `queries.py` if you restore the fraud queries).

## Run

```bash
cd virtual-graph-demo
uv run gds_pagerank.py                # 7-day window: size, project, stream top 10, drop
uv run gds_pagerank.py --since-days 3 # tighter window (smaller projection)
uv run gds_pagerank.py --since-hours 2 # thin sub-day slice (~a couple hundred edges)
uv run gds_pagerank.py --count-only   # only size the window; never provision a session
uv run gds_pagerank.py --limit 25     # stream the top 25
uv run gds_pagerank.py --memory 4GB   # request a larger session instance
uv run gds_pagerank.py --keep         # leave the projection/session in place for reuse
uv run gds_pagerank.py --since-hours 72 --read-timeout 0  # large projection, disable the 60s read timeout
```

`uv run` resolves and installs the dependencies (`neo4j`, `python-dotenv`) into a
local virtual environment on first run.

`gds_pagerank.py` runs its statements one at a time: a cheap `count(t)` sizing query
for the window, then drop any stale projection, create the session + windowed
projection (the `{ memory }` argument is what provisions the session), then
`gds.pageRank.stream`. Each statement reports its wall-clock time and, on failure, the
exact Neo4j error code (e.g. `42NG0: Unsupported syntax`). `--count-only` stops after
the sizing query so you can tune `--since-days` without provisioning a session.

## Notes

- **No write-back** to the relational source exists on a Virtual Graph, so PageRank is
  streamed to the app rather than written to `Account` nodes.
- **Pool / performance.** The projection's `MATCH (src)-[:TRANSFERRED_TO]->(dst)` is a
  full ~300k-edge scan, comparable to the heavier fraud queries (~54s on a Small
  warehouse). The Virtual Graph holds ~10 JDBC connections to Databricks and does not
  cancel server-side queries when the client gives up, so run on a clean instance, let
  each statement finish, and never abandon a run. Scale the warehouse up if the
  projection is slow.
- **60s Bolt read timeout.** Aura pins `connection.recv_timeout_seconds: 60`, so the
  driver drops the connection after any 60s gap with no server bytes. GDS Session
  provisioning can go silent longer than that for projections above a few thousand
  edges, which fails the project call with `TimeoutError('The read operation timed
  out')`. There is no public driver config for this; the correct fix is server-side
  keepalives. As an opt-in workaround, `--read-timeout 0` disables the read timeout so a
  long, silent provisioning completes. See `../docs/gds-guide.md` for the full analysis.
- This is a genuine probe of an actively changing surface (see the note at the bottom
  of `../docs/gds-guide.md`); the classic in-database GDS form was previously rejected
  on the Virtual Graph, so a clean failure is a valid outcome to record.

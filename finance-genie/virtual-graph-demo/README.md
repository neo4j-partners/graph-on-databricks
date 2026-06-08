# Virtual Graph Demo

> **First, set up the Virtual Graph.** Follow [VIRTUAL_GRAPH.md](VIRTUAL_GRAPH.md) to
> create the Virtual Graph over the Finance Genie Silver tables before running any demo
> here.

A small [uv](https://docs.astral.sh/uv/) Python demo that runs Cypher against the
Finance Genie Neo4j **Virtual Graph** (Aura translates the Cypher to SQL and runs it on
a backing Databricks SQL warehouse). One entry point, `vg-demo` (`src/cli.py`), runs
four demo sets selected with `--demo`:

| `--demo` | What it is | Everything works? |
|---|---|---|
| `basic` | warm-up exploration and visualization queries | yes |
| `fraud` (default) | the fast fraud-signal queries from `finding-fraud.md` | yes; `--all` adds slow / unsupported ones |
| `fast-gds` | the working GDS Session + PageRank path | yes, on a small window |
| `slow-gds` | the GDS forms that do not work, kept as a demonstration | no, by design |
| `gds-probe` | sweep projections that add node / relationship properties, to isolate which property types the projection rejects | mixed, by design |

## Quick start

Prerequisites:

- `uv` installed.
- A `finance-genie/.env` (the parent directory) with the Aura connection:

  ```
  NEO4J_URI=neo4j+s://<instance>.graph-engine.neo4j.io
  NEO4J_USERNAME=neo4j
  NEO4J_PASSWORD=<password>
  ```

- A Virtual Graph over the Finance Genie Silver tables with node labels `:Account` and
  `:Merchant`, set up as described in [VIRTUAL_GRAPH.md](VIRTUAL_GRAPH.md).

Run any demo (`uv run` installs the project and its dependencies on first use):

```bash
cd virtual-graph-demo

uv run vg-demo                          # fraud demo (default): the 7 fast queries
uv run vg-demo --all                    # also attempt the slow / unsupported queries
uv run vg-demo --demo basic             # exploration / visualization queries
uv run vg-demo --demo fast-gds --since-hours 2   # working PageRank path (thin window)
uv run vg-demo --demo slow-gds          # demonstrate the GDS forms that fail
uv run vg-demo --demo gds-probe --since-hours 2   # sweep property projections (thin window)
```

Useful flags: `--rows N` caps printed rows per query, `--timeout S` sets the per-query
server timeout (default 120s), `--query N` / `--only N M` pick specific fraud queries.

## `basic` demo

Counts, breakdowns, and small anchored traversals that show the value of the
relationships without any fraud logic. All run. The `graph` queries return nodes and
relationships, so the CLI prints only a row count and timing; paste them into the Aura
Workspace Query tab to see the picture. The demo prints the anchor account and merchant
ids it picked.

| # | What it does | Kind |
|---|---|---|
| 1 | Count of accounts | table |
| 2 | Count of merchants | table |
| 3 | Accounts grouped by type | table |
| 4 | Accounts grouped by region | table |
| 5 | Merchants grouped by category | table |
| 6 | Top 10 merchants by distinct customers | table |
| 7 | Ego network: one account and the merchants it shops at | graph |
| 8 | Ego network: one account and its transfer partners | graph |
| 9 | Merchant star: one merchant and the accounts that use it | graph |
| 10 | Two hops: accounts linked through a shared merchant | graph |
| 11 | Two hops: a transfer chain (who your counterparty pays) | graph |

## `fraud` demo

The seven fast queries (1-7) are the pushdown-friendly forms from
[`finding-fraud.md`](finding-fraud.md). They group by scalar ids,
reshape a `count(DISTINCT)` into pair-grouping plus a client-side rollup (fan-in and
fan-out), and split a cross product into two merged halves (courier). The server
aggregates and orders; the threshold filters and top-N run in Python; recent windows are
passed as a precomputed `$since` parameter. Each returns in a few seconds.

| # | What it does | Status |
|---|---|---|
| 1 | Structuring: accounts with many transfers sized just under $10,000 | works |
| 2 | Busy brand-new accounts: recently opened accounts already moving large volume | works |
| 3 | Round trips: account pairs paying each other both ways (wash activity) | works |
| 4 | Velocity ratio: accounts moving far more money than they hold | works |
| 5 | Collection accounts (fan-in): many distinct senders into one account | works |
| 6 | Spray accounts (fan-out): one account paying many distinct recipients | works |
| 7 | Courier accounts: heavy peer-to-peer transfers, little merchant spend | works |

The slow tier (8-11) has no fast equivalent and is skipped unless you pass `--all`. It
is kept to demonstrate what does not work. With `--all` these run behind a printed
warning, bounded by `--timeout`, and any error is caught and printed so the run
continues.

| # | What it does | Status |
|---|---|---|
| 8 | Pass-through mule (local betweenness proxy) | slow: unbounded two-hop join, usually times out |
| 9 | Shared-merchant burst (coordinated ring) | slow: `collect(DISTINCT)` over a node group, hit the 120s timeout |
| 10 | Rapid-turnover per account | slow: unbounded two-hop join, usually times out |
| 11 | Layering cycles | unsupported: variable-length path `{2,4}` fails with `42NG0` |

## `fast-gds` demo

GDS is not an in-database plugin on the Virtual Graph. The supported path is a **GDS
Session**: the Cypher-projection form of `gds.graph.project(...)` with a `{ memory }`
config provisions an ephemeral session, then PageRank streams against the named
in-memory graph. The demo runs its statements one at a time: size the window, drop any
stale projection, project (this provisions the session), stream PageRank, drop.

The "window" is a time-range filter on the transfer rows: `--since-hours` / `--since-days`
keep only transfers from the most recent N hours or days of the data, and that row count
is the edge count projected into the graph. "Size the window" counts those rows without
provisioning a session.

What it looks like on a thin window (the most recent 2 hours of transfers):

```
--- size window (count edges, last 2.0h)        OK 0.6s, 298 edges
--- project ... (provisions the session)        OK 90.9s, 556 nodes / 298 rels
--- PageRank stream (top 10)                     OK 3.9s, 10 rows
--- drop projection                              OK 1.0s
```

Almost all the time is session cold-start, not the query or the algorithm. Streamed
`nodeId`s are GDS-internal ids, not `account_id`s; resolving them back is not reliable on
the Virtual Graph yet, so the demo streams the raw id and score.

**Keep the window small.** `--count-only` counts the rows in a window for free. A thin
window (`--since-hours 2`, the most recent 2 hours of transfers, a few hundred edges)
provisions and completes. The default 7-day window is about 23,000 edges, which trips the
read timeout during provisioning (see Slow GDS). Use `--since-hours` / `--since-days` to scope it, `--limit` to change the top-N,
`--memory` to size the session, and `--keep` to leave the projection in place for reuse.

## `slow-gds` demo

Demonstrates the two GDS failure modes on the Virtual Graph, both caught and printed:

| Statement | What happens |
|---|---|
| Classic `CALL gds.graph.project('g', 'Account', 'TRANSFERRED_TO')` | rejected fast with `42NG0` (the label/type form is not supported) |
| Full-graph Cypher projection (every transfer) | provisions a session whose long, silent provisioning trips the 60s Bolt read timeout (observed at ~240s) or is reset by the server |

`--read-timeout 0` lets the full projection survive past 60s to show the later server
reset. The full projection cannot be cancelled once started and can saturate the pool,
so run this on a clean instance.

## `gds-probe` demo

The fast-gds projection carries only labels and the relationship type; it never projects
`amount` or `transfer_timestamp` as graph properties. This demo isolates what happens when
you add properties: a GDS in-memory graph only accepts **numeric** property types, so it
sweeps a series of projections on a thin window (the timeout stays out of the picture),
adding one node or relationship property at a time, and reports which project and which the
server rejects. It first introspects the live schema and prints each property's type, then
runs:

| Scenario | Projection adds | Result |
|---|---|---|
| A_control | labels + `relationshipType` only | projects |
| B_rel_amount | `relationshipProperties { amount }` (float) + weighted PageRank | projects, weight usable |
| C_rel_timestamp | `relationshipProperties { transfer_timestamp }` (`DateTime`) | rejected fast |
| D_rel_both | `amount` + `transfer_timestamp` | rejected on the temporal one |
| E_node_numeric | a numeric node property on both endpoints | projects |
| F_node_nonnumeric | a string node property on both endpoints | rejected fast |

Each rejection comes back in under a second, before the session provisions, as
`IllegalArgumentException: The property ... contained a value of type DateTime/String,
which is not supported`. This is standard GDS typing, not a Virtual Graph defect: project
only numeric columns, and cast or drop temporal and string ones. See the modeling note in
[`gds-guide.md`](gds-guide.md). Use `--count-only` to introspect the schema without
provisioning, and `--since-hours` / `--since-days` to size the window.

## Support scripts

These standalone scripts probe and stress the Virtual Graph; they share the connection
helper in `src/connection.py` (reads the parent `.env`, or `PROBE_ENV` if set):

- `vg-probe` (`src/probe.py`): run a single ad-hoc Cypher statement and time it
  (`uv run vg-probe "<cypher>"`).
- `vg-heavy` (`src/heavy_run.py`): run the slow fraud queries sequentially with a
  per-query cap and a pool health check between each.
- `vg-viz` (`src/viz_check.py`): find real flagged accounts and confirm each anchored
  visualization renders small and fast.

## Notes

- **No write-back.** A Virtual Graph has no write-back to the relational source, so
  PageRank is streamed to the app rather than written to `Account` nodes. See
  [`gds-guide.md`](gds-guide.md).
- **Connection pool.** The Virtual Graph holds about 10 JDBC connections to Databricks
  and does not cancel a server-side query when the client gives up. Run on a clean
  instance, let each statement finish, and do not abandon a run. The full hazard and the
  performance rules are in [`best-practices.md`](best-practices.md).
- **Candidates, not verdicts.** These queries surface candidates, not confirmed fraud.
  See the interpretation caveats in [`finding-fraud.md`](finding-fraud.md).

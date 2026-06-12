# Creating a GDS Session on a Virtual Graph

This guide explains how to run Graph Data Science (GDS) algorithms against a Neo4j
Virtual Graph by creating a **GDS Session**.

## Background

GDS is **not** supported as an in-database plugin on Virtual Graph. The only way to
run graph algorithms is through **GDS Sessions** — an ephemeral, on-demand compute
environment that projects your data into an in-memory graph, runs algorithms, and can
be torn down afterward.

The working path is the **Cypher projection** form shown below. The classic label/type
`CALL gds.graph.project(...)` form does not work on Virtual Graph. For the
streamed-`nodeId` resolution gap and the Bolt read-timeout that makes large projections
fail, see [`gds-limitations.md`](gds-limitations.md).

## When you need GDS, and when plain Cypher is enough

Most local fraud signal can be expressed in plain Cypher over the base entities, so reach
for a GDS Session only when you need a global, transitive score. The table maps each GDS
algorithm to its plain-Cypher stand-in.

| Signal | GDS version | Plain-Cypher equivalent |
|---|---|---|
| Mule / hub detection | PageRank | Degree counting (local proxy) |
| Fraud ring discovery | WCC / Louvain | Bounded-depth connectivity, shared-merchant co-occurrence |
| Bridge / layering node | Betweenness | Pass-through pattern (receives then forwards) |
| Coordinated bursts | community + temporal | Same-merchant / same-window grouping |

What plain Cypher keeps: degree, reciprocity, cycles, fan-in/out, velocity, and
co-occurrence, the workhorses of rules-based fraud detection. What it loses is ranking
quality. PageRank weights a hub by the importance of who points at it, not just how many,
so it catches mules one layer removed from the obvious hubs. Louvain and WCC partition the
whole graph into rings rather than surfacing the fixed-shape patterns you anticipated.

The trade-off: plain Cypher gives fast, explainable, rules-based candidates, excellent for
triage and the "find the suspects" step. GDS gives the global scores that catch the rings
your rules did not think to look for. For the plain-Cypher forms of these signals, see
[`best-practices.md`](best-practices.md).

## The key: how a session gets created

A GDS Session is triggered by passing a **configuration** to `gds.graph.project` that
contains **either**:

- an **instance size** (memory in GB), e.g. `{ memory: '2GB' }`, **or**
- an existing **`sessionId`** to reuse a running session.

Without one of these, the call won't start a session.

## Recommended pattern: Cypher projection

On Virtual Graph, express the projection as a `MATCH ... RETURN gds.graph.project(...)`
statement rather than the label/type `CALL` form. The projection takes node and
relationship objects, with the label/type details carried in the `dataConfig`
parameter, and the memory/instance config supplied as the final argument.

```cypher
MATCH (person:Person)-[wrote:WROTE]->(movie:Movie)
RETURN gds.graph.project(
  'writersGraph',
  person,
  movie,
  {
    sourceNodeLabels: labels(person),
    targetNodeLabels: labels(movie),
    relationshipType: type(wrote)
  },
  { memory: '2GB' }
)
```

The first config object (`dataConfig`) describes the graph structure; the final config
object (`{ memory: '2GB' }`) is what provisions the session.

### Applied to a social graph

For a `USER`-`IS_FRIEND`-`USER` model, the equivalent projection looks like:

```cypher
MATCH (user:USER)-[friend:IS_FRIEND]->(:USER)
RETURN gds.graph.project(
  'socialGraph',
  user,
  friend,
  {
    sourceNodeLabels: labels(user),
    relationshipType: type(friend)
  },
  { memory: '2GB' }
)
```

## Project only numeric properties

The projections above carry only labels and the relationship type. If you also project
node or relationship **properties**, every projected property must be **numeric** (Long,
Double, or a numeric array). A GDS in-memory graph cannot hold a temporal or string
property, so adding one to the `dataConfig` makes the projection fail fast, before the
session provisions, with an `IllegalArgumentException` that names the offending property
and type:

```
The property `relationship.ts` contained a value of type `DateTime`, which is not supported.
The property `sourceNode.account_hash` contained a value of type `String`, which is not supported.
```

So `relationshipProperties: { amount: t.amount }` (a numeric column) projects and is
usable as a `relationshipWeightProperty`, while `relationshipProperties: { ts:
t.transfer_timestamp }` (a `DateTime`) is rejected. Project only the numeric columns you
need for the algorithm, and cast or drop temporal and string columns. The `gds-probe`
demo (`src/demos/gds_probe.py`, run with `uv run vg-demo --demo gds-probe`) sweeps these
property configs and prints which project and which are rejected. This is standard GDS
typing behavior, not specific to the Virtual Graph.

## Running an algorithm

Once the session and projection exist, run algorithms against the named graph:

```cypher
CALL gds.pageRank.stream('socialGraph')
YIELD nodeId, score
RETURN nodeId, score
ORDER BY score DESC
LIMIT 10
```

The standalone `CALL gds.<algorithm>.stream(...)` form works. The stream returns
GDS-internal `nodeId`s; resolving them back to `account_id`s is not reliable yet, so
stream the raw id and score. See [`gds-limitations.md`](gds-limitations.md).


## No write-back

There is **no write-back to the relational source** from a session. Options for
handling results include:

- Streaming results back to your application.
- Writing to a separate physical graph via a composite database.
- Writing to Parquet on a cloud bucket and feeding that back into the data warehouse.
- Keeping the session alive and serving from it as an ephemeral cache (re-create the
  projection if it expires).

For production GDS on Snowflake, the **GDS native app** is the intended path.

## Tested: the working path

A live test ran the Cypher projection form for PageRank over `Account` nodes and
`TRANSFERRED_TO` relationships against instance `ge224c32`, backed by a 2X-Small
Serverless Starter warehouse. The Sessions path works end to end: it provisions a
session, registers an in-memory graph, streams PageRank, and drops cleanly. The harness
is the `fast-gds` demo (`src/demos/gds_fast.py`, run with `uv run vg-demo --demo fast-gds`).

The "window" here is a time-range filter on the transfer rows: `--since-hours` /
`--since-days` keep only transfers from the most recent N hours or days of the data, and
the resulting row count is the edge count projected into the graph. Filtering to the most
recent 1.5 hours (233 transfers, so 233 edges) ran the full path successfully:

- Sizing count: 0.5s for 233 edges, no session.
- Projection that provisions the session: 128.8s, returning a registered graph of 438
  nodes and 233 relationships. The returned `projectMillis` was 127670, so almost the
  entire call is session provisioning. The Databricks data pull is sub-second, as
  separately confirmed in query history.
- `gds.pageRank.stream`: 2.5s for the top 10 accounts, with real scores.
- `gds.graph.drop`: about 1s.

The dominant cost is Aura Graph Analytics session provisioning, the cold start of the
ephemeral compute, not the Databricks query or the algorithm itself.

**Keep projections small.** A small projection is the reliable path today: the 233-edge
projection from the 1.5-hour window completed cleanly, and small projections provision
faster. A wider time window with more transfers can exceed the 60 second Bolt read timeout
during provisioning or hit a server reset, so scope the window until the projection
provisions reliably. Use `--count-only` to count the rows in a window for free and
`--keep` to reuse a provisioned session.

A later systematic sweep on the backing warehouse ran three projections per window. It put
the 233-edge projection at an ~88 s median, so the 128.8 s measured above was a colder
single sample, and it confirmed the projection step dominates and scales super-linearly:
about 1.5 minutes at 233 edges, 3.8 minutes at 986, and 6.2 minutes at 1,987, while a
~5,000-edge projection did not finish within 33 minutes and was stopped. Warehouse size made
no difference at any window. See [`perf-tests-results.md`](perf-tests-results.md), Test set B.

## Limitations and workarounds

The patterns above are the known working ones. For the GDS limitations on the Virtual
Graph, the streamed-`nodeId` resolution gap, and the full analysis of the 60 second Bolt
read timeout and server reset that affect large projections, along with workarounds,
see [`gds-limitations.md`](gds-limitations.md).

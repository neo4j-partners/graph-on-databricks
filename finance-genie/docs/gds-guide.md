# Creating a GDS Session on a Virtual Graph

This guide explains how to run Graph Data Science (GDS) algorithms against a Neo4j
Virtual Graph by creating a **GDS Session**.

## Background

GDS is **not** supported as an in-database plugin on Virtual Graph. The only way to
run graph algorithms is through **GDS Sessions** — an ephemeral, on-demand compute
environment that projects your data into an in-memory graph, runs algorithms, and can
be torn down afterward.

A few consequences of this:

- The label/type form of `gds.graph.project` (e.g. `CALL gds.graph.project('g', 'USER', 'IS_FRIEND')`) does **not** work on Virtual Graph today.
- The `CALL` form of the procedure isn't supported yet on Virtual Graph (support is planned for a later release). Use a **Cypher projection** instead.
- GDS does not currently work in Bloom for Virtual Graph.

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

## Running an algorithm

Once the session and projection exist, run algorithms against the named graph:

```cypher
CALL gds.pageRank.stream('socialGraph')
YIELD nodeId, score
RETURN nodeId, score
ORDER BY score DESC
LIMIT 10
```

The standalone `CALL gds.<algorithm>.stream(...)` form works. Note that chaining a
`CALL` directly into a follow-up `MATCH` (to resolve `nodeId` back to nodes) is not
something you should rely on working on Virtual Graph yet.

## What you can do with results

There is **no write-back to the relational source** from a session. Options for
handling results include:

- Streaming results back to your application.
- Writing to a separate physical graph via a composite database.
- Writing to Parquet on a cloud bucket and feeding that back into the data warehouse.
- Keeping the session alive and serving from it as an ephemeral cache (re-create the
  projection if it expires).

For production GDS on Snowflake, the **GDS native app** is the intended path.

## Known limitations / gotchas

- Label/type-based `gds.graph.project` is not yet supported on Virtual Graph — use the Cypher projection form above.
- The `CALL` form of procedures (and `WITH` subqueries) on Virtual Graph is planned for a future release.
- GDS does not work in Bloom for Virtual Graph at this time.
- Cypher projections may still hit edge-case bugs with certain relationship values; verify on your own schema.

## Tested on the finance-genie Virtual Graph, 2026-06-04

A live test ran the Cypher projection form for PageRank over `Account` nodes and
`TRANSFERRED_TO` relationships against instance `ge224c32`, backed by a 2X-Small
Serverless Starter warehouse. The Sessions path works end to end: it provisions a
session, registers an in-memory graph, streams PageRank, and drops cleanly. The harness
is `finance-genie/virtual-graph-demo/gds_pagerank.py`.

A 1.5 hour window of 233 transfers ran the full path successfully:

- Sizing count: 0.5s for 233 edges, no session.
- Projection that provisions the session: 128.8s, returning a registered graph of 438
  nodes and 233 relationships. The returned `projectMillis` was 127670, so almost the
  entire call is session provisioning. The Databricks data pull is sub-second, as
  separately confirmed in query history.
- `gds.pageRank.stream`: 2.5s for the top 10 accounts, with real scores.
- `gds.graph.drop`: about 1s.

The dominant cost is Aura Graph Analytics session provisioning, the cold start of the
ephemeral compute, not the Databricks query or the algorithm itself.

### The 60 second Bolt read timeout, and why larger projections fail

Scaling the window up exposed the real failure mode. A sweep of larger windows gave:

| window | edges | project result |
|--------|-------|----------------|
| 1.5h   | 233    | success, 128.8s |
| 36h    | 4,897  | connection read timeout |
| 72h    | 9,846  | connection read timeout, then a later attempt survived 6+ minutes |
| 109h   | 14,991 | connection read timeout |
| 145h   | 20,019 | survived 263s, then stopped manually |

There are two independent ways a long projection dies, and they stack.

The first surfaces client side as `Failed to read from defunct connection ...
TimeoutError('The read operation timed out')`. The cause is a Bolt connection hint: Aura
sends `connection.recv_timeout_seconds: 60`, and the Neo4j driver applies it as a 60
second socket read timeout, read directly off the live connection here. This is not a
total query budget. It trips when a single socket read waits more than 60 seconds with no
bytes from the server, meaning no data and no NOOP keepalive.

That explains the whole pattern. While the server streams keepalives with gaps under 60
seconds, the projection survives and total time can far exceed 60 seconds, which is why
233 edges finished at 128.8s and one 10,000 edge attempt ran past 6 minutes. When
provisioning hits a phase that goes silent for more than 60 seconds, the read trips and
the connection is declared defunct. So the trip is nondeterministic and depends on the
server keepalive cadence during provisioning, not strictly on edge volume.

The two earlier runs first recorded as hangs, 23,198 edges and roughly 300,000 edges
stopped after 16 and 29 minutes, are this same mechanism. They were stopped with
`driver.execute_query`, whose managed retry masked the read timeout as an apparent hang.
The plain `session.run` path used now surfaces it as a clean `TimeoutError`.

The second mechanism is a server side connection reset. Disabling the client read
timeout with `--read-timeout 0` was tested against the 10,000 edge window. The
connection then lived past 60 seconds, confirming the client trip was bypassed, but the
projection still failed, this time with `ConnectionResetError(54, 'Connection reset by
peer')` raised as `SessionExpired`, from an AWS fronted endpoint in front of the
graph-engine. So even with no client timeout, the server or an intermediary tears down a
long, silent provisioning, and the client cannot control that.

Both mechanisms are nondeterministic. A separate no-override probe on the same 10,000
edge window happened to survive past six minutes before it was stopped manually, while
the override run was reset earlier. The trip depends on the keepalive and reset cadence
during provisioning, not on a fixed wall-clock or strictly on edge volume.

### Workarounds

- There is no public driver config to raise this. The driver applies the server hint
  unconditionally in `hello()` for every Bolt version, and the only client timeout knobs
  are `connection_acquisition_timeout`, which governs pool checkout, and the per query
  `timeout`, which is a server side query deadline.
- The correct fix is server side, and it is the only one that addresses both mechanisms:
  Aura Graph Analytics should emit Bolt keepalives during session provisioning so neither
  the 60 second client read gap nor the server reset elapses. The driver log even advises
  checking that the server is set up correctly.
- The harness adds `--read-timeout` as an unsupported client workaround. It patches the
  sync `BoltSocket` to clamp or remove the read timeout before any connection opens, and
  `--read-timeout 0` disables it entirely. This is necessary but not sufficient: it only
  removes the client side trip. Testing showed a long provisioning then survives past 60
  seconds but can still be reset by the server, so it does not on its own make a large
  projection complete. A genuinely dead connection also blocks instead of erroring with
  the timeout off, so the flag is opt-in and never the default.
- The reliable path today is a small projection. The 233 edge window completed cleanly,
  and small projections provision faster, so they are far more likely to stay inside both
  the keepalive gap and the server reset window. Use `--count-only` to size the window for
  free and `--keep` to reuse a provisioned session.
- The classic in-database `CALL gds.graph.project('g','Account',...)` form still fails
  fast with `42NG0`. The Cypher projection Sessions form is the working path.

---
*Compiled from internal #team-graph-engine discussion (June 2026). Verify against the
current Neo4j Aura Graph Analytics / GDS Sessions documentation, as behavior is
actively changing.*

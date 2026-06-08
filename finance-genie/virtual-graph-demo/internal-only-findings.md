# Internal-only findings: graph-engine source vs. observed GDS failures

**Internal only. Do not send externally.** This references the private Neo4j
`graph-engine` source (`neo4j-field/neo4j/private/enterprise/graph-engine`) to
explain the mechanisms behind the behaviors documented in
[`gds-limitations.md`](gds-limitations.md). The customer-facing report stays in
`gds-limitations.md`; this file records what the source confirms so we do not
have to re-derive it.

The engine is the Cypher-to-SQL translation and runtime layer that backs the
Aura Virtual Graph. It is the component that runs the projection query against
the Databricks SQL warehouse and streams rows back over Bolt.

## Summary

| Observed behavior (gds-limitations.md) | What the source confirms |
|---|---|
| Mechanism 1: 60s Bolt read timeout from a silent gap | Confirmed and narrowed. The read path is blocking JDBC with no keepalive path. |
| `gds.util.asNode(nodeId)` cannot resolve a streamed id | The encode/decode asymmetry is real but does NOT explain this demo. `account_id` is an integer key, so the long-encode path applies. The failure points at GDS Session remote resolution instead. |
| Mechanism 2: server-side connection reset | Not in this repo. The gatekeeper sits in front of the engine. |

## 1. The silent gap is structural: blocking JDBC, zero keepalive

`runtime/src/main/scala/com/neo4j/graphengine/cypher/runtime/JdbcSlottedPipe.scala`
is the entire read path. It is a synchronous pull-based `ClosingIterator`. Two
lines carry the behavior:

- `JdbcSlottedPipe.scala:110` runs `resultSet = statement.executeQuery()` inside
  `initialize()`, which fires lazily on the first `innerHasNext`. This is a
  blocking JDBC call. For a GDS projection the translated SQL can be a heavy
  aggregation or join, and `executeQuery()` does not return until the warehouse
  has computed and is ready to hand back the first row.
- `JdbcSlottedPipe.scala:80` then calls `resultSet.next()` to pull rows one at a
  time, blocking on each call.

There is no NOOP, keepalive, or heartbeat anywhere in this pipe. No background
flush thread, nothing async. Between "SQL submitted" and "first row available"
the Bolt connection emits nothing. That silent stretch is exactly Mechanism 1's
60-second gap.

This narrows the customer-facing doc. `gds-limitations.md` says we know what
trips the failure but not why provisioning goes quiet, and attributes the quiet
to Aura session setup that is out of the client's view. The source shows the
quiet is not only session provisioning. It is also, and more durably, the
warehouse's compute-to-first-row latency on `executeQuery()`, during which the
engine has no code path that could send a keepalive. That is a design gap in
this pipe, not a hidden cause.

It also explains the nondeterminism. Row count loads the dice, since a bigger
SQL statement tends toward longer compute-to-first-row, but what actually trips
the timeout is whether any single gap crosses 60 seconds, which depends on
warehouse scheduling rather than edge volume.

## 2. The `gds.util.asNode` failure: the encode/decode asymmetry is real but does not explain this demo

There is a genuine encode/decode asymmetry in the engine, described below. But
after checking the actual schema, it does **not** account for the `asNode`
failure on the Finance Genie graph, because `account_id` is an integer key. Read
the "Verified against the schema" subsection before relying on this mechanism.

The encode and decode paths do not agree, and the id cache is never consulted on
decode.

**Encode** (`virtual-ids/src/main/java/com/neo4j/graphengine/virtual_ids/GlobalVirtualIdSourceProvider.java`,
the private `id(...)` helper): a node id is long-encoded only when the external
id is a single `IntegralValue` and the entity has a single integer-typed key.
The eligibility check is `LongIdEncoder.encodableIds` calling `hasSingleIntKey`,
which requires the key column to map to a property of type
`Entity.PropertyType.Integer`. Anything else falls back to
`CachingLongIdGenerator.assignId`.

**Decode** (`GlobalVirtualIdSourceProvider.decode(long, encoder)` via
`decodeNodeId`): consults only the `LongIdEncoder` bit math. The cache is never
queried on the way back.

**Why the fallback ids are unrecoverable**
(`virtual-ids/src/main/java/com/neo4j/graphengine/virtual_ids/LongIdEncoder.java`):

- `LongIdEncoder.java:14` sets `PREFIX = 1L << 62` on every long-encoded id, and
  `decodeSchemaId` / `decodeExternalId` reject anything that fails
  `isValidPrefix`.
- Generated ids come from `GENERATED_ID_MAX = (1L << 62) - 1` counting downward
  (`CachingLongIdGenerator.GeneratedLongIdLoader`). A generated id has bit 62 set
  to 0, so `isValidPrefix` fails, `decodeSchemaId` returns `INVALID_DECODE`, and
  `decodeNodeId` returns `Optional.empty()`.

So when the entity key is a string, composite, or any non-integer, every node id
is cache-generated and cannot be decoded, and `gds.util.asNode(nodeId)` can never
resolve it. That would be a deterministic 100% failure. The open question was
whether the Finance Genie `:Account` key falls into that bucket.

**Verified against the schema (it does not).** `account_id` is `BIGINT` and the
single-column primary key of `accounts` (`enrichment-pipeline/sql/schema.sql:16`
and `:23`), and the generator assigns plain integers `1..N`
(`enrichment-pipeline/setup/generate_data.py:155,167`). The `:Account` node is
keyed on `account_id` mapped from column `account_id`
(`virtual-graph-demo/VIRTUAL_GRAPH.md:98,107-108`). So both conditions of
`hasSingleIntKey` are met: a single key, and an integer (`BIGINT` →
`PropertyType.Integer`) type. The long-encode path applies, ids carry the
`PREFIX` bit, and `decodeNodeId` should succeed.

**Conclusion: the encode/decode asymmetry is not the cause of the observed
`asNode` failure on this graph.** Do not present the "non-integer key" rule as
the explanation for the Finance Genie demo. It remains a correct rule in
general, and a real trap for any future graph keyed on a string, hash, or
composite (for example, if a node were ever keyed on `account_hash` or `txn_id`
as a string), so it is worth documenting as a modeling constraint, just not as
the diagnosis here.

**Two caveats I could not close from the repo:**

- `hasSingleIntKey` also requires `account_id` to be retained as a *mapped
  Integer property* on `:Account`, not only as the ID. That mapping lives in the
  Aura data-source config / UI, which is not checked into this repo (searched,
  no saved data-source JSON or YAML). "Generate from schema" maps all columns by
  default, so it is very likely present, but it is not provable from code alone.
- The working path uses a detached **GDS Session** (Aura Graph Analytics,
  separate compute) with no write-back on a Virtual Graph
  (`virtual-graph-demo/src/demos/gds_fast.py:115-116`). The `nodeId` from
  `gds.pageRank.stream` is the session's internal id, and resolving it back
  through a virtual graph that has no write path is a GDS-Session concern,
  separate from the id bit-encoding. This is the more likely home of the real
  `asNode` failure and is where to look next.

**Second hazard for large projections:** the cache is bounded
(`Caffeine...maximumSize(cacheSize)`), and the class doc on
`GlobalVirtualIdSourceProvider` states ids are stable only as long as the cache
is not full. A projection larger than `cacheSize` can evict and reassign ids,
including for integer keys, so even decodable ids stop being stable past that
size. This is a separate failure mode from the timeout and worth noting if we
ever push projection sizes up.

## 3. What the source does not explain

Mechanism 2 (the `ConnectionResetError(54, 'Connection reset by peer')` surfaced
as `SessionExpired`) is not in this repo. The engine is the Cypher-to-SQL
translation and runtime layer. The gatekeeper that resets long-silent
connections sits in front of it (the Bolt gateway / AWS-fronted endpoint).
Nothing in `graph-engine` can emit a keepalive to satisfy that gatekeeper
either, but both the fix and the responsible component live outside this repo.
The customer-facing framing of Mechanism 2 as client-uncontrollable infra is
correct; the source simply cannot corroborate it.

## Bottom line

The "we see that it fails, not why it goes quiet" framing in
`gds-limitations.md` can be tightened on Mechanism 1, but the `asNode` finding
should stay as-is (or be investigated on the GDS Session side):

- Mechanism 1: the why is concrete. `JdbcSlottedPipe` blocks on `executeQuery()`
  and `next()` with no keepalive path, so warehouse compute-to-first-row latency
  produces the silent gap. Safe to sharpen in the customer doc.
- `asNode`: the encode/decode asymmetry is a real engine behavior but does NOT
  explain this demo, because `account_id` is an integer key (verified in the
  schema). Keep the customer doc's "not reliable" wording. The likely cause is
  GDS Session remote resolution, not id encoding; that is the next thing to
  probe. The "non-integer key breaks `asNode`" rule is still worth recording as
  a general modeling constraint, just not as the diagnosis here.
- Mechanism 2 remains correctly attributed to infra outside the engine.

---
*Internal working notes, compiled 2026-06-07 against the private graph-engine
source. Behavior is changing during the preview; re-verify file references
before relying on them.*

# GDS on Virtual Graph: what does not work

Findings from running Graph Data Science against a Neo4j Aura **Virtual Graph** during the
private preview. This is the companion to [`gds-guide.md`](gds-guide.md), which documents
the working GDS Session path. This document collects what does not work, so it can be sent
to Neo4j as a single report.

Scope is GDS only. The Virtual Graph Cypher coverage gaps (HAVING-style filters, temporal
arithmetic in `WHERE`, variable-length paths) are a separate topic and are documented in
[`best-practices.md`](best-practices.md).

## Test environment

- **Instance:** Aura Virtual Graph `ge224c32`.
- **Backing warehouse:** Databricks 2X-Small Serverless Starter SQL warehouse.
- **Data:** the Finance Genie Silver tables, `:Account` nodes and `TRANSFERRED_TO`
  relationships.
- **Harness:** the `fast-gds` and `slow-gds` demos (`src/demos/`, run with
  `uv run vg-demo --demo fast-gds` / `--demo slow-gds`).
- **Dates:** live runs on 2026-06-04, compiled from internal #team-graph-engine
  discussion in June 2026.

Behavior is actively changing during the preview, so verify each finding against the
current Aura Graph Analytics / GDS Sessions documentation.

## Summary

| Finding | Status |
|---|---|
| Resolving a streamed `nodeId` back to a node | Not reliable |
| Large Cypher projections | Fail nondeterministically (not strictly by size) on a 60s Bolt read timeout or a server reset |

The last finding is the significant one and is the bulk of this report.

## Other known gaps

- **A streamed `nodeId` cannot be mapped back to an account.** GDS algorithms run over the
  in-memory projection, where every node carries a GDS-internal integer id assigned at
  projection time. `gds.pageRank.stream` returns each row keyed by that `nodeId` and a
  `score`, not by the source `account_id`. The usual way to make the result actionable is
  to resolve each `nodeId` back to its node, for example
  `... YIELD nodeId, score WITH gds.util.asNode(nodeId) AS n, score RETURN n.account_id, score`,
  or by chaining the `CALL` into a follow-up `MATCH`. On the Virtual Graph that resolution
  is not reliable, so PageRank produces a ranking that cannot yet be attributed to specific
  accounts. The demo prints the raw internal id and score.


## The 60 second Bolt read timeout, and why larger projections fail

The working path provisions a session, registers an in-memory graph, streams PageRank, and
drops cleanly on a small projection. The "window" below is a time-range filter on the
transfer rows: each row count is how many transfers fall in the most recent N hours of the
data, and that row count is the edge count projected into the graph. Filtering to the most
recent 1.5 hours (233 transfers) ran the full path in about 132 seconds, almost all of it
session provisioning. Widening the time window, which lets in more transfers, exposed the
real failure mode.

A sweep of wider time windows gave the following. Each "time window" row keeps only the
transfers from that most-recent slice of the data ("last 36h" is the most recent 36 hours
of transfers), and the transfer count is the number of edges projected into the graph:

| time window | transfers (edges) | project result |
|-------------|-------------------|----------------|
| last 1.5h   | 233               | success, 128.8s |
| last 36h    | 4,897             | connection read timeout |
| last 72h    | 9,846             | connection read timeout, then a later attempt survived 6+ minutes |
| last 109h   | 14,991            | connection read timeout |
| last 145h   | 20,019            | survived 263s, then stopped manually |

There are two independent ways a long projection dies, and they stack.

### Mechanism 1: client-side Bolt read timeout

The first surfaces client side as `Failed to read from defunct connection ...
TimeoutError('The read operation timed out')`. The cause is a Bolt connection hint: Aura
sends `connection.recv_timeout_seconds: 60`, and the Neo4j driver applies it as a 60
second socket read timeout, read directly off the live connection here. This is not a
total query budget. It trips when a single socket read waits more than 60 seconds with no
bytes from the server, meaning no data and no NOOP keepalive.

We know what trips the failure, but not why. The error is a socket read timeout, so the
immediate cause is certain: a single gap of more than 60 seconds with no bytes from the
server. What we cannot see is *why* provisioning goes quiet, since that happens inside
Aura's session setup, out of the client's view.

That distinction explains the *observed* pattern, even though the root cause stays hidden.
As long as the server checks in with gaps under 60 seconds, the projection survives, and
total time can run well past 60 seconds. That is why 233 edges finished at 128.8s and one
10,000 edge attempt ran past 6 minutes. The moment a silent stretch crosses 60 seconds,
the read trips and the connection is declared defunct. Because it is the timing of those
gaps that matters, not the job size, the failure is nondeterministic: the same 10,000 edge
window failed once and survived past six minutes on a later attempt. Edge volume only
loads the dice, longer projections tend to have longer silent stretches, but it does not
decide the outcome.

The two earlier runs first recorded as hangs, 23,198 edges and roughly 300,000 edges
stopped after 16 and 29 minutes, are this same mechanism. They were stopped with
`driver.execute_query`, whose managed retry masked the read timeout as an apparent hang.
The plain `session.run` path used now surfaces it as a clean `TimeoutError`.

### Mechanism 2: server-side connection reset

In plain terms: even if you tell your own machine to wait forever, there is a gatekeeper
between you and the graph engine (an AWS-fronted endpoint). When a connection sits quiet
for a long time during provisioning, that gatekeeper decides it is stuck and cuts the
cord itself. You cannot turn this one off from the client.

The evidence: disabling the client read timeout (Mechanism 1) was tested against the
10,000 edge window. The connection then lived past 60 seconds, confirming the client trip
was bypassed, but the projection still failed, this time with
`ConnectionResetError(54, 'Connection reset by peer')` raised as `SessionExpired`, from
that AWS-fronted endpoint in front of the graph engine. So even with no client timeout,
the server or an intermediary tears down a long, silent provisioning, and the client
cannot control that.

As with Mechanism 1, we see *that* it gets reset, not *why* provisioning goes quiet long
enough to trigger it, that happens inside Aura. Both mechanisms are nondeterministic. A
separate no-override probe on the same 10,000 edge window happened to survive past six
minutes before it was stopped manually, while the override run was reset earlier. What
matters is the timing of the silent gaps during provisioning, not a fixed wall-clock and
not strictly the edge volume.

### Workarounds and the recommended fix

- **There is no public driver config to raise the client read timeout.** The driver
  applies the server hint unconditionally in `hello()` for every Bolt version. The only
  client timeout knobs are `connection_acquisition_timeout`, which governs pool checkout,
  and the per query `timeout`, which is a server side query deadline.
- **The correct fix is server side, and it is the only one that addresses both
  mechanisms.** Aura Graph Analytics should emit Bolt keepalives during session
  provisioning so neither the 60 second client read gap nor the server reset elapses. The
  driver log itself advises checking that the server is set up correctly.
- **A client-side read-timeout override is necessary but not sufficient.** The harness
  adds an unsupported `--read-timeout` workaround that patches the sync `BoltSocket` to
  clamp or remove the read timeout before any connection opens. It only removes the
  client-side trip; a long provisioning then survives past 60 seconds but can still be
  reset by the server. A genuinely dead connection also blocks instead of erroring with
  the timeout off, so the flag is opt-in and never the default.
- **The reliable path today is a small projection.** The 233-edge projection from the
  1.5-hour window completed cleanly, and small projections provision faster, so they are
  far more likely to stay inside both the keepalive gap and the server reset window. Use
  `--count-only` to count the rows in a time window for free and `--keep` to reuse a
  provisioned session.

---
*Compiled from internal #team-graph-engine discussion (June 2026). Verify against the
current Neo4j Aura Graph Analytics / GDS Sessions documentation, as behavior is actively
changing.*

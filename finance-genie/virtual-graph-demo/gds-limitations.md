# GDS on Virtual Graph: current limitations and findings

Findings from running Graph Data Science against a Neo4j Aura **Virtual Graph** and the current limitations.

## Test environment

- **Instance:** Aura Virtual Graph with 8 gb of Memory.
- **Backing warehouse:** Databricks 2X-Small Serverless Starter SQL warehouse. Tested with Larger SQL warehouses and did not find any performance improvements. 
- **Data:** the Finance Genie Silver tables, `:Account` nodes and `TRANSFERRED_TO`
  relationships.
- **Harness:** the `fast-gds` and `slow-gds` demos (`src/demos/`, run with
  `uv run vg-demo --demo fast-gds` / `--demo slow-gds`).

  
## Summary

| Finding | Status                              |
|---|-------------------------------------|
| Resolving a streamed `nodeId` back to a node | Does not resolve consistently today |
| Larger Cypher projections | Session provisioning times out as the edge count grows |


## Open questions

These are the current limitations without a known workaround. Feedback on use cases or
ways to handle them is welcome.

- **GDS stream results can't be attributed to specific accounts.** GDS algorithms return
  rows keyed by a GDS-internal `nodeId`, not by the source `account_id`, and this is the
  same across centrality scores, community ids, embeddings, and pathfinding output.
  PageRank is the worked example here: `gds.pageRank.stream` yields `nodeId` + `score`, and
  mapping that `nodeId` back to its node (`gds.util.asNode(nodeId)` or a follow-up `MATCH`)
  does not work consistently on the Virtual Graph today, so the output is a ranking of
  anonymous internal ids rather than accounts. The usual fallback, writing results back
  with `.write` mode, is also unavailable because the Virtual Graph is read-only. The demo
  prints the raw `nodeId` and score.


## Session provisioning timeouts as the projection grows

The graph is built with the Cypher-projection form of `gds.graph.project(...)`, and the
`{ memory }` argument on that call provisions a GDS Session. The two are one statement: the
same call starts the session and projects the subgraph. The failure below is the session
provisioning timing out, not a projection-memory limit, and the projected edge count is what
drives how long provisioning stays silent.

Aura sends a 60s Bolt read-timeout hint with no keepalive during provisioning, so once the
edge count pushes the silent provisioning wait past 60s the driver declares the connection
dead and the projection dies mid-flight. The demo can raise or remove that client-side
timeout with `--read-timeout`, but a long provision can still be reset by the server, so this
is necessary but not sufficient.

The working path provisions a session, registers an in-memory graph, streams PageRank, and
drops cleanly on a small projection. The "window" below is a time-range filter on the
transfer rows: each row count is how many transfers fall in the most recent N hours of the
data, and that row count is the edge count projected into the graph. Filtering to the most
recent 1.5 hours (233 transfers) ran the full path in about 132 seconds, almost all of it
session provisioning. Widening the time window lets in more transfers, raising the edge
count, and that is where provisioning stays silent long enough to trip the timeout.

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

This sweep was single attempts; several rows are inconclusive ("survived" means it had not
timed out when stopped, not that it completed). A later systematic sweep, three runs per
window, put the 233-edge projection at an ~88 s median, so the 128.8 s above was a colder
single sample, and pinned the growth curve below the timeout: about 3.8 minutes at 986 edges
and 6.2 minutes at 1,987, with a ~5,000-edge projection that did not finish within 33
minutes. Warehouse size made no difference at any window. See
[`perf-tests-results.md`](perf-tests-results.md), Test set B.

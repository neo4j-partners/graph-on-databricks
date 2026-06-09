# GDS on Virtual Graph: current limitations and findings

Findings from running Graph Data Science against a Neo4j Aura **Virtual Graph** and the limitations I hit.

## Test environment

- **Instance:** Aura Virtual Graph `ge224c32`.
- **Backing warehouse:** Databricks 2X-Small Serverless Starter SQL warehouse.
- **Data:** the Finance Genie Silver tables, `:Account` nodes and `TRANSFERRED_TO`
  relationships.
- **Harness:** the `fast-gds` and `slow-gds` demos (`src/demos/`, run with
  `uv run vg-demo --demo fast-gds` / `--demo slow-gds`).

  
## Summary

| Finding | Status |
|---|---|
| Resolving a streamed `nodeId` back to a node | Does not resolve consistently today |
| Larger Cypher projections | May time out during provisioning (not strictly by size) |


## Open questions

These are the limitations I have not found a way around. Guidance on how to handle them
would be welcome.

- **GDS stream results can't be attributed to specific accounts.** GDS algorithms return
  rows keyed by a GDS-internal `nodeId`, not by the source `account_id`, and this is the
  same across centrality scores, community ids, embeddings, and pathfinding output.
  PageRank is the worked example here: `gds.pageRank.stream` yields `nodeId` + `score`, and
  mapping that `nodeId` back to its node (`gds.util.asNode(nodeId)` or a follow-up `MATCH`)
  does not work consistently on the Virtual Graph today, so the output is a ranking of
  anonymous internal ids rather than accounts. The usual fallback, writing results back
  with `.write` mode, is also unavailable because the Virtual Graph is read-only. The demo
  prints the raw `nodeId` and score.


## Projection size and provisioning timeouts

The working path provisions a session, registers an in-memory graph, streams PageRank, and
drops cleanly on a small projection. The "window" below is a time-range filter on the
transfer rows: each row count is how many transfers fall in the most recent N hours of the
data, and that row count is the edge count projected into the graph. Filtering to the most
recent 1.5 hours (233 transfers) ran the full path in about 132 seconds, almost all of it
session provisioning. Widening the time window, which lets in more transfers, is where
larger projections begin to time out during provisioning.

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

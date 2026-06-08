# GDS on Virtual Graph: current limitations and findings

Findings from running Graph Data Science against a Neo4j Aura **Virtual Graph** during the
private preview. This is the companion to [`gds-guide.md`](gds-guide.md), which documents
the working GDS Session path. This document collects the limitations we hit, to share with
the Neo4j team as preview feedback. As an early-access preview, some rough edges are
expected, and several of these may already be in progress.

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
| Resolving a streamed `nodeId` back to a node | Does not resolve consistently today |
| Larger Cypher projections | May time out during provisioning (not strictly by size) |

The second finding is the more significant one and is the focus of this document.

## Other known gaps

- **A streamed `nodeId` cannot be mapped back to an account.** GDS algorithms run over the
  in-memory projection, where every node carries a GDS-internal integer id assigned at
  projection time. `gds.pageRank.stream` returns each row keyed by that `nodeId` and a
  `score`, not by the source `account_id`. The usual way to make the result actionable is
  to resolve each `nodeId` back to its node, for example
  `... YIELD nodeId, score WITH gds.util.asNode(nodeId) AS n, score RETURN n.account_id, score`,
  or by chaining the `CALL` into a follow-up `MATCH`. On the Virtual Graph that resolution
  is not consistent today, so PageRank produces a ranking that cannot yet be attributed to
  specific accounts. The demo prints the raw internal id and score.


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

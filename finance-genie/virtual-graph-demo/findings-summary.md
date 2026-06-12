# Virtual Graph on Databricks: Condensed Findings

A short summary of what we measured running Neo4j Aura Virtual Graph over data in a
Databricks SQL warehouse. Each finding points to the source document for the full method,
timings, and captured SQL:

- Warehouse sizing and workload timing: [`perf-tests-results.md`](test-results/perf-tests-results.md)
- 100K to 100M row stress ramp: [`perf-tests-results-v2.md`](test-results/perf-tests-results-v2.md)
- Pushdown vs. engine-side behavior and captured SQL: [`verify-best.md`](test-results/verify-best.md)

The dataset is a synthetic finance graph: an `accounts` table and a 300,000-row
`account_links` table of account-to-account transfers, mapped as `TRANSFERRED_TO`. The live
transfers table is a single ~4 MB file.

---

## Bottom line

Across every workload tested, the Databricks warehouse finished its share of the work in
well under a second and never spilled. The wall-clock cost lived on the Aura side: shipping
result rows, building GDS graphs, and per-value timezone round trips. Slow queries were slow
because of how Cypher translated to SQL, not because of warehouse compute.

---

## Warehouse sizing

Moving the warehouse from 2X-Small up to Small produced no measurable change on any tested
workload.

- **Aggregation queries are a tie at every window.** The "who paid whom" pair aggregation
  matched within run-to-run noise on both sizes; Databricks finished each query in ~0.2 s
  regardless of result size. `[perf-tests-results.md -> Test set A, Phases 1-2]`
- **Zero spill from 100K to 100M rows.** At 100M rows / ~1.07 GB / ~95M distinct aggregate
  groups the 2X-Small built the full hash aggregate in memory with `spilled_local_bytes = 0`.
  `[perf-tests-results-v2.md -> Spike 1 results]`
- **The only real warehouse compute floor is a high-cardinality pair group-by.** That query
  scaled from 455 ms at 1M rows to 5,234 ms at 100M, reading the full table each time. Every
  other shape stayed sub-second through cache-serving or partition pruning.
  `[perf-tests-results-v2.md -> Spike 1 results]`

---

## GDS limitations

PageRank cost lives entirely in the Neo4j GDS Session, not the warehouse.

- **PageRank is insensitive to warehouse size.** The only warehouse query is a ~0.4 s edge
  count; the in-memory graph build runs in a Neo4j GDS Session that never touches the
  warehouse, so 2X-Small and Small tie. `[perf-tests-results.md -> Test set B, Phases 3-4]`
- **The GDS graph-build step dominates and scales super-linearly.** The build was ~99% of
  total time: ~1.5 min at 233 edges, ~3.8 min at 986, ~6.2 min at 1,987, and a ~5,000-edge
  build did not finish within ~33 minutes when it was stopped. The other steps (size, stream,
  drop) stayed under 4 s regardless of window. `[perf-tests-results.md -> Test set B,
  extension]`

---

## The timezone round-trip

The single largest slow path found. When a result carries TIMESTAMP values, the engine makes a
separate round trip to the warehouse for every one of them. A query that returns N rows with a
timestamp fires N `SELECT current_timezone()` statements, one per row, run serially at about
5.5 per second.

- **The calls are per row, not per query.** Returning 25 timestamp-bearing rows fired exactly
  25 `current_timezone()` calls; a 3,331-row pull fired 3,331. There is no batching.
  `[verify-best.md -> Phases 5, 9]`
- **The trigger is the TIMESTAMP value itself, not the query shape.** Each TIMESTAMP the engine
  materializes into a Cypher datetime costs one round trip, whether it rides in a relationship,
  a node property, or a bare projected column. DATE values cost nothing.
  `[verify-best.md -> Phase 9]`
- **No caching.** The engine never reuses the answer, so every value pays every time;
  back-to-back reruns of the same 25-row query each fired 25 calls. `[verify-best.md -> Phase 9]`
- **This is what dominates wall-clock, not warehouse compute.** The 3,331-row node-grouped pull
  finished in 738 ms on the warehouse, then spent ~10 minutes on the 3,331 serial timezone
  calls. `[verify-best.md -> Phase 5]`

---

## What pushes down to the warehouse

These shapes translate to a single pushed SQL statement that filters or bounds before rows
move.

- **UNION ALL runs as one Cypher statement, two pushed SQL statements.** A two-label count
  combined with `UNION ALL` returned correct counts; the engine submitted one count statement
  per branch and concatenated the results itself. `[verify-best.md -> Phase 6]`
- **Row-level filters push down as bound parameters.** A time window becomes
  `WHERE transfer_timestamp >= ?`; an amount range becomes `WHERE (amount >= ?) AND (amount < ?)`,
  with the `GROUP BY` pushed alongside, so only the final groups ship.
  `[verify-best.md -> Phases 3, 4]`
- **An anchor pushes down as a selective filter.** An anchored traversal generates
  `WHERE (a.account_id = ?)`, and the warehouse produces only that node's edges.
  `[verify-best.md -> Phase 3]`
- **LIMIT pushes down on plain traversals at every depth tried.** Single-hop, two-hop, and
  four-hop unanchored traversals each emitted `LIMIT ?` and produced exactly 25 rows. The
  limit bounds the output, not the join work: warehouse time still grew from 0.9 s to 13.5 s
  across one to four hops. `[verify-best.md -> Phase 7]`

---

## What stays engine-side

These shapes do not push their aggregation, ordering, or limiting into SQL. The warehouse
receives a raw or full-group pull and the engine does the rest.

- **ORDER BY and LIMIT do not push down on an aggregation.** All five fan-out variants
  generated byte-identical SQL with no `ORDER BY` and no `LIMIT`; the warehouse produced the
  full 22,096 groups every time and the engine sorted and trimmed afterward. The top-N is
  still fast because only the trimmed rows cross the engine-to-client leg.
  `[verify-best.md -> Phase 1]`
- **count(DISTINCT) always materializes.** The generated SQL carries no `DISTINCT` and no
  `GROUP BY`; the warehouse ships a raw join pull and the engine deduplicates and counts.
  Cost scales with window size: 4.6 s on a 1-day window, past 5 minutes on 7 days.
  `[verify-best.md -> Phase 5]`
- **Grouping by a node materializes.** The node-grouped form sends a raw row pull with no
  `GROUP BY`; the engine aggregates client-side. It returns results identical to the
  key-grouped form, which does push down. `[verify-best.md -> Phases 4, 5]`
- **A post-aggregation threshold fails to parse.** Adding a `WHERE` after an aggregating
  `WITH` raises `Neo.ClientError.Statement.SyntaxError`, GQL `42NG0: Unsupported syntax`, at
  parse time; nothing reaches the warehouse. `[verify-best.md -> Phase 2]`

---

## Workload ceilings

Where the aggregation workload's cost actually grows.

- **Aggregation wall-clock tracks rows returned.** The pair query rose from ~1 s at 3,303
  rows to ~27 s at 222,966 rows, ~0.12 ms per row above a ~1 s floor, all of it Aura-to-client
  data movement. Narrowing the window is the lever. `[perf-tests-results.md -> Test set A]`

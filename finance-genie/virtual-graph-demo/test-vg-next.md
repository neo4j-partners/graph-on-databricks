SHOW TRANSACTIONS
YIELD transactionId, currentQuery
WHERE currentQuery CONTAINS 'velocity_ratio'
TERMINATE TRANSACTIONS transactionId
YIELD transactionId AS txId, message
RETURN txId, message



# Virtual Graph testing: status and next steps

Working notes for the `virtual-graph-demo` harness against the finance-genie Aura
Virtual Graph. The Virtual Graph translates Cypher to SQL and runs it on a backing
Databricks SQL warehouse. Connection comes from the parent `finance-genie/.env`.

## Progress log

Live run on 2026-06-03 against instance `ge990841` (backing warehouse
`high-cost-high-performance`, **Small**, serverless off). One query at a time.

- **Step 1 done.** Clean state confirmed. `RETURN 1` 2.6s, `count(Account)` 25000 in
  3.9s, no HikariPool error.
- **Step 2 done, current size is Small.**
  - Q4 reciprocal: completes, **54s** wall (about 46s of query after the ~8s connect
    plus two startup metadata probes), 21052 rows. Slower than the old ~8s number,
    which came from a larger instance.
  - Q7 structuring: completes, **58s** wall. 196 aggregated rows, **0 pass** the
    `near_threshold>=3` filter, so no account has 3+ just-under-threshold transfers.
  - Q11 velocity ratio: **did not finish, killed at ~290s** on Small. A single-hop
    `sum` group was expected to behave like Q7 but is far slower here. Reclassified
    from "likely slow but completes" to "needs bigger warehouse" on Small.
  - Pool note: abandoning Q11 once did not saturate the pool. `RETURN 1` was still
    2.4s afterward. One abandoned query holds at most one of the ~10 slots.
- **Takeaway for steps 3 to 7:** the heavy queries are not practical on Small and
  will be abandoned at the client timeout, which risks pool saturation. Scale the
  warehouse up first, then run them.
- **Heavy-query measurement, 10-min cap on Small.**
  - Driver note: `driver.execute_query` wraps the query in a retrying managed
    transaction, so a socket read timeout makes it silently re-run the expensive
    query and spawn another server-side query. Use an explicit `session.run` for
    long queries. With that, the Bolt connection stays alive well past 600s, so the
    earlier "socket read timeout" was a retry artifact, not a hard connection limit.
  - Q11 velocity ratio: ran the **full 600s without finishing** (abandoned at the
    cap). It is a single-hop unwindowed `sum` group, one of the cheaper heavy
    queries, so the `count(DISTINCT)` and 2-hop queries will also exceed 10 min on
    Small. Conclusion: heavy queries do not complete within 10 minutes on Small.
  - Pool degradation observed: `RETURN 1` rose from ~2s (fresh) to 8.4s then 12.3s
    as abandoned Q11s kept running server-side on the Small warehouse. Each abandoned
    10-min query holds a slot and burns warehouse compute, slowing everything.
  - Open and promising: the **windowed** queries prune the data hard before
    aggregating and may still complete on Small. Q1 fan-in uses a 7-day transfer
    window, Q8 new-account uses a 30-day opened window. These are the best
    candidates to verify next, on a clean (drained or restarted) instance.

## Current status

- The demo connects, reads the schema, and runs queries. Labels are `:Account` and
  `:Merchant`. Relationship properties are mapped: `TRANSFERRED_TO` has `amount`,
  `transfer_timestamp`, `link_id`; `TRANSACTED_WITH` has `amount`, `txn_timestamp`,
  `txn_hour`, `txn_id`.
- `queries.py` holds Virtual-Graph-adapted versions of all 12 examples. The
  adaptations are: threshold filters applied client-side, time windows passed as a
  `$since` parameter anchored to `max(transfer_timestamp)`, multi-hop duration windows
  dropped, and node-property predicates moved to a leading `WHERE`.
- Cypher coverage is mapped and stable. See the support matrix in
  `../docs/plain-cypher-examples.md` Section B.
- The blocker is performance and the connection pool, not Cypher. Heavy aggregations
  did not finish, and abandoned queries saturated the Virtual Graph connection pool.

## Connection pool behavior, read before testing

- The Virtual Graph holds about 10 JDBC connections to Databricks.
- Killing or abandoning a slow query on the client does not cancel the Databricks
  query. It keeps running and holds a pool slot until it finishes server-side.
- A few abandoned slow queries saturate the pool. After that every query fails with
  `Neo.DatabaseError.Statement.ExecutionFailed: HikariPool-1 - Connection is not
  available, request timed out after 30000ms (total=10, active=10, idle=0)`.
- The Bolt transaction timeout is not honored, so there is no clean server-side cancel.
- Testing rules: run one query at a time, let each finish, never abandon. Do not wrap
  runs in an OS timeout that kills the process, and do not use thread caps that move
  on while the query still runs. Treat the HikariPool error as the saturation signal,
  and restart or resize the instance to recover.

## Query speed classification

Timings are provisional. Many were confounded by pool saturation, so re-measure on a
clean instance one query at a time.

All timings below are on the **Small** warehouse, one query at a time. "Verified"
means measured cleanly this session. The rest are unverified or known to exceed the
10-min cap.

| Query | Shape | Observed on Small | Class |
|---|---|---|---|
| baseline `RETURN 1` | none | ~2 to 3s fresh | verified fast |
| baseline `count` 25k nodes | scan | ~4s | verified fast |
| baseline `max(timestamp)` | scan agg | ~1 to 2s | verified fast |
| Q4 reciprocal | self-join, `count`/`sum` | **~54s, 21052 rows** | verified, completes |
| Q7 structuring | single-hop, amount filter, `count` | **~58s, 0 pass thresh 3** | verified, completes (threshold too high) |
| Q1 fan-in | single-hop, `count(DISTINCT)` + 7-day window | not yet verified | windowed, best candidate to test next on Small |
| Q8 new-account velocity | single-hop, 30-day opened window | not yet verified | windowed, best candidate to test next on Small |
| Q11 velocity ratio | single-hop, unwindowed `sum` | **did not finish in 600s** | does not complete in 10 min on Small |
| Q2 fan-out | single-hop, unwindowed `count(DISTINCT)` | not verified | expected > 10 min on Small |
| Q9 hub stats | `count(DISTINCT)` + OPTIONAL MATCH | not verified | expected > 10 min on Small |
| Q12 P2P vs merchant | undirected + OPTIONAL MATCH + `count(DISTINCT)` | not verified | expected > 10 min on Small; also unverified: undirected pattern |
| Q3 pass-through | 2-hop join | not verified | expected > 10 min on Small |
| Q10 rapid turnover | 2-hop join, unbounded | not verified | expected > 10 min on Small |
| Q6 shared-merchant burst | `collect(DISTINCT)` + `date()` grouping | not verified | expected > 10 min on Small; also unverified: date()+collect |
| Q5 layering cycles | variable-length path | n/a | unsupported on Virtual Graph |

Summary:
- Verified to complete on Small: Q4 (~54s) and Q7 (~58s, but 0 rows pass the
  threshold of 3), plus the baselines.
- Verified NOT to complete on Small: Q11 ran the full 600s without finishing. Since
  it is a cheap single-hop query, the `count(DISTINCT)` and 2-hop queries are
  expected to exceed 10 min on Small too.
- Best untested candidates on Small: the windowed queries Q1 (7-day) and Q8 (30-day),
  which prune the data hard before aggregating.
- Needs a bigger or faster SQL warehouse to be practical: Q2, Q9, Q12, Q3, Q6, Q10,
  and Q11.
- Unsupported regardless of warehouse: Q5.

## Recommendations and what to test next

Current recommendation, in order:

1. **Clear the runaway queries first.** Several abandoned 10-min Q11 runs are still
   executing on the Small warehouse and holding pool slots, so `RETURN 1` has slowed
   from ~2s to ~12s. Test on a clean warehouse, not this loaded one. Cleanest ways to
   recover: restart or resize the Virtual Graph instance, or look up the runaway
   queries in Databricks query history and cancel them directly.
2. **On Small, test only the windowed queries Q1 and Q8, one at a time.** They are the
   only heavy queries with a real chance of completing on Small, and they cover strong
   fraud signals (collection accounts, new-account velocity). Stop immediately if
   either exceeds the cap or the pool degrades.
3. **For everything else, use a bigger or faster warehouse.** Q11 proved that an
   unwindowed single-hop aggregation exceeds 10 min on Small, so Q2, Q9, Q12, Q3, Q6,
   Q10 will too. On a larger warehouse, measure each one at a time and record the size
   where it returns within an acceptable bound.
4. While on the larger warehouse, settle the two open Cypher questions that were never
   measured cleanly: Q12 undirected `-[tr:TRANSFERRED_TO]-` support, and Q6
   `date(t.txn_timestamp)` grouping with `collect(DISTINCT ...)`.
5. Isolate the `count(DISTINCT)` cost: compare a plain `count` group against a
   `count(DISTINCT)` group on a clean instance to confirm DISTINCT is the driver.
6. Decide the demo story and defaults from what is actually verified. Today that is
   Q4 and Q7; if Q1 and Q8 complete on Small, the verified set grows to four. See
   `finding-fraud.md` for the narrative.

Driver and harness notes:
- Use an explicit `session.run` for long queries, not `driver.execute_query`. The
  latter wraps the query in a retrying managed transaction, so a socket read timeout
  silently re-runs the expensive query and spawns another server-side query. With an
  explicit `session.run` the Bolt connection stays alive past 600s.
- `heavy_run.py` runs the heavy queries one at a time with a 600s cap, a `--only N`
  flag, and a `RETURN 1` health check that stops the batch if the pool degrades.
- Consider dropping the unhonored `--timeout` flag from `main.py` so the harness never
  looks like it can abandon a query server-side.

## How to run

```bash
cd virtual-graph-demo
uv run main.py --query 4            # one query, lets it finish
uv run main.py --rows 5            # all supported queries, sequential
uv run main.py --all               # also attempt the unsupported cycles query
```

Run a single query at a time while characterizing performance.

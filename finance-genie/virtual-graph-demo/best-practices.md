# Virtual Graph Best Practices

How to write Cypher that runs well on the Finance Genie Virtual Graph. Aura
compiles Cypher into SQL and pushes most of the work down to the backing Databricks SQL
warehouse, so the rules here are about helping that translation push work down to
Databricks instead of dragging rows back to the graph engine.

The working fraud queries this guide draws on are the demo set in
[`finding-fraud.md`](finding-fraud.md); the warm-up and visualization queries are in
[`basic-graph-examples.md`](basic-graph-examples.md). This document is the reference
for *why* those queries are shaped the way they are, and what to do when a standard
Cypher query will not run.

## How the Virtual Graph works

- **Translation.** Most of a Cypher query becomes SQL over Databricks, with
  graph-specific work handled by the engine. Only a subset of Cypher is
  supported, so a query written for a loaded Aura graph rarely runs verbatim. The
  reference forms in the appendix show the gap.
- **The shared query shape.** Filter and group on the server, order and limit in Cypher,
  apply the threshold filter in your application. Row-level filters such as a time window,
  an amount range, or an account-id anchor, together with a `GROUP BY` on a key column,
  push down to Databricks. `ORDER BY` runs in the graph engine rather than the warehouse,
  but is still worth writing. Only the HAVING-style threshold on an aggregate alias has to
  move to the application. Almost every adaptation in this guide is a consequence of that
  split.
- **Property mapping.** Relationship and node properties exist only if they were mapped
  from a backing table column in the Aura model. An unmapped column leaves the
  relationship in place with zero properties, and any query touching it fails with
  "Could not resolve property".
- **Labels.** This model uses singular `:Account` and `:Merchant`. A model generated
  from table names may use `:accounts` and `:merchants` instead. Match your model.
  - `TRANSFERRED_TO` (`:Account` → `:Account`): `amount`, `transfer_timestamp`, `link_id`.
  - `TRANSACTED_WITH` (`:Account` → `:Merchant`): `amount`, `txn_timestamp`, `txn_hour`, `txn_id`.

The patterns in this guide change timings by orders of magnitude, so query shape is the
first thing to get right. The absolute seconds for any given query also depend on the
warehouse size and the connection pool, so treat the numbers here as rough and
directional.

## What governs performance

Performance comes down to three cost centers plus the machine everything runs on. A few
terms used throughout:

- **Scalar:** a single plain value such as an `account_id`, as opposed to a whole node object.
- **Node:** a full graph object such as an `:Account`, carrying all its properties.
- **Pushdown:** letting Databricks do the counting and summing. This is the fast path.
- **Materialize:** the graph engine pulls every matching row back to itself first, then
  counts. This is the slow path.
- **Cardinality:** how many rows. High cardinality means a lot of rows.

**Cost center 1, where the math happens.** Who does the counting and summing, Databricks
(fast) or the graph engine (slow). The patterns below all move this work to Databricks.

**Cost center 2, how much data moves.** Every result row travels back over the wire.
This bites even when cost center 1 is perfect.

**Cost center 3, the timezone round trip.** Every `TIMESTAMP` value the engine
materializes into a Cypher datetime costs one extra round trip to the warehouse, with no
caching. At bulk row counts this dwarfs the other two and is the single biggest slow path
found. See [Pattern 7](#pattern-7-keep-timestamps-out-of-bulk-results).

**The machine underneath.** Once the query shape is right, the absolute wall-clock time
also depends on the warehouse size and the connection pool, covered under
[Performance and the connection pool](#performance-and-the-connection-pool).

The next sections are the patterns. Each one is stated once, with the worked example
that measured it.

### Pattern 1: group by a scalar, not a node

The biggest lever. Group by `a.account_id` (one value) and Databricks does the
aggregation. Group by `a` (the whole node) and the graph engine drags every row home and
aggregates by hand for the same answer.

- **Structuring (just-under-threshold transfers).** Grouping by scalar `src.account_id`
  pushes the `GROUP BY` down to the warehouse, about 1s. Grouping by the `src` node
  materializes, about 38s, and the console warns about a "post-processing step that
  materializes intermediate results". Dropping the trailing `(:Account)` label or the
  `round()` wrapper changed nothing. Only the group key mattered.

  ```cypher
  MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
  WHERE t.amount >= 9000 AND t.amount < 10000
  WITH src.account_id AS account_id, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
  RETURN account_id, near_threshold, total
  ORDER BY near_threshold DESC
  ```

- **New account, high velocity.** The clearest single measurement. Grouping by scalar
  `a.account_id` and carrying `a.opened_date` and `a.holder_age` as extra grouping keys,
  which are constant per account, ran in about 1s. The node-grouped form `WITH a, count(t) ...`
  took about 985s for the identical result. The captured SQL shows why: the node-grouped
  form sends a raw row pull with no `GROUP BY`, which the warehouse finishes in under a
  second, and then the engine pays one timezone round trip per pulled row because the raw
  pull drags `transfer_timestamp` along. Those round trips, not the aggregation, are almost
  all of the 985s; see [Pattern 7](#pattern-7-keep-timestamps-out-of-bulk-results). A
  controlled rerun confirmed the two forms return identical results to the cent, so grouping
  by the scalar key loses nothing.

  ```cypher
  MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
  WHERE a.opened_date >= date("2022-11-06")
  WITH a.account_id AS account_id, a.opened_date AS opened_date,
       a.holder_age AS holder_age, count(t) AS transfers, sum(t.amount) AS outflow
  RETURN account_id, opened_date, holder_age, transfers, outflow
  ```

Carry any constant node property you need (balance, opened date) as an additional scalar
grouping key rather than grouping by the node to keep it.

### Pattern 2: replace count(DISTINCT) with pair-grouping

`count(DISTINCT x)` is its own trap, separate from the node-versus-scalar one. It never
pushes down, even with a clean scalar group key: the captured SQL is a raw join pull with
no `DISTINCT` and no `GROUP BY`, and the engine deduplicates and counts itself. Whether it
finishes is a matter of window size, not luck. `count(DISTINCT dst.account_id)` grouped by
`src.account_id` ran past 5 minutes on a 7-day window but finished in about 4.6s on a
1-day window.

The fix is to group by the pair on the server, then count the groups in your
application. A plain `GROUP BY` over the pair dedupes it and needs no `DISTINCT`.

- **Fan-in by distinct senders.** Group by `(dst.account_id, src.account_id)`. The
  server returns one row per sender-recipient pair, about 22,000 rows for the 7-day
  window in about 3.7s. The row count per recipient is the distinct-sender count.

  ```cypher
  MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
  WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
  WITH dst.account_id AS recipient, src.account_id AS sender,
       count(t) AS legs, sum(t.amount) AS pair_amount
  RETURN recipient, sender, legs, pair_amount
  ```

  Client-side: group by `recipient`, the row count per recipient is the distinct-sender
  count, sum `legs` for transfers and `pair_amount` for inflow.

- **Fan-out by distinct recipients** is the mirror: group by `(src.account_id, dst.account_id)`,
  then count rows per `sender`.

This is the standard way to recover any `count(DISTINCT x)` that will not push down: group
by `x` on the server, count the groups in the application. The same pair dataset also
feeds hub statistics (in-degree, out-degree, incoming transfer count) with no dedicated
hub query.

**Aliasing rule.** Give the two endpoints distinct aliases such as `recipient` and
`sender`. Aliasing both to `account_id` collides in the generated SQL and fails with
`AMBIGUOUS_REFERENCE`. The `TRANSACTED_WITH` backing table also exposes its own
`account_id` column, so on the merchant side you cannot alias the group key to
`account_id` either; alias to something else and rename in `RETURN`.

### Pattern 3: write ORDER BY and LIMIT in Cypher; keep only the threshold client-side

`ORDER BY` and `LIMIT` never reach the warehouse on an aggregation. The captured SQL is
byte-identical with or without them, and the warehouse produces the full group set every
time; the graph engine sorts and trims afterward as a post-processing step. At tens of
thousands of grouped rows that step is free: a sorted run took the same ~3.4s as the
unsorted control, and the engine trim happens before the slow engine-to-client leg, so a
top-N still returned in 0.7s against 3.4s for the full result. So write the `ORDER BY` and
the `LIMIT` in Cypher. Neither reduces warehouse work, but together they give a correct,
cheap top-N. Only a filter or an anchor reduces warehouse work, never a `LIMIT` on an
aggregation.

The one thing that has to stay client-side is the HAVING-style threshold: a `WHERE` on an
aggregate alias is not supported at all and fails at parse time (see
[Cypher coverage](#cypher-coverage)). The shape that runs is `MATCH ... WITH <aggregates>
... RETURN ... ORDER BY <aggregate> DESC LIMIT <n>` with no post-`WITH` `WHERE`. Apply the
threshold in the application.

- **Fan-in by transfer count** runs in about 2s over the 7-day window with a scalar group
  key, `count(t)` and `sum(t.amount)`, and no `count(DISTINCT)`. The `transfers >= 5`
  threshold moves client-side; the sort and the top-N stay in Cypher and run in the engine.

  ```cypher
  MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
  WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
  WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow
  RETURN account_id, transfers, inflow
  ORDER BY transfers DESC
  ```

A leading `WHERE` on a node or edge property such as `WHERE a.balance > 0` or
`WHERE t.amount >= 9000` stays on the server. Only the comparison against an aggregate
alias has to move.

### Pattern 4: avoid cross products, split into independent halves

An `OPTIONAL MATCH` that branches two ways multiplies rows together, then needs
`DISTINCT` to undo the mess. Splitting the query into two single-`MATCH` aggregations and
joining them client-side is faster and removes the `DISTINCT`.

- **P2P-heavy, merchant-light.** The original used an undirected transfer pattern plus a
  leading `OPTIONAL MATCH` to merchants, with `count(DISTINCT tr)` and `count(DISTINCT tw)`
  over the cross product. The cross join existed only to undo it. The insight: each
  incident edge is already distinct, so `count(DISTINCT tr)` is just `count(tr)`, plain
  transfer degree, and `count(DISTINCT tw)` is just `count(tw)`, the merchant count.

  ```cypher
  MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
  WITH a.account_id AS account_id, count(tr) AS transfer_count
  RETURN account_id, transfer_count
  ```

  ```cypher
  MATCH (a:Account)-[tw:TRANSACTED_WITH]->(:Merchant)
  WITH a.account_id AS acct, count(tw) AS merchant_count
  RETURN acct AS account_id, merchant_count
  ```

  Each half pushes down in about 3.5s for 25,000 accounts. Client-side, left-join the two
  on the account, default `merchant_count` to 0 for accounts with no merchant activity,
  then apply the threshold. The transfer half also confirms the undirected
  `-[tr:TRANSFERRED_TO]-` pattern translates and pushes down.

### Pattern 5: anchor deep traversals; a shallow limit-bounded query is fine unanchored

A `LIMIT` pushes into the SQL on a traversal, anchored or not, at every depth tested. An
unanchored single-, two-, and four-hop traversal with `LIMIT 25` each produced exactly 25
rows on the warehouse, so a limit-bounded visualization query does not need an anchor to be
bounded. The catch is that the `LIMIT` bounds the output, not the join work: the unanchored
four-hop still cost 13.5s of warehouse time to find its 25 rows, against under a second at
one and two hops. An anchor on a single node id such as `{account_id: 184}` becomes a
selective SQL filter, and that, not the `LIMIT`, is what makes a deep traversal cheap.

```cypher
MATCH (a:Account {account_id: $account_id})-[t:TRANSACTED_WITH]->(m:Merchant)
RETURN a, t, m
LIMIT 25
```

For a shallow visualization a `LIMIT` alone is enough; for a deep one, anchor on a specific
account or merchant. Either way, keep the row count small: a query that returns nodes or
relationships carrying a `TIMESTAMP` pays one warehouse round trip per row (see
[Pattern 7](#pattern-7-keep-timestamps-out-of-bulk-results)), which is harmless at 25 rows
and fatal in bulk. The visualization queries in
[`finding-fraud.md`](finding-fraud.md) and [`basic-graph-examples.md`](basic-graph-examples.md)
all follow this rule.

### Pattern 6: keep result sets small

Cost center 2 stands alone: every row travels back over the wire. The all-time fan-out
pair query returned 222,966 rows in about 27s even though it pushed down perfectly.
Narrowing it to a recent 7-day window dropped it to 22,096 rows and about 3.5s. Add a
time window or a tighter filter to shrink the row count. A recent window is also often the
cleaner definition of the signal: a burst of many recipients in one week is a better
smurfing signal than an all-time total.

Multi-hop joins are expensive regardless of grouping. Following two steps in a row (A
sends to B, then B sends to C) does a lot of matching work no matter how you group it.
The unbounded versions did not finish within 100s. Always bound or filter a two-hop
pattern.

### Pattern 7: keep timestamps out of bulk results

The biggest slow path found is not a query cost at all. The graph engine issues one
`SELECT current_timezone()` round trip to the warehouse for every `TIMESTAMP` value it
materializes into a Cypher datetime, about 0.1 to 0.2s each, with no caching. A `DATE`
value never triggers it. The round trip fires wherever the timestamp sits: in a returned
relationship, in a returned node, or as a bare projected `t.transfer_timestamp` column.

At visualization row counts this is invisible. In bulk it dominates everything: a raw pull
of 3,331 rows carrying `transfer_timestamp` finished on the warehouse in 738ms and then
spent about 10 minutes on 3,331 separate timezone round trips. This is the real mechanism
behind the slow node-grouped timing in [Pattern 1](#pattern-1-group-by-a-scalar-not-a-node)
and behind the slow node-grouped and `count(DISTINCT)` anti-patterns: the materialized raw
pull drags a `TIMESTAMP` column along, and each row then pays.

The fix is to project the scalar columns you need rather than returning whole nodes or
relationships, and to avoid returning a bare `TIMESTAMP` column at bulk row counts. The
mapped TIMESTAMP properties are `transfer_timestamp` and `txn_timestamp`; the mapped DATE
property `opened_date` is free. Carrying a `DATE` grouping key such as `opened_date` costs
nothing, which is why a key-grouped aggregation that keeps `opened_date` stays fast.

### When plain Cypher is not enough: GDS

The patterns above keep rules-based fraud signals such as degree, fan-in/out, reciprocity,
cycles, and co-occurrence in pushed-down Cypher. A global, transitive score such as PageRank
or community detection cannot be expressed that way and needs a GDS Session, a separate
ephemeral compute path that projects the data into an in-memory graph. Its cost is dominated
by that projection step, which scales super-linearly with edge count and is insensitive to
warehouse size, so keep the projected window small: about 1.5 minutes at 233 edges, rising
past 33 minutes at roughly 5,000. See [`gds-guide.md`](gds-guide.md) for the working
projection pattern and the plain-Cypher-versus-GDS trade-off.

## Adaptation recipes

How to take a standard Cypher query and make it run on the Virtual Graph. Most of these
follow from the patterns above.

- **Move only the threshold filter client-side.** A HAVING-style `WHERE` on an aggregate
  alias is unsupported. Let the server aggregate, keep the `ORDER BY` and `LIMIT` in Cypher
  where the engine handles them, and apply only the threshold in the application. See
  [Pattern 3](#pattern-3-write-order-by-and-limit-in-cypher-keep-only-the-threshold-client-side).
- **Replace relative time windows with a parameter.** `datetime() - duration({days: 7})`
  inside `WHERE` is unsupported. Compute the cutoff in the application and pass it as
  `$since`, then use `prop >= $since`. Anchor the window to the dataset's maximum
  timestamp, not `now()`: the synthetic transfer data ends 2024-03-30, so a window
  relative to the present returns nothing. `max(transfer_timestamp)` is fast to query and
  makes a good anchor. The demo cutoff `2024-03-23T23:58:00Z` is that maximum minus 7
  days. The `opened_date` series ends 2022-12-06, so the new-account window uses
  `2022-11-06`, that maximum minus 30 days.
- **Drop the upper bound on a multi-hop time window.** Keep the plain ordering
  `out.transfer_timestamp >= in.transfer_timestamp`. Timestamp-plus-duration comparisons
  across relationships are unsupported in `WHERE`. If you need turnaround time, compute it
  in `RETURN` from `.epochMillis`, not in the filter.
- **Move node-property predicates to a leading `WHERE`.** `WHERE a.balance > 0` belongs
  before the aggregating `WITH`, where it stays on the server.
- **For cycles**, enumerate fixed-length patterns and `UNION` them, or run against a
  loaded Aura graph. The variable-length path `{2,4}` does not translate. `UNION ALL` is
  confirmed to run on the Virtual Graph, each branch as its own pushed warehouse statement;
  see the two-label count in [Cypher coverage](#cypher-coverage).

## Cypher coverage

### Supported

| Construct | Detail |
|---|---|
| Aggregation in `WITH` and `RETURN` | `count`, `count(DISTINCT ...)`, `sum`, `avg`, `round`, `collect(DISTINCT ...)`, `size()`. Note `count(DISTINCT ...)` is supported but never pushes down; it always materializes and the cost scales with the window. See [Pattern 2](#pattern-2-replace-countdistinct-with-pair-grouping). |
| `OPTIONAL MATCH` | Supported, but watch for cross products; see [Pattern 4](#pattern-4-avoid-cross-products-split-into-independent-halves). |
| `UNION` / `UNION ALL` | Each branch runs as its own pushed warehouse statement and the engine concatenates the results. Verified with a two-label count and used by the cycles recipe. |
| Plain comparisons in `WHERE` | Numeric comparisons, `abs()`, arithmetic on amounts, `timestamp >= timestamp`, `timestamp >= $param`, `timestamp >= datetime("2020-01-01T00:00:00Z")`. |
| Temporal projection in `RETURN` | `date(timestamp)`, the `.epochMillis` property, `duration.inSeconds(...)` and `duration.between(...)`. |

### Not supported (returns `42NG0: Unsupported syntax`)

| Construct | Detail |
|---|---|
| Writes | `SET`, `CREATE`, `MERGE` all fail. The Virtual Graph is read-only. |
| HAVING-style filtering | Any `WHERE` after an aggregating `WITH` that filters on an aggregate alias, with or without a leading `WHERE`. Fails at parse time with `Neo.ClientError.Statement.SyntaxError`, GQL status `42NG0: Unsupported syntax`, so nothing reaches the warehouse. |
| Temporal arithmetic in a filtering `WHERE` | `datetime() - duration({...})`, `date() - duration({...})`, timestamp-plus-duration compared across relationships, `duration.inSeconds(...)` and `duration.between(...)`, and `.epochMillis` subtraction. The same functions work in `RETURN`. |
| Variable-length and quantified path patterns | For example `(a)-[:TRANSFERRED_TO]->{2,4}(a)`. |
| Counting two labels in one chained statement | `MATCH (a:Account) WITH count(a) ... MATCH (m:Merchant) ...` fails at parse time with `Neo.ClientError.Statement.SyntaxError`, GQL status `42NG0: Unsupported syntax`. Workaround: combine two single-label counts with `UNION ALL` in one statement, which runs each branch as its own warehouse query. |
| `CYPHER 25` version prefix | Does not enable any of the above. |

## Performance and the connection pool

Three things set how fast a query comes back: its shape, the warehouse size, and the
connection pool. The patterns above cover shape, the largest lever. This section covers
the other two. Every query becomes SQL on the backing Databricks SQL warehouse and runs
through a small JDBC connection pool to it, so both the warehouse and the pool shape what
you observe.

The timing table shows shape doing the heavy lifting: the same relationship table is a
few seconds with the right group key and tens of seconds without it.

| Query shape | Observed timing |
|---|---|
| `RETURN 1` | about 0.3s |
| `count` of 25,000 nodes | about 4s |
| `max(timestamp)` | about 1 to 2s |
| Single-hop aggregation scanning the full relationship table | roughly 40 to 45s |
| `count(DISTINCT ...)`, even with a scalar key, over a wide window | never pushes down; materializes, so cost scales with the window: about 4.6s on a 1-day window and past 5 minutes on 7 days |
| Two-hop pattern joins (pass-through, rapid-turnover) | very expensive; unbounded ones did not finish within 100s |

How the pool behaves:

- **Pool size.** The Virtual Graph holds a small JDBC connection pool to Databricks, with
  an observed maximum of 10 connections.
- **A client-side cancel does not cancel the query.** Killing a slow query on the client
  leaves the underlying Databricks query running, and it holds its pool connection until
  it finishes.
- **Saturation.** Once enough long-running queries hold connections, the pool is full and
  new queries return `HikariPool-1 - Connection is not available, request timed out after
  30000ms (total=10, active=10, idle=0)`. The pool recovers when those queries finish on
  Databricks, or after the instance is restarted.
- **No server-side timeout.** The Bolt transaction timeout `begin_transaction(timeout=...)`
  is not honored, so the pool, not a timeout, is what bounds a long query.

Recommendations:

- **Run one query at a time.** Letting each finish before starting the next keeps
  connections free.
- **Keep result sets small.** Prefer the lighter aggregations and add time windows; see
  [Pattern 6](#pattern-6-keep-result-sets-small).
- **Do not count on warehouse size for these queries.** A bigger warehouse only helps a query
  that is genuinely scan- or spill-bound, and this workload is neither. A 2X-Small-versus-Small
  test found no difference across every window of the fan-out query, because Databricks already
  finishes each one in about 0.2s and the wait is data movement, not compute. A separate stress
  test confirmed the warehouse aggregated a 100M-row, ~1 GB table in a few seconds with zero
  spill. Reach for a bigger warehouse only when a query shows real scan time or spill on
  Databricks, which on this data almost never happens. Otherwise the lever is query shape and
  result size, not the machine.

## Anti-patterns: the slow and unsupported forms

These run (or fail) as the shapes the working queries were rewritten to avoid. Each one
names the fast rewrite to use instead.

- **Fan-in with `count(DISTINCT src)` grouped by the `dst` node.** Never pushes down; the
  `DISTINCT` materializes the whole aggregation regardless of the group key. Use the
  pair-grouping form in [Pattern 2](#pattern-2-replace-countdistinct-with-pair-grouping).
- **Fan-out with `count(DISTINCT dst)` grouped by the `src` node.** Same blocker, same
  fix.
- **Hub statistics with a leading `OPTIONAL MATCH` and three `count(DISTINCT ...)`
  aggregates.** This is the cartesian-fan-out shape. Roll fan-in, fan-out, and hub stats
  out of the single pair dataset in [Pattern 2](#pattern-2-replace-countdistinct-with-pair-grouping)
  instead.
- **P2P-heavy, merchant-light with an `OPTIONAL MATCH` cross product.** Split into two
  halves per [Pattern 4](#pattern-4-avoid-cross-products-split-into-independent-halves).
- **Pass-through mule and rapid-turnover as unbounded two-hop joins.** Did not finish
  within 100s. Bound the window and move turnaround time into `RETURN`; see
  [Pattern 6](#pattern-6-keep-result-sets-small).
- **Shared-merchant burst.** Runs, but `account_count >= 4` and `txns <= 200` must move
  client-side, and the `collect(DISTINCT ...)` over a node group can hit the timeout on
  a large window.
- **Layering cycles (`{2,4}` path).** Not supported. The variable-length path is a
  coverage gap, not the HAVING rule, so reshaping the `WITH` does not help. Enumerate
  fixed-length patterns and `UNION` them, or run on a loaded Aura graph.

## Appendix: loaded-graph reference forms

These are the standard, loaded-graph forms of each fraud signal. They do not run verbatim
on the Virtual Graph; they are here to show the gap between the textbook query and the
adapted form. The **Virtual Graph: ✓ / ✗** marker indicates only whether the signal is
achievable at all, not that the Cypher runs as written. Every ✓ needs the adaptations
above, most often moving the post-aggregation filter client-side and replacing relative
time windows with `$since`. The one ✗, cycles, uses a variable-length path the Virtual
Graph cannot translate.

The loaded-graph labels are `:Account` / `:Merchant`. On the Virtual Graph, swap to
`:accounts` / `:merchants` as your model names them.

### 1. Fan-in (mule collection accounts) — ✓

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime() - duration({days: 7})
WITH dst,
     count(DISTINCT src) AS senders,
     count(t)            AS transfers,
     sum(t.amount)       AS inflow
WHERE senders >= 5
RETURN dst.account_id, senders, transfers, round(inflow, 2) AS inflow
ORDER BY senders DESC, inflow DESC
LIMIT 50
```

### 2. Fan-out (distribution / smurfing) — ✓

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src,
     count(DISTINCT dst) AS recipients,
     sum(t.amount)       AS outflow
WHERE recipients >= 5
RETURN src.account_id, recipients, round(outflow, 2) AS outflow
ORDER BY recipients DESC
LIMIT 50
```

### 3. Pass-through mule (local betweenness proxy) — ✓

```cypher
MATCH (a:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(b:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND out.transfer_timestamp <= in.transfer_timestamp + duration({hours: 48})
  AND abs(out.amount - in.amount) <= 0.05 * in.amount
  AND a <> b
RETURN mule.account_id,
       count(*)                 AS passthroughs,
       round(sum(in.amount), 2) AS volume
ORDER BY passthroughs DESC
LIMIT 50
```

### 4. Reciprocal / round-trip transfers — ✓

```cypher
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id
RETURN a.account_id, b.account_id,
       round(sum(f.amount + g.amount), 2) AS round_trip_volume,
       count(*)                            AS leg_count
ORDER BY round_trip_volume DESC
LIMIT 50
```

### 5. Layering cycles — ✗ (loaded graph only)

The variable-length path `{2,4}` is a coverage gap. Run on the loaded Aura graph, or
enumerate fixed lengths as separate single-`MATCH` queries and `UNION` them, which is a
confirmed-working construct on the Virtual Graph.

```cypher
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
```

### 6. Shared-merchant burst (coordinated ring) — ✓

```cypher
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
WITH m, date(t.txn_timestamp) AS day,
     collect(DISTINCT a.account_id) AS accounts,
     count(t)                       AS txns
WHERE size(accounts) >= 4
  AND txns <= 200
RETURN m.merchant_id, m.merchant_name, day,
       size(accounts) AS account_count, txns, accounts
ORDER BY account_count DESC
LIMIT 50
```

### 7. Structuring (just-under-threshold transfers) — ✓

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
WHERE near_threshold >= 3
RETURN src.account_id, near_threshold, total
ORDER BY near_threshold DESC
LIMIT 50
```

### 8. New account, high velocity — ✓

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= date() - duration({days: 30})
WITH a, count(t) AS transfers, round(sum(t.amount), 2) AS outflow
WHERE transfers >= 10
RETURN a.account_id, a.opened_date, a.holder_age, transfers, outflow
ORDER BY outflow DESC
LIMIT 50
```

### 9. Hub network statistics — ✓ (reshaped)

```cypher
MATCH (a:Account)<-[r_in:TRANSFERRED_TO]-(src:Account)
OPTIONAL MATCH (a)-[r_out:TRANSFERRED_TO]->(dst:Account)
WITH a,
     count(DISTINCT src)  AS incoming_conns,
     count(DISTINCT dst)  AS outgoing_conns,
     count(DISTINCT r_in) AS incoming_txns
WHERE incoming_conns >= 100
RETURN a.account_id,
       incoming_conns + outgoing_conns AS total_connections,
       incoming_conns, outgoing_conns, incoming_txns
ORDER BY incoming_conns DESC
LIMIT 15
```

### 10. Rapid-turnover summary per account — ✓

```cypher
MATCH (src:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(dst:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND out.transfer_timestamp <= in.transfer_timestamp + duration({hours: 24})
  AND src <> dst
WITH mule,
     count(*) AS rapid_pairs,
     avg(duration.inSeconds(in.transfer_timestamp, out.transfer_timestamp).seconds) / 3600.0 AS avg_hours
WHERE rapid_pairs >= 50
RETURN mule.account_id, rapid_pairs, round(avg_hours, 1) AS avg_turnaround_hours
ORDER BY rapid_pairs DESC
LIMIT 15
```

### 11. Velocity ratio (volume vs. balance) — ✓

`balance` is a current snapshot, not a time series. A pass-through account ends near empty
by construction, so a small balance is partly a consequence of the behavior rather than
independent evidence. Treat a high ratio as one weak signal. Account tenure or
inflow-vs-outflow symmetry is a cleaner denominator.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, sum(t.amount) AS outflow
WHERE a.balance > 0 AND outflow > 0
RETURN a.account_id,
       round(a.balance, 2)            AS balance,
       round(outflow, 2)              AS outflow_volume,
       round(outflow / a.balance, 1)  AS velocity_ratio
ORDER BY velocity_ratio DESC
LIMIT 25
```

### 12. P2P-heavy, merchant-light disconnect — ✓ (reshaped)

```cypher
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
OPTIONAL MATCH (a)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a,
     count(DISTINCT tr) AS transfer_count,
     count(DISTINCT tw) AS merchant_count
WHERE transfer_count >= 100 AND merchant_count < 20
RETURN a.account_id, transfer_count, merchant_count
ORDER BY transfer_count DESC
LIMIT 25
```

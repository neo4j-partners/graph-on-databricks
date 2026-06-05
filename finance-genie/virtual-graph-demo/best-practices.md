# Virtual Graph Best Practices

How to write Cypher that runs well on the Finance Genie Virtual Graph. Aura
translates each Cypher query to SQL and runs it on the backing Databricks SQL
warehouse, so the rules here are about helping that translation push work down to
Databricks instead of dragging rows back to the graph engine.

The working fraud queries this guide draws on are the demo set in
[`finding-fraud.md`](finding-fraud.md); the warm-up and visualization queries are in
[`basic-graph-examples.md`](basic-graph-examples.md). This document is the reference
for *why* those queries are shaped the way they are, and what to do when a standard
Cypher query will not run.

## How the Virtual Graph works

- **Translation.** Cypher becomes SQL over Databricks. Only a subset of Cypher is
  supported, so a query written for a loaded Aura graph rarely runs verbatim. The
  reference forms in the appendix show the gap.
- **The shared query shape.** Aggregate and order on the server, then apply the
  threshold filter and the top-N in your application. Almost every adaptation in this
  guide is a consequence of that one shape.
- **Property mapping.** Relationship and node properties exist only if they were mapped
  from a backing table column in the Aura model. An unmapped column leaves the
  relationship in place with zero properties, and any query touching it fails with
  "Could not resolve property".
- **Labels.** This model uses singular `:Account` and `:Merchant`. A model generated
  from table names may use `:accounts` and `:merchants` instead. Match your model.
  - `TRANSFERRED_TO` (`:Account` → `:Account`): `amount`, `transfer_timestamp`, `link_id`.
  - `TRANSACTED_WITH` (`:Account` → `:Merchant`): `amount`, `txn_timestamp`, `txn_hour`, `txn_id`.

Timings in this guide are dominated by the backing warehouse and the connection-pool
behavior, not by the query text. Treat them as rough and directional.

## What governs performance

Performance comes down to two cost centers plus the machine everything runs on. A few
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

**The machine underneath.** Real wall-clock time is usually set by the warehouse size
and the connection pool, covered under [Operational hazards](#operational-hazards).

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
  `a.account_id` and carrying `a.opened_date` and `a.holder_age` as extra grouping keys
  (they are constant per account) ran in about 1s. The node-grouped form `WITH a, count(t) ...`
  took about 985s for the identical result.

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

`count(DISTINCT x)` is its own trap, separate from the node-versus-scalar one. Even with
a clean scalar group key, `count(DISTINCT dst.account_id)` grouped by `src.account_id`
ran past 5 minutes with no result. The `DISTINCT` itself blocks pushdown.

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

### Pattern 3: keep ORDER BY, LIMIT, and thresholds off the server

A row-cutting `LIMIT` or a sort on the server can add a post-processing step. More
importantly, a HAVING-style filter on an aggregate alias is not supported at all (see
[Cypher coverage](#cypher-coverage)). The shape that runs is: the server does
`MATCH ... WITH <aggregates> ... RETURN ... ORDER BY <aggregate> DESC` with no post-`WITH`
`WHERE` and no row-cutting `LIMIT`. Apply the threshold and the top-N in the application.
The grouped row count is bounded by the number of accounts, so shipping all of it back is
cheap.

- **Fan-in by transfer count** runs in about 2s over the 7-day window with a scalar group
  key, `count(t)` and `sum(t.amount)`, no `count(DISTINCT)`, no `ORDER BY`, and no
  `LIMIT` on the server. EXPLAIN reports no post-processing step. The `transfers >= 5`
  threshold, the sort, and the top-N all move client-side.

  ```cypher
  MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
  WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
  WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow
  RETURN account_id, transfers, inflow
  ```

A leading `WHERE` on a node or edge property (`WHERE a.balance > 0`,
`WHERE t.amount >= 9000`) stays on the server. Only the comparison against an aggregate
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

### Pattern 5: anchor traversals on a node id

Aggregations push down; traversals and visualizations push down through a *selective
filter*. A query anchored on a single node id (`{account_id: 184}`) becomes a selective
SQL filter that the warehouse runs quickly and that returns a handful of rows. The same
pattern with no anchor becomes a full join across the relationship table, which is slow
and returns far too much to draw.

```cypher
MATCH (a:Account {account_id: $account_id})-[t:TRANSACTED_WITH]->(m:Merchant)
RETURN a, t, m
LIMIT 25
```

For every demo or visualization query, start from a specific account or merchant. An
unanchored two-hop traversal scans the full relationship table; anchored, the same shape
returns in a few seconds. The visualization queries in
[`finding-fraud.md`](finding-fraud.md) and [`basic-graph-examples.md`](basic-graph-examples.md)
all follow this rule.

### Pattern 6: keep result sets small

Cost center 2 stands alone: every row travels back over the wire. The all-time fan-out
pair query returned 222,966 rows in about 24.8s even though it pushed down perfectly.
Narrowing it to a recent 7-day window dropped it to 22,096 rows and about 3.5s. Add a
time window or a tighter filter to shrink the row count. A recent window is also often the
cleaner definition of the signal: a burst of many recipients in one week is a better
smurfing signal than an all-time total.

Multi-hop joins are expensive regardless of grouping. Following two steps in a row (A
sends to B, then B sends to C) does a lot of matching work no matter how you group it.
The unbounded versions did not finish within 100s. Always bound or filter a two-hop
pattern.

## Adaptation recipes

How to take a standard Cypher query and make it run on the Virtual Graph. Most of these
follow from the patterns above.

- **Move the threshold filter client-side.** A HAVING-style `WHERE` on an aggregate alias
  is unsupported. Let the server aggregate and order, apply the threshold and top-N in the
  application. See [Pattern 3](#pattern-3-keep-order-by-limit-and-thresholds-off-the-server).
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
  loaded Aura graph. The variable-length path `{2,4}` does not translate.

## Cypher coverage

### Supported

| Construct | Detail |
|---|---|
| Aggregation in `WITH` and `RETURN` | `count`, `count(DISTINCT ...)`, `sum`, `avg`, `round`, `collect(DISTINCT ...)`, `size()`. Note `count(DISTINCT ...)` is supported but rarely pushes down; see [Pattern 2](#pattern-2-replace-countdistinct-with-pair-grouping). |
| `OPTIONAL MATCH` | Supported, but watch for cross products; see [Pattern 4](#pattern-4-avoid-cross-products-split-into-independent-halves). |
| Plain comparisons in `WHERE` | Numeric comparisons, `abs()`, arithmetic on amounts, `timestamp >= timestamp`, `timestamp >= $param`, `timestamp >= datetime("2020-01-01T00:00:00Z")`. |
| Temporal projection in `RETURN` | `date(timestamp)`, the `.epochMillis` property, `duration.inSeconds(...)` and `duration.between(...)`. |

### Not supported (returns `42NG0: Unsupported syntax`)

| Construct | Detail |
|---|---|
| Writes | `SET`, `CREATE`, `MERGE` all fail. The Virtual Graph is read-only. |
| HAVING-style filtering | Any `WHERE` after an aggregating `WITH` that filters on an aggregate alias, with or without a leading `WHERE`. |
| Temporal arithmetic in a filtering `WHERE` | `datetime() - duration({...})`, `date() - duration({...})`, timestamp-plus-duration compared across relationships, `duration.inSeconds(...)` and `duration.between(...)`, and `.epochMillis` subtraction. The same functions work in `RETURN`. |
| Variable-length and quantified path patterns | For example `(a)-[:TRANSFERRED_TO]->{2,4}(a)`. |
| Counting two labels in one statement | `MATCH (a:Account) WITH count(a) ... MATCH (m:Merchant) ...` fails with `42NG0`. Run each label count as its own statement. |
| `CYPHER 25` version prefix | Does not enable any of the above. |

## Operational hazards

Every query becomes SQL on the backing Databricks SQL warehouse, and the connection pool
to that warehouse is the main operational hazard.

| Query shape | Observed timing |
|---|---|
| `RETURN 1` | about 0.3s |
| `count` of 25,000 nodes | about 4s |
| `max(timestamp)` | about 1 to 2s |
| Single-hop aggregation scanning the full relationship table | roughly 40 to 45s |
| `count(DISTINCT ...)` grouped by a node over the full transfer table | did not finish within 100s |
| Two-hop pattern joins (pass-through, rapid-turnover) | very expensive; unbounded ones did not finish within 100s |

- **Small pool.** The Virtual Graph holds a small JDBC connection pool to Databricks,
  observed maximum 10 connections.
- **Abandoning does not cancel.** Killing a slow query on the client does not cancel the
  underlying Databricks query. It keeps running and holds a pool connection.
- **Saturation.** A few abandoned slow queries saturate the pool, after which every new
  query fails with `HikariPool-1 - Connection is not available, request timed out after
  30000ms (total=10, active=10, idle=0)`. Recovery needs those queries to finish on
  Databricks or the instance to be restarted.
- **No server-side timeout.** The Bolt transaction timeout `begin_transaction(timeout=...)`
  is not honored, so you cannot bound a query that way.

Practical guidance:

- **Run one query at a time.** Let each finish rather than abandoning it.
- **Keep result sets small.** Prefer the lighter aggregations and add time windows.
- **Size the warehouse.** A bigger Databricks SQL warehouse sets a faster floor for every
  scan and aggregation.

## Anti-patterns: the slow and unsupported forms

These run (or fail) as the shapes the working queries were rewritten to avoid. Each one
names the fast rewrite to use instead.

- **Fan-in with `count(DISTINCT src)` grouped by the `dst` node.** Does not push down.
  Use the pair-grouping form in [Pattern 2](#pattern-2-replace-countdistinct-with-pair-grouping).
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
enumerate fixed lengths as separate single-`MATCH` queries and `UNION` them.

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

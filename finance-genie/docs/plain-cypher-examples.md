# Plain Cypher Fraud Signals (No Gold Enrichment, No GDS)

A lot of fraud signal in the Finance Genie graph is purely structural and temporal, which means plain Cypher over the four base entities (`:Account`, `:Merchant`, `TRANSACTED_WITH`, `TRANSFERRED_TO`) gets you most of the way. GDS and the gold features mainly buy you global, iterative scores (PageRank, Louvain/WCC communities, betweenness) that you cannot compute exactly in a single Cypher statement. Almost everything local that those algorithms approximate, you can express directly.

## Virtual Graph examples (verified)

These are the versions that actually run on the Aura Virtual Graph in this project. The Virtual Graph translates Cypher to SQL over Databricks and supports only a subset of Cypher, so the reference examples further down do not run verbatim. The queries here are the adapted forms from `queries.py`. Each one aggregates and orders on the server, then applies the threshold filter and the top-N client-side. Two recurring adaptations are applied: HAVING-style filters move into the application, and relative time windows become a precomputed `$since` parameter anchored to the dataset's maximum timestamp. Section B documents the full support matrix and the operational behavior.

The node labels in this model are `:Account` and `:Merchant`, singular. A model generated straight from table names may instead use `:accounts` and `:merchants`. Adjust the labels to match your model. Relationship properties exist only if they were mapped in the Aura model. `TRANSFERRED_TO` carries `amount`, `transfer_timestamp`, and `link_id`. `TRANSACTED_WITH` carries `amount`, `txn_timestamp`, `txn_hour`, and `txn_id`. If those property columns are not mapped in the model, the relationships exist with zero properties and every amount or timestamp query fails with "Could not resolve property".

Timings below are provisional. They are dominated by the backing Databricks warehouse and the connection-pool behavior described in Section B, not by the query text.

### Status: runs and is reasonably quick

#### Q4. Reciprocal / round-trip transfers

A pays B and B pays A back. Runs verbatim: a single `MATCH` with no HAVING-style filter. It is fast (about 3s, 21052 rows) because its grouping keys are the scalar `a.account_id` and `b.account_id` in the `RETURN`, so the aggregation already pushes down to Databricks with no reshape. This is the same reason the Q7 rewrite is fast: aggregate grouped by scalar columns pushes down, aggregate grouped by a node does not.

```cypher
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id
RETURN a.account_id AS a_id, b.account_id AS b_id,
       round(sum(f.amount + g.amount), 2) AS round_trip_volume,
       count(*)                            AS leg_count
ORDER BY round_trip_volume DESC
```

#### Q7. Structuring (just-under-threshold transfers)

Repeated transfers sized to stay below a reporting line. Adaptation: the `near_threshold >= 3` filter moves client-side.

Performance fix: group by the scalar `src.account_id`, not by the `src` node. Grouping by a node entity stops the Virtual Graph from pushing the `GROUP BY` down to Databricks, so it drags every matching transfer row back into the graph engine and aggregates there (about 38s, and the console warns about a "post-processing step that materialize intermediate results"). Grouping by the scalar id lets the aggregation push down to the warehouse, which runs in about 1s on the same instance, a roughly 40x speedup. Dropping the trailing `(:Account)` label or the `round()` wrapper made no difference in testing; only the group key matters.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src.account_id AS account_id, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
RETURN account_id, near_threshold, total
ORDER BY near_threshold DESC
```

#### Q11. Velocity ratio (volume vs. balance)

Outbound volume relative to current balance. As first written this grouped by the `a` node (`WITH a, sum(t.amount)`), which does not push down: it materializes, the same slow shape that made the node-grouped Q8 take about 985s. Group by the scalar `a.account_id` and carry `a.balance` as a grouping key, and the aggregation pushes down to about 3.4s over the full transfer table (24951 accounts). The velocity ratio and the rounding are derived client-side, `a.balance > 0` stays in a leading `WHERE`, and the `outflow > 0` filter, the sort, and the top-N move client-side.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.balance > 0
WITH a.account_id AS account_id, a.balance AS balance, sum(t.amount) AS outflow
RETURN account_id, balance, outflow
```

The client-side step, for reference: keep rows with `outflow > 0`, compute `velocity_ratio = round(outflow / balance, 1)`, round `balance` and `outflow`, then sort by `velocity_ratio` descending and take the top-N.

#### Q1-M. Fan-in by transfer count (pushdown-friendly fan-in)

The fast rewrite of the fan-in signal below. It surfaces accounts receiving many incoming transfers in a recent 7-day window, the collection-mule shape, by counting transfers and summing inflow per recipient.

It is fast for the same reason as Q4 and Q7, taken one step further. The grouping key is the scalar `dst.account_id`, and the aggregates are `count(t)` over the relationship and `sum(t.amount)`, with no `count(DISTINCT)`, no `ORDER BY`, and no `LIMIT` on the server. The whole aggregation pushes down to Databricks, EXPLAIN reports no post-processing step at all, and it runs in about 2s over the 7-day window (9847 grouped recipients, 1157 with 5 or more transfers). Adaptation: the 7-day window is a hard-coded datetime literal, and the `transfers >= 5` threshold, the sort, and the top-N all move client-side so the server query keeps only the constructs that push down.

The cutoff below, `2024-03-23T23:58:00Z`, is the dataset's maximum `transfer_timestamp` (2024-03-30T23:58:00Z) minus 7 days. Anchor it to the dataset maximum, not to `now()`: the synthetic data ends 2024-03-30, so a window relative to the present returns nothing. In production, compute the cutoff and pass it as a `$since` parameter instead of hard-coding it, since `datetime() - duration({days: 7})` inside the `WHERE` is unsupported.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow
RETURN account_id, transfers, inflow
```

The tradeoff against the distinct-sender Q1 below: this counts transfers, the edges, not distinct senders. Repeat transfers from the same source inflate the count, so a high `transfers` value is a weaker collection signal than a high distinct-sender count. The reason Q1 is slow and this is fast is exactly the `count(DISTINCT src)` grouped by the `dst` node: that combination cannot push down, so it drags every matching transfer back into the graph engine and counts distinct sources there. Drop the distinct-sender count and group by the scalar id, and the query pushes down. Q1-pair below recovers the distinct-sender count without giving up the pushdown.

#### Q1-pair. Fan-in by distinct senders (pushdown-friendly, full fidelity)

The faithful fan-in signal, distinct senders per recipient, expressed so it still pushes down. It runs in about 3.7s over the 7-day window and recovers the exact signal Q1-M trades away.

The trick is to do the distinct in the grouping instead of with `count(DISTINCT ...)`. Group by the pair `(dst.account_id, src.account_id)` on the server, which dedupes sender-recipient pairs with a plain `GROUP BY` and needs no `DISTINCT`, so the aggregation pushes down to Databricks. The server returns one row per sender-recipient pair (about 22000 rows for the 7-day window). The application then groups those by recipient and counts the rows, which is the distinct-sender count, and sums `legs` and `pair_amount` for the transfer count and inflow. The `senders >= 5` threshold, the sort, and the top-N stay client-side. This found 1127 accounts with 5 or more distinct senders.

Give the two endpoints distinct aliases (`recipient` and `sender`). Aliasing both to `account_id` collides in the generated SQL and fails with `AMBIGUOUS_REFERENCE`.

The cutoff `2024-03-23T23:58:00Z` is the same 7-day window as Q1-M: the dataset's maximum `transfer_timestamp` minus 7 days. Parameterize it as `$since` in production.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH dst.account_id AS recipient, src.account_id AS sender,
     count(t) AS legs, sum(t.amount) AS pair_amount
RETURN recipient, sender, legs, pair_amount
```

The client-side aggregation, for reference: group the rows by `recipient`; `senders` is the row count per recipient, `transfers` is `sum(legs)`, and `inflow` is `sum(pair_amount)`. This is the general way to recover a `count(DISTINCT x)` that will not push down: group by `x` on the server and count the groups in the application.

#### Q2-pair. Fan-out by distinct recipients (pushdown-friendly, full fidelity)

The mirror of Q1-pair for fan-out. The faithful smurfing signal is distinct recipients per sender, which is `count(DISTINCT dst)` grouped by the `src` node, and that does not push down. The scalar version, grouping by `src.account_id` but keeping `count(DISTINCT dst.account_id)`, does not push down either: it ran past 5 minutes without returning on the same warehouse where the pair form finishes in seconds. The DISTINCT is the blocker, not just the node group key.

The fix is the same pair-grouping trick: group by the pair `(src.account_id, dst.account_id)` on the server, which dedupes sender-recipient pairs with a plain `GROUP BY` and needs no `DISTINCT`, so the aggregation pushes down. The server returns one row per pair; the application groups those by `sender`, and the row count per sender is the distinct-recipient count, with `pair_transfers` and `pair_outflow` summed for the transfer count and total outflow. The `recipients >= 5` threshold, the sort, and the top-N stay client-side. Give the two endpoints distinct aliases (`sender` and `recipient`); aliasing both to `account_id` fails with `AMBIGUOUS_REFERENCE`.

Q2 wants the time window, unlike Q7. Fan-out is unfiltered by nature, so all-time pair-grouping returns one row per distinct pair across the whole table, 222966 rows in about 24.8s, dominated by transferring that many rows back. Restricting to a recent 7-day window (the same `2024-03-23T23:58:00Z` cutoff as Q1) cuts it to 22096 pairs in about 3.5s, which is demo-ready. A burst of many recipients in a recent window is also the cleaner smurfing definition than many recipients ever.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH src.account_id AS sender, dst.account_id AS recipient,
     count(t) AS pair_transfers, sum(t.amount) AS pair_outflow
RETURN sender, recipient, pair_transfers, pair_outflow
```

The client-side aggregation, for reference: group the rows by `sender`; `recipients` is the row count per sender, `transfers` is `sum(pair_transfers)`, and `outflow` is `sum(pair_outflow)`. Parameterize the cutoff as `$since` in production.

#### Q8. New account, high velocity

Recently opened accounts moving large volume fast. Group by the scalar `a.account_id`, carrying `a.opened_date` and `a.holder_age` as grouping keys since they are constant per account, and the aggregation pushes down to about 1s over the 30-day opened window (452 accounts, 52 with 10 or more transfers). The node-grouped form (`WITH a, count(t) ...`) took about 985s for the identical result, the clearest single measurement of the node-versus-scalar grouping cost in this file.

The cutoff `2022-11-06` is the dataset's maximum `opened_date` (2022-12-06) minus 30 days. As with Q1-M, hard-code it here and parameterize it as `$since` in production, since `date() - duration({days: 30})` inside the `WHERE` is unsupported. The `transfers >= 10` threshold, the sort, and the top-N move client-side.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= date("2022-11-06")
WITH a.account_id AS account_id, a.opened_date AS opened_date,
     a.holder_age AS holder_age, count(t) AS transfers, sum(t.amount) AS outflow
RETURN account_id, opened_date, holder_age, transfers, outflow
```

#### Q9-roll. Hub statistics rolled up from the pair dataset (pushdown-friendly)

Hub statistics are in-degree (distinct senders), out-degree (distinct recipients), and incoming transfer count per account. The original Q9 computed all three on the server by grouping the `a` node with three `count(DISTINCT)` aggregates over a leading `OPTIONAL MATCH` cartesian fan-out, which is exactly the shape that does not push down: a node group key plus `count(DISTINCT)` plus a cross join.

There is no need for a dedicated hub query. All three statistics are a client-side rollup of the same all-time pair dataset used for fan-in and fan-out. Group by the pair `(src.account_id, dst.account_id)` over the whole transfer table; the server returns one row per directed sender-recipient pair (222966 rows in about 24.8s, the cost being the row transfer, since the table has no time filter). Then in the application: group the rows by `recipient` to get `incoming_conns` (the row count per recipient, that is distinct senders) and `incoming_txns` (`sum(legs)`); group the same rows by `sender` to get `outgoing_conns` (the row count per sender, that is distinct recipients). One server query feeds fan-in, fan-out, and hub statistics together.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src.account_id AS sender, dst.account_id AS recipient,
     count(t) AS legs, sum(t.amount) AS pair_amount
RETURN sender, recipient, legs, pair_amount
```

#### Q12-split. P2P-heavy, merchant-light via two pushdown halves

The disconnect signal is high peer-to-peer transfer activity with little merchant spend. The original Q12 used an undirected `-[tr]-` transfer pattern plus a leading `OPTIONAL MATCH` to merchants, with `count(DISTINCT tr)` and `count(DISTINCT tw)` over the resulting cross product. That is the same non-pushdown shape as Q9: the cross join exists only to undo it with `DISTINCT`.

Split it into two independent single-`MATCH` aggregations grouped by the scalar id, no `DISTINCT` and no cross join, then join the two results client-side on the account. `count(DISTINCT tr)` is just transfer degree, since each incident edge is distinct, so a plain `count(tr)` over the undirected pattern gives it. `count(DISTINCT tw)` is the merchant transaction count, a plain `count(tw)`.

The transfer-degree half pushes down in about 3.5s (25000 accounts). This also settles an open question: the undirected `-[tr:TRANSFERRED_TO]-` pattern translates and pushes down.

```cypher
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
WITH a.account_id AS account_id, count(tr) AS transfer_count
RETURN account_id, transfer_count
```

The merchant-count half pushes down in about 3.2s (24999 accounts). One caveat: the `TRANSACTED_WITH` backing table exposes its own `account_id` column, so aliasing the grouping key to `account_id` fails with `AMBIGUOUS_REFERENCE` (`a.account_id` versus `tw.account_id`). Alias the grouping key to something else and rename it in `RETURN`. The `TRANSFERRED_TO` table has no such column, which is why the transfer half above can alias to `account_id` directly.

```cypher
MATCH (a:Account)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a.account_id AS acct, count(tw) AS merchant_count
RETURN acct AS account_id, merchant_count
```

The client-side step, for reference: left-join the transfer-degree rows with the merchant-count rows on the account, defaulting `merchant_count` to 0 for accounts with no merchant activity (the `merchant_count < 20` filter is meant to keep those), then keep accounts with `transfer_count >= 100 AND merchant_count < 20`, sort by `transfer_count` descending, and take the top-N.

### Status: runs but expensive or slow on the backing warehouse

#### Q1. Fan-in (mule collection accounts)

Many distinct senders pushing into one account in a recent window. Adaptation: the 7-day window becomes a `$since` parameter, and `senders >= 5` moves client-side.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
WITH dst,
     count(DISTINCT src) AS senders,
     count(t)            AS transfers,
     sum(t.amount)       AS inflow
RETURN dst.account_id AS account_id, senders, transfers, round(inflow, 2) AS inflow
ORDER BY senders DESC, inflow DESC
```

#### Q2. Fan-out (distribution / smurfing)

One account spraying funds to many recipients. Adaptation: `recipients >= 5` moves client-side.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src,
     count(DISTINCT dst) AS recipients,
     sum(t.amount)       AS outflow
RETURN src.account_id AS account_id, recipients, round(outflow, 2) AS outflow
ORDER BY recipients DESC
```

#### Q3. Pass-through mule (local betweenness proxy)

Account receives an amount and forwards roughly the same value. Adaptation: the 48-hour forward window is dropped because temporal arithmetic in a `WHERE` is unsupported. The forward-after-receive ordering and the 5% same-value test are kept.

```cypher
MATCH (a:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(b:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND abs(out.amount - in.amount) <= 0.05 * in.amount
  AND a <> b
RETURN mule.account_id            AS account_id,
       count(*)                   AS passthroughs,
       round(sum(in.amount), 2)   AS volume
ORDER BY passthroughs DESC
```

#### Q6. Shared-merchant burst (coordinated ring)

A group of accounts all hitting the same merchant on the same day. Adaptation: `account_count >= 4` and `txns <= 200` move client-side.

```cypher
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
WITH m, date(t.txn_timestamp) AS day,
     collect(DISTINCT a.account_id) AS accounts,
     count(t)                       AS txns
RETURN m.merchant_id AS merchant_id, m.merchant_name AS merchant_name, day,
       size(accounts) AS account_count, txns, accounts
ORDER BY account_count DESC
```

#### Q9. Hub network statistics

Per-account in-degree and out-degree by distinct counterparty. Adaptation: `incoming_conns >= 100` moves client-side. The leading `OPTIONAL MATCH` shape with `count(DISTINCT ...)` is robust to the cartesian fan-out between the two traversals.

```cypher
MATCH (a:Account)<-[r_in:TRANSFERRED_TO]-(src:Account)
OPTIONAL MATCH (a)-[r_out:TRANSFERRED_TO]->(dst:Account)
WITH a,
     count(DISTINCT src)  AS incoming_conns,
     count(DISTINCT dst)  AS outgoing_conns,
     count(DISTINCT r_in) AS incoming_txns
RETURN a.account_id AS account_id,
       incoming_conns + outgoing_conns AS total_connections,
       incoming_conns, outgoing_conns, incoming_txns
ORDER BY incoming_conns DESC
```

#### Q10. Rapid-turnover summary per account

Receive-then-forward pairs per account, with average turnaround. Adaptation: the 24-hour window is dropped because temporal arithmetic in a `WHERE` is unsupported. The turnaround is computed in `RETURN` from `.epochMillis`, and `rapid_pairs >= 50` moves client-side. This is an unbounded two-hop join and may be slow or hit the timeout.

```cypher
MATCH (src:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(dst:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND src <> dst
WITH mule,
     count(*) AS rapid_pairs,
     round(avg(out.transfer_timestamp.epochMillis
               - in.transfer_timestamp.epochMillis) / 3600000.0, 1) AS avg_turnaround_hours
RETURN mule.account_id AS account_id, rapid_pairs, avg_turnaround_hours
ORDER BY rapid_pairs DESC
```

#### Q12. P2P-heavy, merchant-light disconnect

Heavy peer-to-peer activity with little merchant spend. Adaptation: `transfer_count >= 100` and `merchant_count < 20` move client-side. The merchant traversal is `OPTIONAL` so accounts with zero merchant activity are kept.

```cypher
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
OPTIONAL MATCH (a)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a,
     count(DISTINCT tr) AS transfer_count,
     count(DISTINCT tw) AS merchant_count
RETURN a.account_id AS account_id, transfer_count, merchant_count
ORDER BY transfer_count DESC
```

### Status: not supported on the Virtual Graph

#### Q5. Layering cycles

The variable-length path `{2,4}` is unsupported. Reshaping the `WITH` does not help, because the gap is the path pattern itself. Run this on a loaded Aura graph, or enumerate fixed-length patterns and `UNION` them.

```cypher
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
```

## Virtual Graph: patterns, tips, and what does not work

This section records the empirical support matrix and the operational behavior. The operational behavior matters more than the Cypher subset.

### Supported Cypher constructs

| Construct | Detail |
|---|---|
| Aggregation in `WITH` and `RETURN` | `count`, `count(DISTINCT ...)`, `sum`, `avg`, `round`, `collect(DISTINCT ...)`, `size()` |
| `OPTIONAL MATCH` | Supported |
| Plain comparisons in `WHERE` | Numeric comparisons, `abs()`, arithmetic on amounts, `timestamp >= timestamp`, `timestamp >= $param`, `timestamp >= datetime("2020-01-01T00:00:00Z")` |
| Temporal projection in `RETURN` | `date(timestamp)`, the `.epochMillis` property, `duration.inSeconds(...)` and `duration.between(...)` |

### Not supported (returns `42NG0: Unsupported syntax`)

| Construct | Detail |
|---|---|
| Writes | `SET`, `CREATE`, `MERGE` all fail. The Virtual Graph is read-only. You cannot write a property onto a node or relationship through Cypher. Properties exist only if mapped from a backing table column in the Aura model. |
| HAVING-style filtering | Any `WHERE` placed after an aggregating `WITH` that filters on an aggregate alias fails, with or without a leading `WHERE`. |
| Temporal arithmetic and functions in a filtering `WHERE` | `datetime() - duration({...})`, `date() - duration({...})`, `someTimestamp + duration({...})` compared across relationships, `duration.inSeconds(...)` and `duration.between(...)` in `WHERE`, and `.epochMillis` subtraction in `WHERE`. The same functions work in `RETURN`, just not in a filtering `WHERE`. |
| Variable-length and quantified path patterns | For example `(a)-[:TRANSFERRED_TO]->{2,4}(a)`. |
| `CYPHER 25` version prefix | Does not enable any of the above. |

### Adaptation patterns

How to make a standard Cypher query run on the Virtual Graph.

1. Move the threshold filter client-side. Have the server do `MATCH ... WITH <aggregates> ... RETURN ... ORDER BY <aggregate> DESC` with no post-`WITH` `WHERE` and no `LIMIT` that would cut rows before filtering. Apply the threshold and the top-N in the application. The number of grouped rows is bounded by the number of accounts, so this is cheap to post-process.
2. Replace relative time windows with a parameter. Compute the cutoff in the application and pass it as `$since`, then use `prop >= $since`. Anchor the window to the dataset's maximum timestamp, not to `now()`. The synthetic data ends 2024-03-30, so a `now() - 7 days` window returns nothing. `max(transfer_timestamp)` is fast to query and makes a good anchor.
3. Drop the upper time bound on multi-hop "within N hours" windows. Keep the plain ordering `out.transfer_timestamp >= in.transfer_timestamp`. The duration bound cannot be expressed in a `WHERE`. If you need average turnaround, compute it in `RETURN` from `.epochMillis`, not in the filter.
4. Move node-property predicates out of a post-`WITH` `WHERE` into a leading `WHERE`. For example `WHERE a.balance > 0` belongs before the aggregating `WITH`. Only the aggregate comparison needs to move client-side.
5. For cycles, enumerate fixed-length patterns and `UNION` them, or run against a loaded Aura graph.

### Operational behavior and performance

Every query becomes SQL on the backing Databricks SQL warehouse.

| Query shape | Observed timing |
|---|---|
| `RETURN 1` | about 0.3s |
| `count` of 25000 nodes | about 4s |
| `max(timestamp)` | about 1 to 2s |
| Single-hop aggregation scanning the full relationship table | roughly 40 to 45s |
| `count(DISTINCT ...)` grouped by a node over the full transfer table | did not finish within 100s |
| Two-hop pattern joins, the pass-through and rapid-turnover shapes | very expensive; an unbounded one did not finish within 100s |
| `date()` (or any function) as a `GROUP BY` key | materializes; the per-day Q6 burst did not finish within 120s |

Pushdown is what separates a query that returns in seconds from one that materializes intermediate rows in the graph engine and runs for minutes. An aggregation pushes down to Databricks only when its `GROUP BY` key is a scalar property. Three things each independently break pushdown:

- **Grouping by a node** (`WITH a, ...`) instead of a scalar (`WITH a.account_id AS account_id, ...`). Carry any extra node properties as additional scalar grouping keys. This is the largest factor measured here: the node-grouped Q8 took about 985s, the scalar form about 1s.
- **`count(DISTINCT x)`**, which forces the engine to materialize the distinct set. Replace it with a pair grouping: group by `(key, x)` on the server, which dedupes with a plain `GROUP BY`, then count the groups per key client-side.
- **A function-derived grouping key** such as `date(t.txn_timestamp)`. The same `date()` works as a `RETURN` projection but blocks pushdown when it is a `GROUP BY` key, which is why the per-day shared-merchant burst (Q6) has no fast form. Grouping by the raw `t.txn_timestamp` pushes down but returns roughly one row per transaction.

`ORDER BY` and `LIMIT` on the server run as a post-processing step rather than pushing down, but on an already-aggregated result that is a cheap local sort, so it matters only when the aggregation itself did not push down. EXPLAIN reports the materialization as a `Neo.ClientNotification.Statement.VirtualGraphPostProcessing` notification, so prefix a query with `EXPLAIN` to check whether it will push down before running it.

Connection-pool behavior is the main operational hazard.

- The Virtual Graph holds a small JDBC connection pool to Databricks, observed maximum 10 connections.
- Killing or abandoning a slow query on the client does not cancel the underlying Databricks query. It keeps running and holds a pool connection. A few abandoned slow queries saturate the pool, after which every new query fails with `Neo.DatabaseError.Statement.ExecutionFailed: HikariPool-1 - Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0)`. Recovery needs those queries to finish on Databricks or the Virtual Graph instance to be restarted.
- The Bolt transaction timeout, `begin_transaction(timeout=...)`, is not honored, so you cannot bound a query server-side that way.

Practical guidance: run queries strictly one at a time, let each finish rather than abandoning it, keep result sets small, prefer the lighter aggregations, and back the Virtual Graph with a Databricks SQL warehouse large enough for the scan and aggregation cost.

## What plain Cypher covers vs. what needs GDS

| Signal | GDS version | Plain-Cypher equivalent |
|---|---|---|
| Mule / hub detection | PageRank | Degree counting with `count{}` (local proxy) |
| Fraud ring discovery | WCC / Louvain | Bounded-depth connectivity, shared-merchant co-occurrence |
| Bridge / layering node | Betweenness | Pass-through pattern (receives then forwards) |
| Coordinated bursts | community + temporal | Same-merchant / same-window grouping |

Plain Cypher loses transitive influence (PageRank weights a hub by the importance of who points at it, not just how many) and whole-graph community partitioning at scale. It keeps degree, reciprocity, cycles, fan-in/out, velocity, and co-occurrence, which are the workhorses of rules-based fraud detection.

## Graph schema

- `:Account` — `account_id`, `account_hash`, `account_type`, `region`, `balance`, `opened_date`, `holder_age`
- `:Merchant` — `merchant_id`, `merchant_name`, `category`, `region`
- `TRANSACTED_WITH` (`:Account` → `:Merchant`) — `amount`, `txn_timestamp`, `txn_hour`
- `TRANSFERRED_TO` (`:Account` → `:Account`) — `amount`, `transfer_timestamp`

The queries below use the loaded-graph labels `:Account` / `:Merchant`. On the Virtual Graph, swap to `:accounts` / `:merchants` as your model names them.

> **Virtual Graph compatibility.** The examples below are the reference, loaded-graph versions. They do not run verbatim on the Virtual Graph. The per-example **Virtual Graph: ✓ / ✗** markers indicate only whether the signal is achievable on the Virtual Graph at all, not that the Cypher as written runs there. Every checkmarked example requires the adaptations in the "Virtual Graph examples (verified)" and "Virtual Graph: patterns, tips, and what does not work" sections at the top of this file to run, most often moving the post-aggregation threshold filter client-side and replacing relative time windows with a `$since` parameter. See those two sections for the real support matrix. The one ✗ query (cycles) uses a variable-length path that the Virtual Graph cannot translate, and it needs the loaded Aura graph from `02_neo4j_ingest.ipynb`.

---

## 1. Fan-in (mule collection accounts)

Many distinct senders pushing into one account in a tight window is the classic collection-mule shape, and a local stand-in for high PageRank.

**Virtual Graph: ✓**

```cypher
CYPHER 25
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

---

## 2. Fan-out (distribution / smurfing)

Mirror of fan-in. One account spraying funds to many recipients, often right after a large inflow.

**Virtual Graph: ✓**

```cypher
CYPHER 25
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src,
     count(DISTINCT dst) AS recipients,
     sum(t.amount)       AS outflow
WHERE recipients >= 5
RETURN src.account_id, recipients, round(outflow, 2) AS outflow
ORDER BY recipients DESC
LIMIT 50
```

---

## 3. Pass-through mule (local betweenness proxy)

Account receives an amount and forwards roughly the same amount shortly after. This is what betweenness centrality flags globally, expressed as a local 2-hop rule.

**Virtual Graph: ✓** (no `WITH`; the 2-hop pattern is a single `MATCH`)

```cypher
CYPHER 25
MATCH (a:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(b:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND out.transfer_timestamp <= in.transfer_timestamp + duration({hours: 48})
  AND abs(out.amount - in.amount) <= 0.05 * in.amount   // forwards ~same value
  AND a <> b
RETURN mule.account_id,
       count(*)                 AS passthroughs,
       round(sum(in.amount), 2) AS volume
ORDER BY passthroughs DESC
LIMIT 50
```

---

## 4. Reciprocal / round-trip transfers

A pays B and B pays A back. Legitimate occasionally, but dense reciprocity inside a cluster signals wash activity.

**Virtual Graph: ✓** (no `WITH`; single `MATCH`)

```cypher
CYPHER 25
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id          // dedupe the pair
RETURN a.account_id, b.account_id,
       round(sum(f.amount + g.amount), 2) AS round_trip_volume,
       count(*)                            AS leg_count
ORDER BY round_trip_volume DESC
LIMIT 50
```

---

## 5. Layering cycles (loaded graph only)

Money leaving A and returning to A through intermediaries is textbook laundering. Bounded length keeps it tractable. This is the strongest single structural signal and a poor man's WCC/ring finder. The quantified path pattern `{2,4}` with the default `DIFFERENT RELATIONSHIPS` mode avoids walking the same edge twice. Use `MATCH ACYCLIC` if you want intermediate nodes distinct too.

**Virtual Graph: ✗** — the variable-length path `{2,4}` is a separate coverage gap, not the `WITH` rule, so reshaping does not help. Run it on the loaded Aura graph, or enumerate fixed lengths as separate single-`MATCH` queries (`(a)->(b)->(a)`, `(a)->(b)->(c)->(a)`, …) and `UNION` them.

```cypher
CYPHER 25
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
```

---

## 6. Shared-merchant burst (coordinated ring)

A group of accounts all hitting the same obscure merchant inside a short window. This is co-occurrence clustering without any community algorithm.

**Virtual Graph: ✓**

```cypher
CYPHER 25
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
WITH m, date(t.txn_timestamp) AS day,
     collect(DISTINCT a.account_id) AS accounts,
     count(t)                       AS txns
WHERE size(accounts) >= 4            // several accounts, same merchant, same day
  AND txns <= 200                    // skip genuinely high-traffic merchants
RETURN m.merchant_id, m.merchant_name, day,
       size(accounts) AS account_count, txns, accounts
ORDER BY account_count DESC
LIMIT 50
```

---

## 7. Structuring (just-under-threshold transfers)

Repeated transfers sized to stay below a reporting line.

**Virtual Graph: ✓**

```cypher
CYPHER 25
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
WHERE near_threshold >= 3
RETURN src.account_id, near_threshold, total
ORDER BY near_threshold DESC
LIMIT 50
```

---

## 8. New account, high velocity

Recently opened accounts moving large volume fast. Combines a node property with edge activity, no enrichment needed.

**Virtual Graph: ✓**

```cypher
CYPHER 25
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= date() - duration({days: 30})
WITH a, count(t) AS transfers, round(sum(t.amount), 2) AS outflow
WHERE transfers >= 10
RETURN a.account_id, a.opened_date, a.holder_age, transfers, outflow
ORDER BY outflow DESC
LIMIT 50
```

---

## 9. Hub network statistics

Per-account in-degree and out-degree, distinguishing distinct counterparties (connections) from raw transfer counts. A hub with many incoming connections and few outgoing is a collection or consolidation point.

**Virtual Graph: ✓** — reshaped below. The `LET`/`count{}` subquery form is cleaner on the loaded graph, but the Virtual Graph needs leading `OPTIONAL MATCH` clauses with `count(DISTINCT ...)`, which is robust to the cartesian fan-out between the two traversals.

```cypher
CYPHER 25
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

---

## 10. Rapid-turnover summary per account

Aggregates the pass-through pattern per account: how many receive-then-forward pairs happen within 24 hours, and the average turnaround. Short average turnaround across many pairs points to automated or coordinated movement.

**Virtual Graph: ✓** (no `WITH` before the `MATCH`; the 2-hop pattern is a single `MATCH`)

```cypher
CYPHER 25
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

---

## 11. Velocity ratio (volume vs. balance)

Total outbound transfer volume relative to current balance. A high ratio flags accounts that move far more money than they hold, which is the pass-through-vehicle shape.

> **Caveat:** `balance` is a current snapshot, not a time series. A pass-through account ends near empty by construction, so a small balance is partly a consequence of the behavior rather than independent evidence. Treat a high ratio as one weak signal, not proof. Account tenure (days since `opened_date`) or inflow-vs-outflow symmetry is a cleaner denominator.

**Virtual Graph: ✓**

```cypher
CYPHER 25
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

---

## 12. P2P-heavy, merchant-light disconnect

Accounts with heavy peer-to-peer transfer activity but almost no legitimate merchant spend. The disconnect between high P2P volume and low merchant activity is a useful fraud indicator.

**Virtual Graph: ✓** — reshaped below, same pattern as query 9. The merchant traversal is `OPTIONAL` so accounts with zero merchant activity (the `merchant_count < 20` case includes 0) are kept.

```cypher
CYPHER 25
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

---

## Interpretation caveats

These queries surface *candidates*, not confirmed fraud. Read the output with three things in mind.

- **Validate against ground truth.** The dataset includes a held-out `account_labels.is_fraud` table. Measure precision and recall of any rule against it before trusting it. Confident language ("clearly fraud") is not earned until you have.
- **Legitimate accounts share the fingerprint.** Payment aggregators, payroll processors, marketplace settlement accounts, and P2P-app float accounts show the same high fan-in, rapid turnover, and low own-merchant activity. The hard part is separating these from fraud, not finding high-throughput accounts.
- **Watch confounded metrics.** The velocity ratio (query 11) divides by current balance, which the behavior itself drives toward zero. Combine signals rather than ranking on any single confounded one.

---

## The honest limitation

What you cannot reproduce in plain Cypher is the ranking quality GDS gives. PageRank tells you an account is central because the accounts pointing at it are themselves central, which catches mules one layer removed from obvious hubs. Louvain/WCC partitions the entire graph into rings rather than surfacing fixed-shape patterns you anticipated.

The trade-off: plain Cypher gives you fast, explainable, rules-based candidates that are excellent for triage and for the "find the suspects" step in the analyst flow. GDS gives you the global scores that catch the rings your rules did not think to look for.

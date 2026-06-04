# Plain Cypher Fraud Signals (No Gold Enrichment, No GDS)

Most fraud signal in the Finance Genie graph is structural and temporal. Plain Cypher over the four base entities gets you most of the way:

- **Entities** : `:Account`, `:Merchant`, `TRANSACTED_WITH`, `TRANSFERRED_TO`.
- **What plain Cypher gives you** : every local signal an algorithm approximates, expressed directly.
- **What GDS and gold features add** : global, iterative scores you cannot compute exactly in one Cypher statement, such as PageRank, Louvain/WCC communities, and betweenness.

---

## Part A. Virtual Graph examples (verified)

These are the forms that actually run on the Aura Virtual Graph in this project. They are the adapted queries from `queries.py`.

**How the Virtual Graph works**
- **Translation** : Cypher becomes SQL over Databricks. Only a subset of Cypher is supported, so the reference queries in Part C do not run verbatim.
- **Shared query shape** : aggregate and order on the server, then apply the threshold filter and top-N client-side.
- **Recurring adaptation 1** : HAVING-style filters move into the application.
- **Recurring adaptation 2** : relative time windows become a precomputed `$since` parameter anchored to the dataset's maximum timestamp.

**Label and property gotchas**
- **Node labels** : this model uses singular `:Account` and `:Merchant`. A model generated from table names may instead use `:accounts` and `:merchants`. Match your model.
- **Relationship properties** : exist only if mapped in the Aura model.
- **`TRANSFERRED_TO` properties** : `amount`, `transfer_timestamp`, `link_id`.
- **`TRANSACTED_WITH` properties** : `amount`, `txn_timestamp`, `txn_hour`, `txn_id`.
- **Unmapped property columns** : the relationship still exists with zero properties, and any amount or timestamp query fails with "Could not resolve property".

**Reading the timings**
- **Provisional** : timings are dominated by the backing Databricks warehouse and the connection-pool behavior in Part B, not by the query text.

### What governs performance

Performance does not come down to a single rule, even though one rule does the most work. Think of it as two places where time gets spent, plus the machine everything sits on.

First, a few terms used below:

- **Scalar** (a single plain value like a number or a string, for example an `account_id` like `"A12345"`, as opposed to a whole node object).
- **Node** (a full graph object such as an `:Account`, carrying all its properties, not just one value).
- **Pushdown** (letting Databricks do the heavy counting and summing itself. Databricks is the big database engine that actually holds the data and is good at this work).
- **Materialize** (the opposite: the graph engine pulls every matching row back to itself first, then does the counting. This is the slow path).
- **Cardinality** (just "how many rows". High cardinality means a lot of rows).

#### Cost center 1: where the math happens

The question here is who does the counting and summing: Databricks (fast) or the graph engine (slow). You want Databricks. Four things decide it:

- **Group by a scalar, not a node** : this is the biggest lever. Tell it to group by `a.account_id` (one value) and Databricks does the work. Tell it to group by `a` (the whole node) and the graph engine drags every row home and does it by hand. Same answer, but Q8 and Q11 went from about 985 seconds down to about 1 to 3 seconds just from this change.
- **Avoid `count(DISTINCT ...)`** : this is its own separate trap, not the same as the node-versus-scalar one. Even with a clean scalar group key, adding `count(DISTINCT)` ran past 5 minutes with no result on Q2-pair. The fix is to group by pairs instead and count them yourself afterward.
- **Keep `ORDER BY` and `LIMIT` off the server** : sorting and "give me the top 50" on the server can add an extra cleanup step that slows things down. Q1-M was fast partly because it did neither on the server. Sort and trim in your own code instead.
- **Avoid accidental cross products** : an `OPTIONAL MATCH` that branches two ways multiplies rows together, then needs `DISTINCT` to undo the mess. Splitting the query into two simpler halves and joining them in your code (Q12-split) is faster.

#### Cost center 2: how much data moves and how big the join is

This one bites you even when cost center 1 is perfect. It is about volume and shape, not about who does the math.

- **How many rows come back** : every result row travels back over the wire, and that travel takes time. The all-time pair query returned 222966 rows in about 24.8 seconds even though it pushed down perfectly. Narrowing it to a recent 7-day window dropped it to 22096 rows and about 3.5 seconds. Fewer rows, faster query. Add a time window or a tighter filter to shrink the count.
- **Multi-hop joins are just expensive** : queries that follow two steps in a row (A sends to B, then B sends to C) do a lot of matching work no matter how you group them. The unbounded versions (Q3, Q10) did not finish within 100 seconds. Always bound or filter these.

#### Underneath both: the machine itself

The doc notes that real wall-clock time is usually set by the warehouse and the connection pool, not the query text:

- **Run one query at a time** : there are only 10 connections to Databricks. A few slow queries you walk away from keep running and use them all up, and then everything fails.
- **Size the warehouse** : a bigger Databricks SQL warehouse sets a faster floor for every scan and sum.

Three habits cover most of cost center 1 and recur below: group by scalar ids, replace `count(DISTINCT x)` with pair-grouping plus a client-side count, and split cross-product patterns into independent halves.

---

### Status: runs and is reasonably quick

#### Q4. Reciprocal / round-trip transfers

**What it does** : finds pairs where A pays B and B pays A back. Dense reciprocity inside a cluster signals wash activity.

**Pattern demonstrated** : a single `MATCH` with no HAVING-style filter, grouped on scalar id columns, pushes down cleanly.

- **Runs verbatim** : no client-side adaptation needed.
- **Why it is fast** : about 3s for 21052 rows. The grouping keys are the scalar `a.account_id` and `b.account_id` in the `RETURN`, so the aggregation pushes down with no reshape.

```cypher
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id
RETURN a.account_id AS a_id, b.account_id AS b_id,
       round(sum(f.amount + g.amount), 2) AS round_trip_volume,
       count(*)                            AS leg_count
ORDER BY round_trip_volume DESC
```

#### Q7. Structuring (just-under-threshold transfers)

**What it does** : finds accounts making repeated transfers sized to stay just below a reporting line.

**Pattern demonstrated** : grouping by a scalar id instead of a node is a roughly 40x speedup for the identical result.

- **Adaptation** : the `near_threshold >= 3` filter moves client-side.
- **Slow form** : grouping by the `src` node materializes intermediate results in the graph engine. About 38s, and the console warns about a "post-processing step that materialize intermediate results".
- **Fast form** : grouping by the scalar `src.account_id` pushes the `GROUP BY` down to the warehouse. About 1s on the same instance.
- **What does not matter** : dropping the trailing `(:Account)` label or the `round()` wrapper made no difference. Only the group key matters.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src.account_id AS account_id, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
RETURN account_id, near_threshold, total
ORDER BY near_threshold DESC
```

#### Q11. Velocity ratio (volume vs. balance)

**What it does** : ranks accounts by outbound volume relative to current balance, the pass-through-vehicle shape.

**Pattern demonstrated** : carry constant node properties as extra scalar grouping keys, then derive ratios client-side.

- **Slow form** : grouping by the `a` node materializes, the same shape that made node-grouped Q8 take about 985s.
- **Fast form** : group by scalar `a.account_id`, carry `a.balance` as a grouping key, about 3.4s over the full transfer table for 24951 accounts.
- **Stays server-side** : `a.balance > 0` in a leading `WHERE`.
- **Moves client-side** : the velocity ratio, the rounding, the `outflow > 0` filter, the sort, and the top-N.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.balance > 0
WITH a.account_id AS account_id, a.balance AS balance, sum(t.amount) AS outflow
RETURN account_id, balance, outflow
```

**Client-side step** : keep rows with `outflow > 0`, compute `velocity_ratio = round(outflow / balance, 1)`, round `balance` and `outflow`, sort by `velocity_ratio` descending, take the top-N.

#### Q1-M. Fan-in by transfer count (pushdown-friendly fan-in)

**What it does** : surfaces accounts receiving many incoming transfers in a recent 7-day window, the collection-mule shape, by counting transfers and summing inflow per recipient.

**Pattern demonstrated** : strip every construct that blocks pushdown so the whole aggregation runs on Databricks.

- **Why it is fast** : about 2s over the 7-day window. The group key is scalar `dst.account_id`, the aggregates are `count(t)` and `sum(t.amount)`, with no `count(DISTINCT)`, no `ORDER BY`, and no `LIMIT` on the server. EXPLAIN reports no post-processing step.
- **Scale** : 9847 grouped recipients, 1157 with 5 or more transfers.
- **Adaptation** : the 7-day window is a hard-coded datetime literal. The `transfers >= 5` threshold, the sort, and the top-N move client-side.
- **The cutoff** : `2024-03-23T23:58:00Z` is the dataset's maximum `transfer_timestamp` of `2024-03-30T23:58:00Z` minus 7 days.
- **Anchor to the dataset maximum, not `now()`** : the synthetic data ends 2024-03-30, so a window relative to the present returns nothing.
- **In production** : compute the cutoff and pass it as `$since`. The expression `datetime() - duration({days: 7})` inside `WHERE` is unsupported.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow
RETURN account_id, transfers, inflow
```

**Tradeoff against Q1-pair** : this counts edges, not distinct senders. Repeat transfers from the same source inflate the count, so a high `transfers` value is a weaker collection signal than a high distinct-sender count. Q1-pair recovers the distinct-sender count without losing pushdown.

#### Q1-pair. Fan-in by distinct senders (pushdown-friendly, full fidelity)

**What it does** : the faithful fan-in signal, distinct senders per recipient, expressed so it still pushes down. About 3.7s over the 7-day window, and it recovers the exact signal Q1-M trades away. Found 1127 accounts with 5 or more distinct senders.

**Pattern demonstrated** : replace `count(DISTINCT x)` with pair-grouping on the server plus a client-side group-and-count.

- **The trick** : group by the pair `(dst.account_id, src.account_id)`. A plain `GROUP BY` dedupes sender-recipient pairs and needs no `DISTINCT`, so it pushes down.
- **Server output** : one row per sender-recipient pair, about 22000 rows for the 7-day window.
- **Client-side step** : group those rows by recipient. The row count per recipient is the distinct-sender count. Sum `legs` for transfers and `pair_amount` for inflow.
- **Stays client-side** : the `senders >= 5` threshold, the sort, and the top-N.
- **Aliasing rule** : give the endpoints distinct aliases such as `recipient` and `sender`. Aliasing both to `account_id` collides in the generated SQL and fails with `AMBIGUOUS_REFERENCE`.
- **The cutoff** : same 7-day window as Q1-M. Parameterize as `$since` in production.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH dst.account_id AS recipient, src.account_id AS sender,
     count(t) AS legs, sum(t.amount) AS pair_amount
RETURN recipient, sender, legs, pair_amount
```

**General principle** : this is the standard way to recover a `count(DISTINCT x)` that will not push down. Group by `x` on the server and count the groups in the application.

#### Q2-pair. Fan-out by distinct recipients (pushdown-friendly, full fidelity)

**What it does** : the mirror of Q1-pair. Distinct recipients per sender, the smurfing signal.

**Pattern demonstrated** : the same pair-grouping trick, and that the `DISTINCT` itself is the blocker, not just the node group key.

- **Slow forms** : `count(DISTINCT dst)` grouped by the `src` node does not push down. Keeping `count(DISTINCT dst.account_id)` while grouping by scalar `src.account_id` does not push down either. It ran past 5 minutes without returning where the pair form finishes in seconds.
- **The fix** : group by the pair `(src.account_id, dst.account_id)`. One row per pair, no `DISTINCT`, pushes down.
- **Client-side step** : group rows by `sender`. The row count per sender is the distinct-recipient count. Sum `pair_transfers` and `pair_outflow`.
- **Stays client-side** : the `recipients >= 5` threshold, the sort, and the top-N.
- **Aliasing rule** : distinct aliases `sender` and `recipient`, or it fails with `AMBIGUOUS_REFERENCE`.
- **Q2 wants the time window** : fan-out is unfiltered by nature. All-time pair-grouping returns 222966 rows in about 24.8s, dominated by transferring that many rows. The 7-day window cuts it to 22096 pairs in about 3.5s, which is demo-ready. A burst of many recipients in a recent window is also the cleaner smurfing definition.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH src.account_id AS sender, dst.account_id AS recipient,
     count(t) AS pair_transfers, sum(t.amount) AS pair_outflow
RETURN sender, recipient, pair_transfers, pair_outflow
```

**Client-side step** : group rows by `sender`. `recipients` is the row count per sender, `transfers` is `sum(pair_transfers)`, `outflow` is `sum(pair_outflow)`. Parameterize the cutoff as `$since` in production.

#### Q8. New account, high velocity

**What it does** : finds recently opened accounts moving large volume fast. Combines a node property with edge activity.

**Pattern demonstrated** : the clearest single measurement of node-versus-scalar grouping cost in this file.

- **Fast form** : group by scalar `a.account_id`, carry `a.opened_date` and `a.holder_age` as grouping keys since they are constant per account. About 1s over the 30-day opened window, 452 accounts, 52 with 10 or more transfers.
- **Slow form** : the node-grouped form `WITH a, count(t) ...` took about 985s for the identical result.
- **The cutoff** : `2022-11-06` is the dataset's maximum `opened_date` of `2022-12-06` minus 30 days. Hard-code here, parameterize as `$since` in production. The expression `date() - duration({days: 30})` inside `WHERE` is unsupported.
- **Moves client-side** : the `transfers >= 10` threshold, the sort, and the top-N.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= date("2022-11-06")
WITH a.account_id AS account_id, a.opened_date AS opened_date,
     a.holder_age AS holder_age, count(t) AS transfers, sum(t.amount) AS outflow
RETURN account_id, opened_date, holder_age, transfers, outflow
```

#### Q9-roll. Hub statistics rolled up from the pair dataset (pushdown-friendly)

**What it does** : computes in-degree (distinct senders), out-degree (distinct recipients), and incoming transfer count per account.

**Pattern demonstrated** : one pushdown-friendly pair query feeds fan-in, fan-out, and hub statistics together. No dedicated hub query is needed.

- **Slow original** : Q9 grouped the `a` node with three `count(DISTINCT)` aggregates over a leading `OPTIONAL MATCH` cartesian fan-out. That is the exact non-pushdown shape: node group key, `count(DISTINCT)`, and a cross join.
- **Server output** : group by the pair `(src.account_id, dst.account_id)` over the whole transfer table. One row per directed pair, 222966 rows in about 24.8s. The cost is the row transfer, since there is no time filter.
- **Client-side rollup** : group rows by `recipient` for `incoming_conns` (row count, the distinct senders) and `incoming_txns` (`sum(legs)`). Group the same rows by `sender` for `outgoing_conns` (row count, the distinct recipients).

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src.account_id AS sender, dst.account_id AS recipient,
     count(t) AS legs, sum(t.amount) AS pair_amount
RETURN sender, recipient, legs, pair_amount
```

#### Q12-split. P2P-heavy, merchant-light via two pushdown halves

**What it does** : finds accounts with high peer-to-peer transfer activity and little merchant spend.

**Pattern demonstrated** : split a cross-product pattern into two independent single-`MATCH` aggregations, then join client-side.

- **Slow original** : Q12 used an undirected `-[tr]-` transfer pattern plus a leading `OPTIONAL MATCH` to merchants, with `count(DISTINCT tr)` and `count(DISTINCT tw)` over the cross product. The cross join exists only to undo it with `DISTINCT`.
- **The insight** : `count(DISTINCT tr)` is just transfer degree, since each incident edge is distinct, so plain `count(tr)` gives it. `count(DISTINCT tw)` is the merchant transaction count, a plain `count(tw)`.
- **Transfer-degree half** : pushes down in about 3.5s for 25000 accounts. This also confirms the undirected `-[tr:TRANSFERRED_TO]-` pattern translates and pushes down.

```cypher
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
WITH a.account_id AS account_id, count(tr) AS transfer_count
RETURN account_id, transfer_count
```

- **Merchant-count half** : pushes down in about 3.2s for 24999 accounts.
- **Aliasing caveat** : the `TRANSACTED_WITH` backing table exposes its own `account_id` column, so aliasing the group key to `account_id` fails with `AMBIGUOUS_REFERENCE` (`a.account_id` versus `tw.account_id`). Alias to something else and rename in `RETURN`. The `TRANSFERRED_TO` table has no such column, which is why the transfer half can alias to `account_id` directly.

```cypher
MATCH (a:Account)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a.account_id AS acct, count(tw) AS merchant_count
RETURN acct AS account_id, merchant_count
```

**Client-side step** : left-join transfer-degree rows with merchant-count rows on the account, defaulting `merchant_count` to 0 for accounts with no merchant activity. Keep accounts with `transfer_count >= 100 AND merchant_count < 20`, sort by `transfer_count` descending, take the top-N.

---

### Status: runs but expensive or slow on the backing warehouse

These are the unadapted forms. They run, but they are the slow shapes the queries above were rewritten to avoid.

#### Q1. Fan-in (mule collection accounts)

**What it does** : many distinct senders pushing into one account in a recent window.

**Why it is slow** : `count(DISTINCT src)` grouped by the `dst` node cannot push down. Use Q1-M or Q1-pair instead.

- **Adaptation** : the 7-day window becomes `$since`, and `senders >= 5` moves client-side.

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

**What it does** : one account spraying funds to many recipients.

**Why it is slow** : `count(DISTINCT dst)` grouped by the `src` node cannot push down. Use Q2-pair instead.

- **Adaptation** : `recipients >= 5` moves client-side.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src,
     count(DISTINCT dst) AS recipients,
     sum(t.amount)       AS outflow
RETURN src.account_id AS account_id, recipients, round(outflow, 2) AS outflow
ORDER BY recipients DESC
```

#### Q3. Pass-through mule (local betweenness proxy)

**What it does** : an account receives an amount and forwards roughly the same value. A local stand-in for betweenness centrality.

**Why it is slow** : an unbounded two-hop join.

- **Adaptation** : the 48-hour forward window is dropped, because temporal arithmetic in a `WHERE` is unsupported. The forward-after-receive ordering and the 5% same-value test are kept.

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

**What it does** : a group of accounts all hitting the same merchant on the same day. Co-occurrence clustering with no community algorithm.

**Why it is here** : it runs, but `account_count >= 4` and `txns <= 200` must move client-side.

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

**What it does** : per-account in-degree and out-degree by distinct counterparty.

**Why it is slow** : the leading `OPTIONAL MATCH` with three `count(DISTINCT ...)` aggregates is the cartesian-fan-out shape. Use Q9-roll instead.

- **Adaptation** : `incoming_conns >= 100` moves client-side.

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

**What it does** : receive-then-forward pairs per account, with average turnaround. Short average turnaround across many pairs points to automated movement.

**Why it is slow** : an unbounded two-hop join that may hit the timeout.

- **Adaptation** : the 24-hour window is dropped, because temporal arithmetic in a `WHERE` is unsupported. Turnaround is computed in `RETURN` from `.epochMillis`, and `rapid_pairs >= 50` moves client-side.

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

**What it does** : heavy peer-to-peer activity with little merchant spend.

**Why it is slow** : the `OPTIONAL MATCH` cross product with two `count(DISTINCT)` aggregates. Use Q12-split instead.

- **Adaptation** : `transfer_count >= 100` and `merchant_count < 20` move client-side. The merchant traversal is `OPTIONAL` so accounts with zero merchant activity are kept.

```cypher
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
OPTIONAL MATCH (a)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a,
     count(DISTINCT tr) AS transfer_count,
     count(DISTINCT tw) AS merchant_count
RETURN a.account_id AS account_id, transfer_count, merchant_count
ORDER BY transfer_count DESC
```

---

### Status: not supported on the Virtual Graph

#### Q5. Layering cycles

**What it does** : money leaving A and returning to A through intermediaries. The strongest single structural laundering signal.

**Why it fails** : the variable-length path `{2,4}` is unsupported. Reshaping the `WITH` does not help, because the gap is the path pattern itself.

- **Workaround** : run it on a loaded Aura graph, or enumerate fixed-length patterns and `UNION` them.

```cypher
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
```

---

## Part B. Virtual Graph: patterns, tips, and what does not work

The operational behavior matters more than the Cypher subset.

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
| Writes | `SET`, `CREATE`, `MERGE` all fail. The Virtual Graph is read-only. Properties exist only if mapped from a backing table column in the Aura model. |
| HAVING-style filtering | Any `WHERE` placed after an aggregating `WITH` that filters on an aggregate alias fails, with or without a leading `WHERE`. |
| Temporal arithmetic and functions in a filtering `WHERE` | `datetime() - duration({...})`, `date() - duration({...})`, timestamp-plus-duration compared across relationships, `duration.inSeconds(...)` and `duration.between(...)` in `WHERE`, and `.epochMillis` subtraction in `WHERE`. The same functions work in `RETURN`. |
| Variable-length and quantified path patterns | For example `(a)-[:TRANSFERRED_TO]->{2,4}(a)`. |
| `CYPHER 25` version prefix | Does not enable any of the above. |

### Adaptation patterns

How to make a standard Cypher query run on the Virtual Graph:

- **Move the threshold filter client-side** : have the server do `MATCH ... WITH <aggregates> ... RETURN ... ORDER BY <aggregate> DESC` with no post-`WITH` `WHERE` and no row-cutting `LIMIT`. Apply the threshold and top-N in the application. The grouped row count is bounded by the number of accounts, so this is cheap.
- **Replace relative time windows with a parameter** : compute the cutoff in the application and pass it as `$since`, then use `prop >= $since`. Anchor the window to the dataset's maximum timestamp, not `now()`. `max(transfer_timestamp)` is fast to query and makes a good anchor.
- **Drop the upper time bound on multi-hop windows** : keep the plain ordering `out.transfer_timestamp >= in.transfer_timestamp`. If you need average turnaround, compute it in `RETURN` from `.epochMillis`, not in the filter.
- **Move node-property predicates to a leading `WHERE`** : `WHERE a.balance > 0` belongs before the aggregating `WITH`. Only the aggregate comparison needs to move client-side.
- **For cycles** : enumerate fixed-length patterns and `UNION` them, or run against a loaded Aura graph.

### Operational behavior and performance

Every query becomes SQL on the backing Databricks SQL warehouse.

| Query shape | Observed timing |
|---|---|
| `RETURN 1` | about 0.3s |
| `count` of 25000 nodes | about 4s |
| `max(timestamp)` | about 1 to 2s |
| Single-hop aggregation scanning the full relationship table | roughly 40 to 45s |
| `count(DISTINCT ...)` grouped by a node over the full transfer table | did not finish within 100s |
| Two-hop pattern joins (pass-through and rapid-turnover) | very expensive; an unbounded one did not finish within 100s |

**Connection-pool behavior is the main operational hazard:**

- **Small pool** : the Virtual Graph holds a small JDBC connection pool to Databricks, observed maximum 10 connections.
- **Abandoning does not cancel** : killing a slow query on the client does not cancel the underlying Databricks query. It keeps running and holds a pool connection.
- **Saturation** : a few abandoned slow queries saturate the pool, after which every new query fails with `Neo.DatabaseError.Statement.ExecutionFailed: HikariPool-1 - Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0)`. Recovery needs those queries to finish on Databricks or the instance to be restarted.
- **No server-side timeout** : the Bolt transaction timeout `begin_transaction(timeout=...)` is not honored, so you cannot bound a query that way.

**Practical guidance:**

- **Run one at a time** : let each query finish rather than abandoning it.
- **Keep result sets small** : prefer the lighter aggregations.
- **Size the warehouse** : back the Virtual Graph with a Databricks SQL warehouse large enough for the scan and aggregation cost.

---

## Part C. Reference: loaded-graph versions

These are the standard, loaded-graph forms of each signal. They do not run verbatim on the Virtual Graph. The **Virtual Graph: ✓ / ✗** markers indicate only whether the signal is achievable at all, not that the Cypher runs as written. Every ✓ example needs the adaptations from Part A and Part B, most often moving the post-aggregation filter client-side and replacing relative time windows with `$since`. The one ✗ query, cycles, uses a variable-length path the Virtual Graph cannot translate and needs the loaded Aura graph from `02_neo4j_ingest.ipynb`.

### Graph schema

- **`:Account`** : `account_id`, `account_hash`, `account_type`, `region`, `balance`, `opened_date`, `holder_age`
- **`:Merchant`** : `merchant_id`, `merchant_name`, `category`, `region`
- **`TRANSACTED_WITH`** (`:Account` → `:Merchant`) : `amount`, `txn_timestamp`, `txn_hour`
- **`TRANSFERRED_TO`** (`:Account` → `:Account`) : `amount`, `transfer_timestamp`

The queries below use the loaded-graph labels `:Account` / `:Merchant`. On the Virtual Graph, swap to `:accounts` / `:merchants` as your model names them.

#### 1. Fan-in (mule collection accounts)

**What it does** : many distinct senders pushing into one account in a tight window. The classic collection-mule shape and a local stand-in for high PageRank.

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

#### 2. Fan-out (distribution / smurfing)

**What it does** : the mirror of fan-in. One account spraying funds to many recipients, often right after a large inflow.

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

#### 3. Pass-through mule (local betweenness proxy)

**What it does** : an account receives an amount and forwards roughly the same amount shortly after. What betweenness centrality flags globally, expressed as a local 2-hop rule.

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

#### 4. Reciprocal / round-trip transfers

**What it does** : A pays B and B pays A back. Legitimate occasionally, but dense reciprocity inside a cluster signals wash activity.

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

#### 5. Layering cycles (loaded graph only)

**What it does** : money leaving A and returning to A through intermediaries. Textbook laundering, and a poor man's WCC/ring finder. The quantified path `{2,4}` with the default `DIFFERENT RELATIONSHIPS` mode avoids walking the same edge twice. Use `MATCH ACYCLIC` if you want intermediate nodes distinct too.

**Virtual Graph: ✗** — the variable-length path `{2,4}` is a coverage gap, not the `WITH` rule, so reshaping does not help. Run it on the loaded Aura graph, or enumerate fixed lengths as separate single-`MATCH` queries and `UNION` them.

```cypher
CYPHER 25
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
```

#### 6. Shared-merchant burst (coordinated ring)

**What it does** : a group of accounts all hitting the same obscure merchant inside a short window. Co-occurrence clustering without any community algorithm.

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

#### 7. Structuring (just-under-threshold transfers)

**What it does** : repeated transfers sized to stay below a reporting line.

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

#### 8. New account, high velocity

**What it does** : recently opened accounts moving large volume fast. Combines a node property with edge activity, no enrichment needed.

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

#### 9. Hub network statistics

**What it does** : per-account in-degree and out-degree, distinguishing distinct counterparties (connections) from raw transfer counts. A hub with many incoming connections and few outgoing is a collection or consolidation point.

**Virtual Graph: ✓** — reshaped. The `LET`/`count{}` subquery form is cleaner on the loaded graph, but the Virtual Graph needs leading `OPTIONAL MATCH` clauses with `count(DISTINCT ...)`.

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

#### 10. Rapid-turnover summary per account

**What it does** : aggregates the pass-through pattern per account. How many receive-then-forward pairs happen within 24 hours, and the average turnaround. Short average turnaround across many pairs points to automated or coordinated movement.

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

#### 11. Velocity ratio (volume vs. balance)

**What it does** : total outbound transfer volume relative to current balance. A high ratio flags accounts that move far more money than they hold, the pass-through-vehicle shape.

> **Caveat:** `balance` is a current snapshot, not a time series. A pass-through account ends near empty by construction, so a small balance is partly a consequence of the behavior rather than independent evidence. Treat a high ratio as one weak signal. Account tenure (days since `opened_date`) or inflow-vs-outflow symmetry is a cleaner denominator.

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

#### 12. P2P-heavy, merchant-light disconnect

**What it does** : accounts with heavy peer-to-peer transfer activity but almost no legitimate merchant spend. The disconnect between high P2P volume and low merchant activity is a useful fraud indicator.

**Virtual Graph: ✓** — reshaped, same pattern as query 9. The merchant traversal is `OPTIONAL` so accounts with zero merchant activity are kept.

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

These queries surface *candidates*, not confirmed fraud.

- **Validate against ground truth** : the dataset includes a held-out `account_labels.is_fraud` table. Measure precision and recall of any rule against it before trusting it. Confident language such as "clearly fraud" is not earned until you have.
- **Legitimate accounts share the fingerprint** : payment aggregators, payroll processors, marketplace settlement accounts, and P2P-app float accounts show the same high fan-in, rapid turnover, and low own-merchant activity. The hard part is separating these from fraud, not finding high-throughput accounts.
- **Watch confounded metrics** : the velocity ratio in query 11 divides by current balance, which the behavior itself drives toward zero. Combine signals rather than ranking on any single confounded one.

---

## What plain Cypher covers vs. what needs GDS

| Signal | GDS version | Plain-Cypher equivalent |
|---|---|---|
| Mule / hub detection | PageRank | Degree counting with `count{}` (local proxy) |
| Fraud ring discovery | WCC / Louvain | Bounded-depth connectivity, shared-merchant co-occurrence |
| Bridge / layering node | Betweenness | Pass-through pattern (receives then forwards) |
| Coordinated bursts | community + temporal | Same-merchant / same-window grouping |

**What plain Cypher loses:**
- **Transitive influence** : PageRank weights a hub by the importance of who points at it, not just how many.
- **Whole-graph community partitioning** : at scale.

**What plain Cypher keeps** : degree, reciprocity, cycles, fan-in/out, velocity, and co-occurrence, the workhorses of rules-based fraud detection.

**The honest limitation** : what you cannot reproduce in plain Cypher is the ranking quality GDS gives. PageRank catches mules one layer removed from obvious hubs. Louvain/WCC partitions the entire graph into rings rather than surfacing fixed-shape patterns you anticipated.

**The trade-off** : plain Cypher gives you fast, explainable, rules-based candidates, excellent for triage and for the "find the suspects" step. GDS gives you the global scores that catch the rings your rules did not think to look for.

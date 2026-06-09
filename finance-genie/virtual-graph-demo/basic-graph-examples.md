# Basic Graph Examples (Virtual Graph)

Warm-up queries for the Finance Genie Virtual Graph: simple counts and small
relationship traversals that show the value of the graph without any fraud
logic. They are the queries to open a demo with, before the structural fraud
signals in [`finding-fraud.md`](finding-fraud.md).

Every query here was verified live against the Aura Virtual Graph backed by the
Databricks Silver tables. Each one runs through the `basic` demo:

```bash
cd virtual-graph-demo
uv run vg-demo --demo basic
```

The dataset is 25,000 accounts, 7,500 merchants, 300,000 transfers, and 250,000
merchant transactions. Node labels are `:Account` and `:Merchant`. If your model
uses the generated table-name labels (`:accounts` / `:merchants`), adjust them.

## How to read the two kinds

The queries split into two kinds.

- **Table** queries return scalar rows. They feed a table or bar-chart widget and
  print directly in the CLI demo.
- **Graph** queries return node and relationship variables. The payoff is the
  picture in the Aura Workspace Query tab, which renders the returned nodes and
  edges as a graph. The CLI demo only reports the row count for these, so run
  them in the Workspace to see the visualization.

The graph queries anchor on a specific `account_id` or `merchant_id`. Anchoring
pushes a selective filter down to Databricks, which keeps the query fast and the
result small enough to render. An unanchored two-hop traversal scans the full
relationship table and is slow. The demo prints which anchor ids it picked so
you can paste the same query into the Workspace. Swap in any id you like.

Timings below come from the runs against this instance. They are dominated by the
backing Databricks warehouse, so treat them as rough.

## Counts and breakdowns (table)

### 1. How many accounts

A single label count, sub-second. Counting two labels in one statement
(`MATCH ... WITH count ... MATCH ...`) fails with `42NG0`, so keep them separate.

```cypher
MATCH (a:Account) RETURN count(a) AS accounts
```

### 2. How many merchants

```cypher
MATCH (m:Merchant) RETURN count(m) AS merchants
```

### 3. Accounts by type

Group-by on a scalar property pushes straight down to the warehouse. Good
bar-chart widget. About 0.5s.

```cypher
MATCH (a:Account)
RETURN a.account_type AS account_type, count(*) AS accounts
ORDER BY accounts DESC
```

### 4. Accounts by region

```cypher
MATCH (a:Account)
RETURN a.region AS region, count(*) AS accounts
ORDER BY accounts DESC
```

### 5. Merchants by category

```cypher
MATCH (m:Merchant)
RETURN m.category AS category, count(*) AS merchants
ORDER BY merchants DESC
```

### 6. Top merchants by distinct customers

The first query that touches the edges. It scans the full `TRANSACTED_WITH`
relationship, so it is slower than the counts above, about 3s on this instance.

```cypher
MATCH (a:Account)-[:TRANSACTED_WITH]->(m:Merchant)
RETURN m.merchant_name AS merchant, count(DISTINCT a) AS customers
ORDER BY customers DESC
LIMIT 10
```

## Visualizations (graph)

Run these in the Aura Workspace Query tab to see the graph. The `$account_id`
and `$merchant_id` parameters are the anchors; replace them with a literal id, or
let the demo supply them.

### 7. Ego network: one account and the merchants it shops at

The simplest "here is the graph" shot: one account in the center, its merchants
fanned out around it, colored by category. Anchored, so about 3s.

```cypher
MATCH (a:Account {account_id: $account_id})-[t:TRANSACTED_WITH]->(m:Merchant)
RETURN a, t, m
LIMIT 25
```

### 8. Ego network: one account and its transfer partners

The peer-to-peer view of the same account. The pattern is undirected, so it shows
money flowing both in and out. About 5s.

```cypher
MATCH (a:Account {account_id: $account_id})-[t:TRANSFERRED_TO]-(b:Account)
RETURN a, t, b
LIMIT 25
```

### 9. Merchant star: one merchant and the accounts that use it

Flip the ego network around the merchant. One merchant in the center with its
customers around it. About 6s.

```cypher
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant {merchant_id: $merchant_id})
RETURN a, t, m
LIMIT 25
```

### 10. Two-hop: accounts linked through a shared merchant

The query that earns the graph database. Two accounts are connected not by a
direct transfer but because they shop at the same merchant. A table cannot show
this link; the graph draws it in one hop through the merchant. Anchored, but the
merchant fan-out makes it about 10s.

```cypher
MATCH (a:Account {account_id: $account_id})-[t1:TRANSACTED_WITH]->(m:Merchant)
      <-[t2:TRANSACTED_WITH]-(b:Account)
WHERE a <> b
RETURN a, t1, m, t2, b
LIMIT 25
```

### 11. Two-hop: transfer chain

Follow the money two hops out: who does my counterparty pay? The chain shape is
the point, and it renders as a path. Fast, under 1s.

```cypher
MATCH p=(a:Account {account_id: $account_id})-[:TRANSFERRED_TO]->(b:Account)
        -[:TRANSFERRED_TO]->(c:Account)
RETURN a, b, c
LIMIT 25
```

## Why anchoring matters

The Virtual Graph compiles Cypher into SQL and pushes most of it down to the backing
Databricks warehouse. A query anchored on a single node id becomes a selective SQL filter that the
warehouse runs quickly and that returns a handful of rows. The same two-hop
pattern with no anchor becomes a full join across the relationship table, which
is slow and returns far too many rows to draw. For demos and visualizations,
always start from a specific account or merchant.

For how the warehouse and the small JDBC connection pool shape performance, plus the
behavior of queries that keep running after the client gives up and the read-only
constraint, see the "Performance and the connection pool" section of
[`best-practices.md`](best-practices.md).

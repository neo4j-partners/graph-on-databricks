"""Virtual-Graph-compatible Finance Genie fraud-signal queries.

The fraud queries come in two tiers:

* ``tier="fast"`` are the pushdown-friendly forms from ``finding-fraud.md``. They
  run by default and each returns in a few seconds. The whole point of the rewrite work
  recorded in ``docs/plain-cypher-examples-v2.md`` is that these group by scalar ids
  (not whole nodes) and avoid ``count(DISTINCT)`` over a node group, so Databricks does
  the aggregation instead of dragging every row back to the graph engine.
* ``tier="slow"`` are the shapes that have no fast equivalent. They are kept to
  demonstrate what does not work on the Virtual Graph and are skipped unless ``--all``
  is passed. Three are supported but expensive (unbounded two-hop joins, a
  ``collect(DISTINCT)`` over a node group); one (layering cycles) is genuinely
  unsupported because it needs a variable-length path (``42NG0``).

Two adaptations recur in the fast tier:

1. **HAVING moves client-side.** The server aggregates and orders only; the threshold
   filter (``client_filter``) and the top-N are applied in Python. A ``WHERE`` after an
   aggregating ``WITH`` fails with ``42NG0``.
2. **Relative time windows become a ``$since`` parameter** anchored to the dataset's max
   timestamp, since temporal arithmetic inside a ``WHERE`` is unsupported (``42NG0``).

Two of the fast queries also reshape a ``count(DISTINCT ...)`` that will not push down:

* **Pair-grouping + rollup** (fan-in, fan-out). The server groups by the
  ``(recipient, sender)`` pair, which is a plain ``GROUP BY`` that pushes down. The
  client then groups those rows by one endpoint; the row count per endpoint is the
  distinct-counterparty count. This is the ``rollup`` hook.
* **Split + merge** (courier). Two independent single-``MATCH`` aggregations replace one
  ``OPTIONAL MATCH`` cross product, joined client-side with a default of zero for the
  missing side (``enrich_*``), which keeps the zero-merchant accounts the signal targets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Row = dict[str, Any]


@dataclass(frozen=True)
class Query:
    number: int
    title: str
    cypher: str
    # "fast" runs by default; "slow" runs only with --all (guarded, may be slow or fail).
    tier: str = "fast"
    # False marks a query the Virtual Graph cannot translate at all (expected failure).
    vg_supported: bool = True
    # If set, ``since_param`` (helpers.py) computes ``$since`` = (data max for
    # ``since_source``) - N days.
    since_window_days: int | None = None
    since_source: str = "transfer"  # "transfer" (timestamp) or "opened" (account date)
    since_kind: str = "datetime"  # "datetime" or "date"
    # Client-side rollup: group the server's pair rows into per-account rows (and sort).
    rollup: Callable[[list[Row]], list[Row]] | None = None
    # Client-side HAVING: keep a row only if this returns True.
    client_filter: Callable[[Row], bool] | None = None
    top: int = 50
    # OPTIONAL MATCH replacement: a second aggregation merged onto the main rows by
    # ``enrich_key``. Columns in ``enrich_columns`` are copied from the matching
    # enrich row, or set to the given default when the account has no enrich row.
    enrich_cypher: str | None = None
    enrich_key: str = "account_id"
    enrich_columns: dict[str, Any] = field(default_factory=dict)
    note: str = ""  # how this differs from the doc version


def rollup_fan_in(rows: list[Row]) -> list[Row]:
    """Group server pair rows by recipient; the row count is the distinct-sender count."""
    agg: dict[Any, Row] = {}
    for r in rows:
        a = agg.setdefault(r["recipient"], {"account_id": r["recipient"],
                                            "senders": 0, "transfers": 0, "inflow": 0.0})
        a["senders"] += 1
        a["transfers"] += r["legs"]
        a["inflow"] += r["pair_amount"]
    out = sorted(agg.values(), key=lambda a: a["senders"], reverse=True)
    for a in out:
        a["inflow"] = round(a["inflow"], 2)
    return out


def rollup_fan_out(rows: list[Row]) -> list[Row]:
    """Group server pair rows by sender; the row count is the distinct-recipient count."""
    agg: dict[Any, Row] = {}
    for r in rows:
        a = agg.setdefault(r["sender"], {"account_id": r["sender"],
                                         "recipients": 0, "transfers": 0, "outflow": 0.0})
        a["recipients"] += 1
        a["transfers"] += r["pair_transfers"]
        a["outflow"] += r["pair_outflow"]
    out = sorted(agg.values(), key=lambda a: a["recipients"], reverse=True)
    for a in out:
        a["outflow"] = round(a["outflow"], 2)
    return out


QUERIES: list[Query] = [
    # ----------------------------------------------------------------------- #
    # Fast tier: the pushdown-friendly forms from finding-fraud.md.
    # ----------------------------------------------------------------------- #
    Query(
        number=1,
        title="Structuring (just-under-threshold transfers)",
        note="Group by scalar account_id (pushes down). Ranked, no threshold.",
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src.account_id AS account_id, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
RETURN account_id, near_threshold, total
ORDER BY near_threshold DESC
""",
    ),
    Query(
        number=2,
        title="Busy brand-new accounts (new account, high velocity)",
        since_window_days=30,
        since_source="opened",
        since_kind="date",
        note="30-day opened window via $since; scalar group key carries opened_date/holder_age.",
        cypher="""
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= $since
WITH a.account_id AS account_id, a.opened_date AS opened_date,
     a.holder_age AS holder_age, count(t) AS transfers, round(sum(t.amount), 2) AS outflow
RETURN account_id, opened_date, holder_age, transfers, outflow
ORDER BY outflow DESC
""",
    ),
    Query(
        number=3,
        title="Round trips between two accounts (reciprocal transfers)",
        note="Single MATCH grouped on scalar a_id/b_id; the a<b filter bounds the pair.",
        cypher="""
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id
RETURN a.account_id AS a_id, b.account_id AS b_id,
       round(sum(f.amount + g.amount), 2) AS round_trip_volume,
       count(*)                            AS leg_count
ORDER BY round_trip_volume DESC
""",
    ),
    Query(
        number=4,
        title="Velocity ratio (moves more than it holds)",
        note="balance>0 in a leading WHERE; scalar group key carries balance.",
        cypher="""
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.balance > 0
WITH a.account_id AS account_id, a.balance AS balance, sum(t.amount) AS outflow
RETURN account_id,
       round(balance, 2)           AS balance,
       round(outflow, 2)           AS outflow_volume,
       round(outflow / balance, 1) AS velocity_ratio
ORDER BY velocity_ratio DESC
""",
    ),
    Query(
        number=5,
        title="Collection accounts (fan-in by distinct senders)",
        since_window_days=7,
        since_source="transfer",
        rollup=rollup_fan_in,
        client_filter=lambda r: r["senders"] >= 5,
        note=(
            "7-day window via $since. Server groups by the (recipient, sender) pair "
            "(pushes down); the client rolls up by recipient so the row count is the "
            "distinct-sender count. senders>=5 filtered client-side."
        ),
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
WITH dst.account_id AS recipient, src.account_id AS sender,
     count(t) AS legs, sum(t.amount) AS pair_amount
RETURN recipient, sender, legs, pair_amount
""",
    ),
    Query(
        number=6,
        title="Spray accounts (fan-out by distinct recipients)",
        since_window_days=7,
        since_source="transfer",
        rollup=rollup_fan_out,
        client_filter=lambda r: r["recipients"] >= 5,
        note=(
            "7-day window via $since. Mirror of fan-in: server groups by the "
            "(sender, recipient) pair; the client rolls up by sender. recipients>=5 "
            "filtered client-side."
        ),
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
WITH src.account_id AS sender, dst.account_id AS recipient,
     count(t) AS pair_transfers, sum(t.amount) AS pair_outflow
RETURN sender, recipient, pair_transfers, pair_outflow
""",
    ),
    Query(
        number=7,
        title="Courier accounts (P2P-heavy, merchant-light)",
        client_filter=lambda r: r["transfer_count"] >= 100 and r["merchant_count"] < 20,
        note=(
            "Split into two pushdown halves instead of one OPTIONAL MATCH cross product: "
            "transfer degree is the main aggregation, merchant count is merged client-side "
            "(missing => 0), which keeps the zero-merchant accounts the signal targets. "
            "transfer_count>=100 and merchant_count<20 filtered client-side."
        ),
        cypher="""
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
WITH a.account_id AS account_id, count(tr) AS transfer_count
RETURN account_id, transfer_count
ORDER BY transfer_count DESC
""",
        enrich_cypher="""
MATCH (a:Account)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a.account_id AS acct, count(tw) AS merchant_count
RETURN acct AS account_id, merchant_count
""",
        enrich_columns={"merchant_count": 0},
    ),
    # ----------------------------------------------------------------------- #
    # Slow tier: kept to demonstrate what does not work. Skipped unless --all.
    # Signals with no fast equivalent in docs/plain-cypher-examples-v2.md.
    # ----------------------------------------------------------------------- #
    Query(
        number=8,
        title="Pass-through mule (local betweenness proxy)",
        tier="slow",
        note=(
            "Unbounded two-hop join; expensive and may hang or hit the read timeout. "
            "48h forward window dropped (temporal arithmetic in WHERE unsupported); "
            "forward-after-receive ordering and the same-value (5%) test are kept."
        ),
        cypher="""
MATCH (a:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(b:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND abs(out.amount - in.amount) <= 0.05 * in.amount
  AND a <> b
RETURN mule.account_id            AS account_id,
       count(*)                   AS passthroughs,
       round(sum(in.amount), 2)   AS volume
ORDER BY passthroughs DESC
""",
    ),
    Query(
        number=9,
        title="Shared-merchant burst (coordinated ring)",
        tier="slow",
        client_filter=lambda r: r["account_count"] >= 4 and r["txns"] <= 200,
        note=(
            "collect(DISTINCT ...) over a node group (m); expensive on the warehouse. "
            "account_count>=4 and txns<=200 filtered client-side."
        ),
        cypher="""
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant)
WITH m, date(t.txn_timestamp) AS day,
     collect(DISTINCT a.account_id) AS accounts,
     count(t)                       AS txns
RETURN m.merchant_id AS merchant_id, m.merchant_name AS merchant_name, day,
       size(accounts) AS account_count, txns, accounts
ORDER BY account_count DESC
""",
    ),
    Query(
        number=10,
        title="Rapid-turnover summary per account",
        tier="slow",
        client_filter=lambda r: r["rapid_pairs"] >= 50,
        note=(
            "Unbounded two-hop join; expensive and may hang or hit the read timeout. "
            "24h window dropped (temporal arithmetic in WHERE unsupported); average "
            "turnaround is computed over all forward-after-receive pairs via epochMillis. "
            "rapid_pairs>=50 filtered client-side."
        ),
        cypher="""
MATCH (src:Account)-[in:TRANSFERRED_TO]->(mule:Account)-[out:TRANSFERRED_TO]->(dst:Account)
WHERE out.transfer_timestamp >= in.transfer_timestamp
  AND src <> dst
WITH mule,
     count(*) AS rapid_pairs,
     round(avg(out.transfer_timestamp.epochMillis
               - in.transfer_timestamp.epochMillis) / 3600000.0, 1) AS avg_turnaround_hours
RETURN mule.account_id AS account_id, rapid_pairs, avg_turnaround_hours
ORDER BY rapid_pairs DESC
""",
    ),
    Query(
        number=11,
        title="Layering cycles (loaded graph only)",
        tier="slow",
        vg_supported=False,
        note="Variable-length path {2,4} is unsupported on the Virtual Graph (42NG0).",
        cypher="""
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
""",
    ),
]


# --------------------------------------------------------------------------- #
# Basic exploration / visualization queries (``vg-demo --demo basic``)
# --------------------------------------------------------------------------- #
# These are the warm-up queries: simple counts and small, anchored traversals
# that demonstrate the value of the relationships without any fraud logic. They
# were verified live on the Virtual Graph and are documented in
# ``basic-graph-examples.md``.
#
# Two kinds:
#   - ``kind="table"``: returns scalar rows; the basic demo prints them as a table.
#   - ``kind="graph"``: returns node and relationship entities. The point is the
#     graph picture in the Aura Workspace Query tab, not the CLI output, so the
#     basic demo prints only the row count and timing and tells you to run it there.
#
# The anchored graph queries take ``$account_id`` and ``$merchant_id`` parameters.
# The basic demo picks a well-connected anchor account and a merchant at runtime and
# prints which ids it used, so the same query can be pasted into the Workspace.


@dataclass(frozen=True)
class BasicQuery:
    number: int
    title: str
    cypher: str
    kind: str = "table"  # "table" (print rows) or "graph" (for Aura visualization)
    note: str = ""


BASIC_QUERIES: list[BasicQuery] = [
    BasicQuery(
        number=1,
        title="How many accounts",
        kind="table",
        note=(
            "A single label count, sub-second. Counting two labels in one statement "
            "(MATCH ... WITH count ... MATCH ...) fails with 42NG0, so keep them separate."
        ),
        cypher="""
MATCH (a:Account) RETURN count(a) AS accounts
""",
    ),
    BasicQuery(
        number=2,
        title="How many merchants",
        kind="table",
        cypher="""
MATCH (m:Merchant) RETURN count(m) AS merchants
""",
    ),
    BasicQuery(
        number=3,
        title="Accounts by type",
        kind="table",
        note="Group-by on a scalar property. Good bar-chart widget.",
        cypher="""
MATCH (a:Account)
RETURN a.account_type AS account_type, count(*) AS accounts
ORDER BY accounts DESC
""",
    ),
    BasicQuery(
        number=4,
        title="Accounts by region",
        kind="table",
        cypher="""
MATCH (a:Account)
RETURN a.region AS region, count(*) AS accounts
ORDER BY accounts DESC
""",
    ),
    BasicQuery(
        number=5,
        title="Merchants by category",
        kind="table",
        cypher="""
MATCH (m:Merchant)
RETURN m.category AS category, count(*) AS merchants
ORDER BY merchants DESC
""",
    ),
    BasicQuery(
        number=6,
        title="Top merchants by distinct customers",
        kind="table",
        note="Full TRANSACTED_WITH scan; ~10s. The first query that needs the edges.",
        cypher="""
MATCH (a:Account)-[:TRANSACTED_WITH]->(m:Merchant)
RETURN m.merchant_name AS merchant, count(DISTINCT a) AS customers
ORDER BY customers DESC
LIMIT 10
""",
    ),
    BasicQuery(
        number=7,
        title="Ego network: one account and the merchants it shops at",
        kind="graph",
        note="Anchored on $account_id, so it stays small and fast (~4s).",
        cypher="""
MATCH (a:Account {account_id: $account_id})-[t:TRANSACTED_WITH]->(m:Merchant)
RETURN a, t, m
LIMIT 25
""",
    ),
    BasicQuery(
        number=8,
        title="Ego network: one account and its transfer partners",
        kind="graph",
        note="Undirected so it shows money in and out (~6s).",
        cypher="""
MATCH (a:Account {account_id: $account_id})-[t:TRANSFERRED_TO]-(b:Account)
RETURN a, t, b
LIMIT 25
""",
    ),
    BasicQuery(
        number=9,
        title="Merchant star: one merchant and the accounts that use it",
        kind="graph",
        note="Anchored on $merchant_id (~6s).",
        cypher="""
MATCH (a:Account)-[t:TRANSACTED_WITH]->(m:Merchant {merchant_id: $merchant_id})
RETURN a, t, m
LIMIT 25
""",
    ),
    BasicQuery(
        number=10,
        title="2-hop: accounts linked to the anchor through a shared merchant",
        kind="graph",
        note=(
            "The 'value of the graph' shot: an indirect connection a table cannot show. "
            "Anchored, but the merchant fan-out makes it ~10s."
        ),
        cypher="""
MATCH (a:Account {account_id: $account_id})-[t1:TRANSACTED_WITH]->(m:Merchant)
      <-[t2:TRANSACTED_WITH]-(b:Account)
WHERE a <> b
RETURN a, t1, m, t2, b
LIMIT 25
""",
    ),
    BasicQuery(
        number=11,
        title="2-hop: transfer chain (who does my counterparty pay)",
        kind="graph",
        note="Fast (~1.5s); the chain shape is the point.",
        cypher="""
MATCH p=(a:Account {account_id: $account_id})-[:TRANSFERRED_TO]->(b:Account)
        -[:TRANSFERRED_TO]->(c:Account)
RETURN a, b, c
LIMIT 25
""",
    ),
]

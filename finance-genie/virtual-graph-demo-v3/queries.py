"""Virtual-Graph-compatible versions of the Finance Genie fraud-signal queries.

These are the queries from ``docs/plain-cypher-examples.md``, adapted to the Cypher
subset the Aura Virtual Graph actually translates to SQL. The boundary was settled
empirically with ``capability_probe.py`` (EXPLAIN mode) and is recorded in
``demo-testplan.md``. Four constructs and only four fail to translate:

1. **HAVING** (a ``WHERE`` after an aggregating ``WITH``), ``42NG0``. The server
   query aggregates and ``ORDER BY``s only; the threshold is applied in Python
   (``client_filter``) and the top-N is taken after filtering.
2. **Temporal arithmetic inside a ``WHERE``** (``datetime()/date() - duration({...})``),
   ``42NG0``. "Recent" windows instead compare against a precomputed ``$since``
   parameter, a plain comparison that translates. The cutoff is anchored to the
   dataset's max timestamp, not ``now()``.
3. **``OPTIONAL MATCH``**, ``42NG1``. The optional side is computed as a second
   supported aggregation and merged client-side (``enrich_*``), with the missing
   side defaulting to zero. This preserves rows that have no optional match, which
   is exactly the population Q12 is looking for.
4. **Variable-length paths** (``->{2,4}``), ``42NG0``. Q5 cannot be expressed and
   is marked unsupported.

Constructs verified to translate: aggregation in ``WITH``/``RETURN``,
``count(DISTINCT)``, ``sum``/``round``/``avg``, ``collect(DISTINCT)``, ``size()``,
numeric arithmetic and ``abs()``, ``CASE``, undirected patterns, two-hop paths, and
plain timestamp comparison (``ts >= ts`` and ``ts >= $since``).
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
    vg_supported: bool = True
    # If set, main.py computes ``$since`` = (data max for ``since_source``) - N days.
    since_window_days: int | None = None
    since_source: str = "transfer"  # "transfer" (timestamp) or "opened" (account date)
    since_kind: str = "datetime"  # "datetime" or "date"
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


QUERIES: list[Query] = [
    Query(
        number=1,
        title="Fan-in (mule collection accounts)",
        since_window_days=7,
        since_source="transfer",
        client_filter=lambda r: r["senders"] >= 5,
        top=50,
        note="7-day window via $since parameter; senders>=5 filtered client-side.",
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
WITH dst,
     count(DISTINCT src) AS senders,
     count(t)            AS transfers,
     sum(t.amount)       AS inflow
RETURN dst.account_id AS account_id, senders, transfers, round(inflow, 2) AS inflow
ORDER BY senders DESC, inflow DESC
""",
    ),
    Query(
        number=2,
        title="Fan-out (distribution / smurfing)",
        client_filter=lambda r: r["recipients"] >= 5,
        top=50,
        note="recipients>=5 filtered client-side.",
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH src,
     count(DISTINCT dst) AS recipients,
     sum(t.amount)       AS outflow
RETURN src.account_id AS account_id, recipients, round(outflow, 2) AS outflow
ORDER BY recipients DESC
""",
    ),
    Query(
        number=3,
        title="Pass-through mule (local betweenness proxy)",
        top=50,
        note=(
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
        number=4,
        title="Reciprocal / round-trip transfers",
        top=50,
        note="Runs verbatim (single MATCH, no HAVING).",
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
        number=5,
        title="Layering cycles (loaded graph only)",
        vg_supported=False,
        top=50,
        note="Variable-length path {2,4} is unsupported on the Virtual Graph (42NG0).",
        cypher="""
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id AS ring_origin,
       length(path) AS hops,
       [n IN nodes(path) | n.account_id] AS cycle
LIMIT 50
""",
    ),
    Query(
        number=6,
        title="Shared-merchant burst (coordinated ring)",
        client_filter=lambda r: r["account_count"] >= 4 and r["txns"] <= 200,
        top=50,
        note="account_count>=4 and txns<=200 filtered client-side.",
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
        number=7,
        title="Structuring (just-under-threshold transfers)",
        client_filter=lambda r: r["near_threshold"] >= 3,
        top=50,
        note="near_threshold>=3 filtered client-side.",
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
RETURN src.account_id AS account_id, near_threshold, total
ORDER BY near_threshold DESC
""",
    ),
    Query(
        number=8,
        title="New account, high velocity",
        since_window_days=30,
        since_source="opened",
        since_kind="date",
        client_filter=lambda r: r["transfers"] >= 10,
        top=50,
        note="30-day opened window via $since parameter; transfers>=10 filtered client-side.",
        cypher="""
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= $since
WITH a, count(t) AS transfers, round(sum(t.amount), 2) AS outflow
RETURN a.account_id AS account_id, a.opened_date AS opened_date,
       a.holder_age AS holder_age, transfers, outflow
ORDER BY outflow DESC
""",
    ),
    Query(
        number=9,
        title="Hub network statistics",
        client_filter=lambda r: r["incoming_conns"] >= 100,
        top=15,
        note=(
            "OPTIONAL MATCH replaced: incoming side is the main aggregation, outgoing "
            "side is a second aggregation merged client-side (missing => 0). "
            "incoming_conns>=100 filtered client-side."
        ),
        cypher="""
MATCH (a:Account)<-[r_in:TRANSFERRED_TO]-(src:Account)
WITH a,
     count(DISTINCT src)  AS incoming_conns,
     count(DISTINCT r_in) AS incoming_txns
RETURN a.account_id AS account_id, incoming_conns, incoming_txns
ORDER BY incoming_conns DESC
""",
        enrich_cypher="""
MATCH (a:Account)-[:TRANSFERRED_TO]->(dst:Account)
WITH a, count(DISTINCT dst) AS outgoing_conns
RETURN a.account_id AS account_id, outgoing_conns
""",
        enrich_columns={"outgoing_conns": 0},
    ),
    Query(
        number=10,
        title="Rapid-turnover summary per account",
        client_filter=lambda r: r["rapid_pairs"] >= 50,
        top=15,
        note=(
            "24h window dropped (temporal arithmetic in WHERE unsupported); average "
            "turnaround is computed over all forward-after-receive pairs via epochMillis. "
            "Expensive unfiltered 2-hop join; may be slow or hit the query timeout."
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
        title="Velocity ratio (volume vs. balance)",
        client_filter=lambda r: r["outflow_volume"] > 0,
        top=25,
        note="balance>0 moved to leading WHERE; outflow>0 filtered client-side.",
        cypher="""
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.balance > 0
WITH a, sum(t.amount) AS outflow
RETURN a.account_id AS account_id,
       round(a.balance, 2)           AS balance,
       round(outflow, 2)             AS outflow_volume,
       round(outflow / a.balance, 1) AS velocity_ratio
ORDER BY velocity_ratio DESC
""",
    ),
    Query(
        number=12,
        title="P2P-heavy, merchant-light disconnect",
        client_filter=lambda r: r["transfer_count"] >= 100 and r["merchant_count"] < 20,
        top=25,
        note=(
            "OPTIONAL MATCH replaced: transfer count is the main aggregation, merchant "
            "count is a second aggregation merged client-side (missing => 0), which keeps "
            "the zero-merchant accounts the signal targets. transfer_count>=100 and "
            "merchant_count<20 filtered client-side."
        ),
        cypher="""
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
WITH a, count(DISTINCT tr) AS transfer_count
RETURN a.account_id AS account_id, transfer_count
ORDER BY transfer_count DESC
""",
        enrich_cypher="""
MATCH (a:Account)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a, count(DISTINCT tw) AS merchant_count
RETURN a.account_id AS account_id, merchant_count
""",
        enrich_columns={"merchant_count": 0},
    ),
]


# --------------------------------------------------------------------------- #
# Basic exploration / visualization queries (``main.py --basic``)
# --------------------------------------------------------------------------- #
# These are the warm-up queries: simple counts and small, anchored traversals
# that demonstrate the value of the relationships without any fraud logic. They
# were verified live on the Virtual Graph and are documented in
# ``docs/basic-graph-examples.md``.
#
# Two kinds:
#   - ``kind="table"``: returns scalar rows; main.py prints them as a table.
#   - ``kind="graph"``: returns node and relationship entities. The point is the
#     graph picture in the Aura Workspace Query tab, not the CLI output, so
#     main.py prints only the row count and timing and tells you to run it there.
#
# The anchored graph queries take ``$account_id`` and ``$merchant_id`` parameters.
# main.py picks a well-connected anchor account and a merchant at runtime and
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

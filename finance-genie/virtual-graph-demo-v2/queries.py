"""Virtual-Graph-compatible versions of the Finance Genie fraud-signal queries.

These mirror the verified forms in ``docs/plain-cypher-examples.md``. The Aura
Virtual Graph translates Cypher to SQL on the backing Databricks warehouse and runs
only a subset of Cypher; the boundary and the pushdown behavior were settled
empirically with ``capability_probe.py`` and the pushdown probes, and are recorded in
``demo-testplan.md``.

Two things decide whether a query is fast:

1. **Translation.** Four constructs do not translate: HAVING (a ``WHERE`` after an
   aggregating ``WITH``), temporal arithmetic inside a ``WHERE``, ``OPTIONAL MATCH``,
   and variable-length paths. They are worked around below.
2. **Pushdown.** A query translates but is slow if its aggregation cannot push down
   to Databricks, in which case it materializes intermediate rows in the graph
   engine. Pushdown requires the ``GROUP BY`` key to be a scalar property. Grouping
   by a **node** (``WITH a, ...``) does not push down; grouping by a scalar
   (``WITH a.account_id AS account_id, ...``) does. ``count(DISTINCT)`` does not push
   down either, and a function-derived key such as ``date(t.txn_timestamp)`` blocks
   pushdown even though ``date()`` works as a ``RETURN`` projection.

The adaptations applied here:

- **HAVING moves client-side** (``client_filter`` or ``post_process``); the server
  aggregates only.
- **Relative time windows become a ``$since`` parameter** anchored to the dataset's
  maximum timestamp, since temporal arithmetic in a ``WHERE`` is unsupported.
- **Node grouping becomes scalar grouping**, carrying any extra node properties as
  additional grouping keys (Q7, Q8, Q11).
- **``count(DISTINCT x)`` becomes a pair grouping**: group by the pair ``(key, x)``
  on the server, which dedupes with a plain ``GROUP BY`` and pushes down, then count
  the groups per key client-side in ``post_process`` (Q1, Q2).
- **``OPTIONAL MATCH`` becomes a second aggregation merged client-side** with the
  missing side defaulting to zero (``enrich_*``), preserving rows with no optional
  match (Q9, Q12).
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
    fast: bool = True  # pushes down and returns in a few seconds
    # If set, main.py computes ``$since`` = (data max for ``since_source``) - N days.
    since_window_days: int | None = None
    since_source: str = "transfer"  # "transfer" (timestamp) or "opened" (account date)
    since_kind: str = "datetime"  # "datetime" or "date"
    # Client-side HAVING: keep a row only if this returns True. Used when the server
    # query already returns display-ready rows in the right order.
    client_filter: Callable[[Row], bool] | None = None
    # Client-side reshaping: re-aggregation for pair-grouped queries, derived columns,
    # the threshold, and the sort. Receives the raw server rows, returns final rows.
    # Takes precedence over client_filter.
    post_process: Callable[[list[Row]], list[Row]] | None = None
    top: int = 50
    # OPTIONAL MATCH replacement: a second aggregation merged onto the main rows by
    # ``enrich_key``. Columns in ``enrich_columns`` are copied from the matching enrich
    # row, or set to the given default when the account has no enrich row.
    enrich_cypher: str | None = None
    enrich_key: str = "account_id"
    enrich_columns: dict[str, Any] = field(default_factory=dict)
    note: str = ""  # how this differs from the doc version


# --- Client-side reshaping for the pair-grouped and derived queries ---------------


def fanin_distinct_senders(rows: list[Row]) -> list[Row]:
    """Q1: re-aggregate (recipient, sender) pairs into distinct senders per recipient."""
    agg: dict[Any, Row] = {}
    for r in rows:
        g = agg.setdefault(r["recipient"], {
            "account_id": r["recipient"], "senders": 0, "transfers": 0, "inflow": 0.0})
        g["senders"] += 1
        g["transfers"] += r["legs"]
        g["inflow"] += r["pair_amount"]
    kept = [{**g, "inflow": round(g["inflow"], 2)}
            for g in agg.values() if g["senders"] >= 5]
    kept.sort(key=lambda r: (r["senders"], r["inflow"]), reverse=True)
    return kept


def fanout_distinct_recipients(rows: list[Row]) -> list[Row]:
    """Q2: re-aggregate (sender, recipient) pairs into distinct recipients per sender."""
    agg: dict[Any, Row] = {}
    for r in rows:
        g = agg.setdefault(r["sender"], {
            "account_id": r["sender"], "recipients": 0, "transfers": 0, "outflow": 0.0})
        g["recipients"] += 1
        g["transfers"] += r["pair_transfers"]
        g["outflow"] += r["pair_outflow"]
    kept = [{**g, "outflow": round(g["outflow"], 2)}
            for g in agg.values() if g["recipients"] >= 5]
    kept.sort(key=lambda r: r["recipients"], reverse=True)
    return kept


def velocity_ratio(rows: list[Row]) -> list[Row]:
    """Q11: derive the velocity ratio client-side, keep outflow > 0, sort by ratio."""
    kept = [{
        "account_id": r["account_id"],
        "balance": round(r["balance"], 2),
        "outflow_volume": round(r["outflow"], 2),
        "velocity_ratio": round(r["outflow"] / r["balance"], 1),
    } for r in rows if r["outflow"] > 0]
    kept.sort(key=lambda r: r["velocity_ratio"], reverse=True)
    return kept


def new_account_velocity(rows: list[Row]) -> list[Row]:
    """Q8: keep accounts with 10 or more transfers, sort by outflow."""
    kept = [{**r, "outflow": round(r["outflow"], 2)}
            for r in rows if r["transfers"] >= 10]
    kept.sort(key=lambda r: r["outflow"], reverse=True)
    return kept


QUERIES: list[Query] = [
    Query(
        number=1,
        title="Fan-in (mule collection accounts)",
        since_window_days=7,
        since_source="transfer",
        post_process=fanin_distinct_senders,
        top=50,
        note=(
            "Distinct senders per recipient via pair grouping (count(DISTINCT) does "
            "not push down). 7-day window via $since; senders>=5 and the sort are "
            "client-side. About 3.7s."
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
        number=2,
        title="Fan-out (distribution / smurfing)",
        since_window_days=7,
        since_source="transfer",
        post_process=fanout_distinct_recipients,
        top=50,
        note=(
            "Distinct recipients per sender via pair grouping. 7-day window via "
            "$since (all-time pair grouping returns ~223k rows in ~25s); recipients>=5 "
            "and the sort are client-side. About 3.5s."
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
        number=3,
        title="Pass-through mule (local betweenness proxy)",
        fast=False,
        top=50,
        note=(
            "48h forward window dropped (temporal arithmetic in WHERE unsupported); "
            "forward-after-receive ordering and the same-value (5%) test are kept. "
            "Expensive two-hop join."
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
        note="Runs verbatim (single MATCH, scalar grouping in RETURN). About 3 to 5s.",
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
        fast=False,
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
        fast=False,
        client_filter=lambda r: r["account_count"] >= 4 and r["txns"] <= 200,
        top=50,
        note=(
            "No clean pushdown rewrite: the per-day signal needs date(t.txn_timestamp) "
            "as a grouping key, and a function-derived GROUP BY key does not push down "
            "(materializes). Grouping by the raw timestamp pushes down but explodes to "
            "~one row per transaction. Left node-grouped; slow, may time out."
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
        number=7,
        title="Structuring (just-under-threshold transfers)",
        client_filter=lambda r: r["near_threshold"] >= 3,
        top=50,
        note=(
            "Scalar grouping by src.account_id (node grouping materializes). "
            "near_threshold>=3 client-side. About 1s."
        ),
        cypher="""
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src.account_id AS account_id, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
RETURN account_id, near_threshold, total
ORDER BY near_threshold DESC
""",
    ),
    Query(
        number=8,
        title="New account, high velocity",
        since_window_days=30,
        since_source="opened",
        since_kind="date",
        post_process=new_account_velocity,
        top=50,
        note=(
            "Scalar grouping by a.account_id, carrying opened_date and holder_age as "
            "grouping keys (node grouping took ~985s). 30-day opened window via $since; "
            "transfers>=10 and the sort are client-side. About 1s."
        ),
        cypher="""
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= $since
WITH a.account_id AS account_id, a.opened_date AS opened_date,
     a.holder_age AS holder_age, count(t) AS transfers, sum(t.amount) AS outflow
RETURN account_id, opened_date, holder_age, transfers, outflow
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
            "incoming_conns>=100 client-side."
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
        fast=False,
        client_filter=lambda r: r["rapid_pairs"] >= 50,
        top=15,
        note=(
            "24h window dropped (temporal arithmetic in WHERE unsupported); average "
            "turnaround is computed in RETURN via epochMillis. Expensive unfiltered "
            "two-hop join; may be slow or time out."
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
        post_process=velocity_ratio,
        top=25,
        note=(
            "Scalar grouping by a.account_id, carrying balance as a grouping key (node "
            "grouping materializes). The velocity ratio, outflow>0, and the sort are "
            "client-side. About 3.4s over the full transfer table."
        ),
        cypher="""
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.balance > 0
WITH a.account_id AS account_id, a.balance AS balance, sum(t.amount) AS outflow
RETURN account_id, balance, outflow
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
            "merchant_count<20 client-side."
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

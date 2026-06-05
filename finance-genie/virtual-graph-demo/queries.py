"""Virtual-Graph-compatible versions of the Finance Genie fraud-signal queries.

These are the queries from ``docs/plain-cypher-examples.md``, adapted to the Cypher
subset the Aura Virtual Graph actually translates to SQL. The doc queries do not run
verbatim, so two faithful rewrites are applied:

1. **HAVING moved client-side.** The Virtual Graph rejects a ``WHERE`` placed after an
   aggregating ``WITH`` (a HAVING-style filter) with ``42NG0: Unsupported syntax``.
   The server query therefore aggregates and ``ORDER BY``s only; the threshold is
   applied in Python (``client_filter``) and the top-N is taken after filtering.

2. **Temporal windows via a parameter.** ``datetime()/date() - duration({...})`` and any
   temporal function inside a ``WHERE`` are unsupported. "Recent" windows instead
   compare against a precomputed ``$since`` parameter (a plain comparison, which works).
   The cutoff is anchored to the dataset's max timestamp (2024-03-30), not ``now()``.

Constructs verified to work: aggregation in ``WITH``/``RETURN``, ``count(DISTINCT)``,
``sum``/``round``/``avg``, ``collect(DISTINCT)``, ``size()``, numeric arithmetic and
``abs()``, plain timestamp comparison (``ts >= ts`` and ``ts >= $since``).

Constructs that do NOT work on this Virtual Graph (so they are dropped or relaxed):
HAVING, temporal arithmetic/functions inside ``WHERE`` (the 48h/24h pass-through
windows), and variable-length paths (Q5 cycles).
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
    note: str = ""  # how this differs from the doc version


# NOTE: The sample fraud-signal queries below are commented out while the demo is
# repurposed to test a GDS Session + PageRank (see ``gds_pagerank.py`` and
# ``../docs/gds-guide.md``). Uncomment to restore the plain-Cypher fraud queries.
QUERIES: list[Query] = []

_DISABLED_QUERIES: list[Query] = [
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
        note="Variable-length path {2,4} is unsupported on the Virtual Graph.",
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
        note="incoming_conns>=100 filtered client-side.",
        cypher="""
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
""",
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
        note="transfer_count>=100 and merchant_count<20 filtered client-side.",
        cypher="""
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
OPTIONAL MATCH (a)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a,
     count(DISTINCT tr) AS transfer_count,
     count(DISTINCT tw) AS merchant_count
RETURN a.account_id AS account_id, transfer_count, merchant_count
ORDER BY transfer_count DESC
""",
    ),
]

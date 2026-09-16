"""Account-level search services, backed by live Cypher against Aura.

`list_risky_accounts` powers Screen 1 mode "Risky accounts" (ordered by
PageRank as `risk_score`).
`list_central_accounts` powers Screen 1 mode "Central accounts" (ordered by
sampled betweenness as `betweenness_centrality`).

Shape parity with the previous SQL-backed version so the OpenAPI client
requires no regeneration.
"""

from __future__ import annotations

from datetime import date, datetime

from neo4j import Driver

from ..models import Band, HubAccountOut, RiskAccountOut


def _velocity_band(txn_count: int) -> Band:
    if txn_count >= 50:
        return "High"
    if txn_count >= 15:
        return "Medium"
    return "Low"


def _diversity_band(distinct_merchants: int) -> Band:
    if distinct_merchants >= 20:
        return "High"
    if distinct_merchants >= 8:
        return "Medium"
    return "Low"


def _account_age_days(opened_date: date | datetime | str | None) -> int:
    if opened_date is None:
        return 0
    if isinstance(opened_date, date) and not isinstance(opened_date, datetime):
        d = opened_date
    elif isinstance(opened_date, datetime):
        d = opened_date.date()
    else:
        try:
            d = datetime.strptime(str(opened_date), "%Y-%m-%d").date()
        except ValueError:
            return 0
    return max((date.today() - d).days, 0)


_RISKY_CYPHER = """
MATCH (a:Account) WHERE a.risk_score IS NOT NULL
WITH a ORDER BY a.risk_score DESC LIMIT $row_limit
OPTIONAL MATCH (a)-[t:TRANSACTED_WITH]->(m:Merchant)
WITH a, count(t) AS txn_count, count(DISTINCT m) AS distinct_merchants
RETURN a.account_id     AS account_id,
       a.risk_score     AS risk_score,
       txn_count,
       distinct_merchants,
       a.opened_date    AS opened_date
ORDER BY a.risk_score DESC
"""


def list_risky_accounts(
    driver: Driver, limit: int = 25
) -> list[RiskAccountOut]:
    with driver.session() as session:
        rows = session.run(_RISKY_CYPHER, row_limit=int(limit)).data()

    if not rows:
        return []

    max_score = max((float(r.get("risk_score") or 0) for r in rows), default=0.0)
    normalize = max_score > 1.0

    out: list[RiskAccountOut] = []
    for r in rows:
        raw_score = float(r.get("risk_score") or 0)
        score = raw_score / max_score if normalize else raw_score
        txn_count = int(r.get("txn_count") or 0)
        diversity = int(r.get("distinct_merchants") or 0)
        out.append(
            RiskAccountOut(
                account_id=str(r.get("account_id")),
                risk_score=score,
                velocity=_velocity_band(txn_count),
                merchant_diversity=_diversity_band(diversity),
                account_age_days=_account_age_days(r.get("opened_date")),
            )
        )
    return out


_HUBS_CYPHER = """
MATCH (a:Account) WHERE a.betweenness_centrality IS NOT NULL
WITH a ORDER BY a.betweenness_centrality DESC LIMIT $row_limit
OPTIONAL MATCH (b:Account)-[r:TRANSFERRED_TO]->(a)
WITH a, count(DISTINCT b) AS neighbors, count(r) AS inbound_transfer_events
RETURN a.account_id              AS account_id,
       a.betweenness_centrality  AS betweenness,
       neighbors,
       inbound_transfer_events
ORDER BY a.betweenness_centrality DESC
"""


def list_central_accounts(
    driver: Driver, limit: int = 25
) -> list[HubAccountOut]:
    """Return high-betweenness accounts.

    `shortest_paths` is derived from `inbound_transfer_events` so the value is
    deterministic without running an All Pairs Shortest Path computation at
    request time. Matches the previous SQL service's contract.
    """
    with driver.session() as session:
        rows = session.run(_HUBS_CYPHER, row_limit=int(limit)).data()

    if not rows:
        return []

    max_betweenness = max(
        (float(r.get("betweenness") or 0) for r in rows), default=0.0
    )
    normalize = max_betweenness > 1.0

    out: list[HubAccountOut] = []
    for r in rows:
        raw_b = float(r.get("betweenness") or 0)
        betweenness = raw_b / max_betweenness if normalize else raw_b
        inbound = int(r.get("inbound_transfer_events") or 0)
        out.append(
            HubAccountOut(
                account_id=str(r.get("account_id")),
                betweenness=betweenness,
                # approximates APSP count without running it; 999 caps UI display
                shortest_paths=min(inbound * 5, 999),
                neighbors=int(r.get("neighbors") or 0),
            )
        )
    return out

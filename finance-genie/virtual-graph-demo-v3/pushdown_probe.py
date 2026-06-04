"""Isolate what blocks Virtual Graph pushdown on the fan-in aggregation shape.

Runs EXPLAIN on a ladder of variants and reports, per variant, whether it errored
(``42NG0``), translated with the ``VirtualGraphPostProcessing`` materialization
notification, or translated clean (full pushdown). EXPLAIN only, so nothing executes
on the warehouse.

    uv run python -u pushdown_probe.py
"""

from __future__ import annotations

import datetime as dt

from neo4j import GraphDatabase

import main

BASE = "MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account) WHERE t.transfer_timestamp >= $since "

VARIANTS: dict[str, str] = {
    "E group by node, count(DISTINCT) + ORDER + LIMIT": (
        BASE + "WITH dst, count(DISTINCT src) AS senders, sum(t.amount) AS inflow "
        "RETURN dst.account_id AS account_id, senders, inflow ORDER BY senders DESC LIMIT 50"
    ),
    "H group by node, rel/sum only (no node count)": (
        BASE + "WITH dst, count(t) AS transfers, sum(t.amount) AS inflow "
        "RETURN dst.account_id AS account_id, transfers, inflow ORDER BY inflow DESC LIMIT 50"
    ),
    "I group by property, rel/sum only": (
        BASE + "WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow "
        "RETURN account_id, transfers, inflow ORDER BY inflow DESC LIMIT 50"
    ),
    "J group by property, count(DISTINCT src.id)": (
        BASE + "WITH dst.account_id AS account_id, count(DISTINCT src.account_id) AS senders, "
        "sum(t.amount) AS inflow "
        "RETURN account_id, senders, inflow ORDER BY senders DESC LIMIT 50"
    ),
    "K group by property, count(DISTINCT src node)": (
        BASE + "WITH dst.account_id AS account_id, count(DISTINCT src) AS senders, "
        "sum(t.amount) AS inflow "
        "RETURN account_id, senders, inflow ORDER BY senders DESC LIMIT 50"
    ),
    "L group by property, full (distinct+round+order+limit)": (
        BASE + "WITH dst.account_id AS account_id, count(DISTINCT src) AS senders, "
        "count(t) AS transfers, sum(t.amount) AS inflow "
        "RETURN account_id, senders, transfers, round(inflow, 2) AS inflow "
        "ORDER BY senders DESC, inflow DESC LIMIT 50"
    ),
    "M group by property, no ORDER/LIMIT": (
        BASE + "WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow "
        "RETURN account_id, transfers, inflow"
    ),
    "N group by property, ORDER BY only (no LIMIT)": (
        BASE + "WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow "
        "RETURN account_id, transfers, inflow ORDER BY inflow DESC"
    ),
    "O group by property, LIMIT only (no ORDER BY)": (
        BASE + "WITH dst.account_id AS account_id, count(t) AS transfers, sum(t.amount) AS inflow "
        "RETURN account_id, transfers, inflow LIMIT 50"
    ),
    "P group by property, count(DISTINCT), no ORDER/LIMIT": (
        BASE + "WITH dst.account_id AS account_id, count(DISTINCT src) AS senders, "
        "sum(t.amount) AS inflow RETURN account_id, senders, inflow"
    ),
}


def classify(session, cypher: str, since: dt.datetime) -> str:
    try:
        notes = session.run("EXPLAIN " + cypher, since=since).consume().notifications or []
    except Exception as exc:  # noqa: BLE001 - report any translation failure
        code = getattr(exc, "code", type(exc).__name__)
        return f"ERROR {code}"
    materializes = any(
        "PostProcessing" in (n.get("code") or "") for n in notes
    )
    return "materializes" if materializes else "PUSHDOWN OK"


def main_probe() -> None:
    uri, auth = main.load_connection()
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        max_transfer, _ = main.data_max_dates(driver)
        since = max_transfer.to_native() - dt.timedelta(days=7)
        with driver.session() as session:
            for label, cypher in VARIANTS.items():
                verdict = classify(session, cypher, since)
                print(f"{verdict:16} | {label}")


if __name__ == "__main__":
    main_probe()

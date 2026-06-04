"""Verify the anchored fraud-visualization queries against the Virtual Graph.

For each laundering shape (collection account, spray account, round-trip pair) this
finds a real flagged account, then runs the matching anchored ego-network query and
reports how many rows come back, confirming each visualization renders small and fast.

Loads ``../.env.azure`` by default; set ``PROBE_ENV`` to point at another dotenv.

    uv run viz_check.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env.azure"
CUTOFF = "2024-03-23T23:58:00Z"  # dataset max transfer_timestamp minus 7 days


def timed(driver, label: str, cypher: str, **params: object) -> list:
    """Run one query, print its wall-clock time and row count, return the records."""
    t0 = time.perf_counter()
    recs, _, _ = driver.execute_query(cypher, **params)
    print(f"  {label}: {time.perf_counter() - t0:.1f}s, {len(recs)} rows")
    return recs


def main() -> None:
    env_file = Path(os.environ.get("PROBE_ENV", DEFAULT_ENV)).expanduser()
    load_dotenv(env_file, override=True)
    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])

    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        print(f"connected: {uri}")

        # Anchor 1: recipient with the most distinct senders in the 7-day window.
        recs = timed(
            driver,
            "find collection account",
            'MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account) '
            f'WHERE t.transfer_timestamp >= datetime("{CUTOFF}") '
            "WITH dst.account_id AS recipient, src.account_id AS sender, count(t) AS legs "
            "WITH recipient, count(*) AS senders "
            "RETURN recipient, senders ORDER BY senders DESC LIMIT 5",
        )
        coll_id = recs[0]["recipient"]
        print(f"    -> account {coll_id} with {recs[0]['senders']} distinct senders")

        # Anchor 2: sender with the most distinct recipients in the 7-day window.
        recs = timed(
            driver,
            "find spray account",
            'MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account) '
            f'WHERE t.transfer_timestamp >= datetime("{CUTOFF}") '
            "WITH src.account_id AS sender, dst.account_id AS recipient, count(t) AS legs "
            "WITH sender, count(*) AS recipients "
            "RETURN sender, recipients ORDER BY recipients DESC LIMIT 5",
        )
        spray_id = recs[0]["sender"]
        print(f"    -> account {spray_id} with {recs[0]['recipients']} distinct recipients")

        # Anchor 3: highest-volume reciprocal round-trip pair.
        recs = timed(
            driver,
            "find round-trip pair",
            "MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a) "
            "WHERE a.account_id < b.account_id "
            "RETURN a.account_id AS a_id, b.account_id AS b_id, "
            "round(sum(f.amount + g.amount), 2) AS vol, count(*) AS legs "
            "ORDER BY vol DESC LIMIT 5",
        )
        a_id, b_id = recs[0]["a_id"], recs[0]["b_id"]
        print(f"    -> pair {a_id} <-> {b_id}, round-trip volume {recs[0]['vol']}")

        print("--- visualizations ---")

        timed(
            driver,
            f"VIZ fan-in star @ {coll_id}",
            "MATCH (sender:Account)-[t:TRANSFERRED_TO]->(a:Account {account_id: $id}) "
            "RETURN sender, t, a LIMIT 50",
            id=coll_id,
        )
        timed(
            driver,
            f"VIZ fan-out star @ {spray_id}",
            "MATCH (a:Account {account_id: $id})-[t:TRANSFERRED_TO]->(recipient:Account) "
            "RETURN a, t, recipient LIMIT 50",
            id=spray_id,
        )
        timed(
            driver,
            f"VIZ round-trip @ {a_id} <-> {b_id}",
            "MATCH (a:Account {account_id: $a})-[t:TRANSFERRED_TO]-(b:Account {account_id: $b}) "
            "RETURN a, t, b",
            a=a_id,
            b=b_id,
        )


if __name__ == "__main__":
    main()

"""Basic demo (``--demo basic``).

The warm-up exploration / visualization queries from ``basic-graph-examples.md``:
simple counts and small, anchored traversals that show the value of the relationships
without any fraud logic.
"""

from __future__ import annotations

import time

from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError

from helpers import _driver_error, print_table, run_cypher
from queries import BASIC_QUERIES, BasicQuery


def pick_anchors(driver: Driver) -> tuple[object, object]:
    """Pick a well-connected anchor account and a merchant for the basic graph queries.

    The anchored traversals need a node to start from. Any account with at least one
    transfer makes a usable ego network; the chosen ids are printed so the same
    query can be pasted into the Aura Workspace.
    """
    rec, _, _ = driver.execute_query(
        "MATCH (a:Account)-[:TRANSFERRED_TO]->(:Account) "
        "RETURN a.account_id AS id LIMIT 1"
    )
    account_id = rec[0]["id"]
    rec, _, _ = driver.execute_query("MATCH (m:Merchant) RETURN m.merchant_id AS id LIMIT 1")
    merchant_id = rec[0]["id"]
    return account_id, merchant_id


def run_basic_query(driver: Driver, query: BasicQuery, max_rows: int, timeout: float,
                    params: dict[str, object]) -> None:
    """Execute one basic exploration query and print rows (table) or a count (graph)."""
    print(f"\n{'=' * 78}")
    print(f"[B{query.number}] {query.title}  ({query.kind})")
    if query.note:
        print(f"  note: {query.note}")
    print("=" * 78)

    t0 = time.perf_counter()
    try:
        rows = run_cypher(driver, query.cypher, params, timeout)
    except Neo4jError as exc:
        print(f"  ERROR after {time.perf_counter() - t0:.1f}s: {exc.code}\n  {exc.message}")
        return
    except DriverError as exc:
        print(f"  ERROR after {time.perf_counter() - t0:.1f}s: {_driver_error(exc)}")
        return
    elapsed = time.perf_counter() - t0

    if query.kind == "graph":
        print(f"  OK {elapsed:.1f}s; {len(rows)} path/row(s) returned.")
        print("  Run this in the Aura Workspace Query tab to see the visualization.")
    else:
        print(f"  OK {elapsed:.1f}s; {len(rows)} row(s).")
        print_table(rows[:max_rows], max_rows, total_matched=len(rows))


def run_basic(driver: Driver, max_rows: int, timeout: float) -> None:
    """Run all basic exploration / visualization queries."""
    account_id, merchant_id = pick_anchors(driver)
    params = {"account_id": account_id, "merchant_id": merchant_id}
    print(f"Anchors: account_id={account_id}, merchant_id={merchant_id} "
          f"(used by the graph queries).")
    print(f"Running {len(BASIC_QUERIES)} basic quer"
          f"{'y' if len(BASIC_QUERIES) == 1 else 'ies'} (timeout {timeout:g}s each).")
    for query in BASIC_QUERIES:
        run_basic_query(driver, query, max_rows, timeout, params)

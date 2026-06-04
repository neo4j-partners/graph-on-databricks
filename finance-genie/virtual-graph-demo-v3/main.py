"""Run the Finance Genie fraud-signal queries against the Neo4j Virtual Graph.

Connection details come from the parent ``finance-genie/.env.azure`` (NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD), which points at the Aura Virtual Graph engine. Each
query is translated to SQL and run on the backing Databricks warehouse.

The queries live in ``queries.py`` and are adapted to what the Virtual Graph actually
supports: the server aggregates and orders, "recent" windows are passed as a
precomputed ``$since`` parameter, threshold (HAVING) filters are applied here in
Python, and an ``OPTIONAL MATCH`` is replaced by a second aggregation merged
client-side. See the module docstring in ``queries.py`` for the full rationale.

Usage:
    uv run main.py                 # run every Virtual-Graph-supported fraud query
    uv run main.py --basic         # run the basic exploration / visualization queries
    uv run main.py --all           # also attempt the unsupported cycles query (Q5)
    uv run main.py --query 9       # run a single query by number
    uv run main.py --only 4 7      # run a subset, in this order (two at a time)
    uv run main.py --rows 5        # cap printed rows per query
    uv run main.py --timeout 60    # per-query server timeout in seconds (default 120)
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError
from neo4j.time import Date, DateTime

from queries import BASIC_QUERIES, QUERIES, BasicQuery, Query, Row

PARENT_ENV = Path(__file__).resolve().parent.parent / ".env.azure"


def load_connection() -> tuple[str, tuple[str, str]]:
    """Read Neo4j credentials from the parent .env and return (uri, auth)."""
    if not PARENT_ENV.is_file():
        sys.exit(f"Could not find parent env file at {PARENT_ENV}")
    load_dotenv(PARENT_ENV, override=True)

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    missing = [
        name
        for name, value in (
            ("NEO4J_URI", uri),
            ("NEO4J_USERNAME", username),
            ("NEO4J_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Missing required variables in {PARENT_ENV}: {', '.join(missing)}")
    return uri, (username, password)


def data_max_dates(driver: Driver) -> tuple[DateTime, Date]:
    """Return the dataset's max transfer timestamp and max account opened_date.

    These anchor the "recent" windows so they land inside the synthetic dataset
    (which ends 2024-03-30) instead of around an empty present day.
    """
    rec, _, _ = driver.execute_query(
        "MATCH ()-[t:TRANSFERRED_TO]->() RETURN max(t.transfer_timestamp) AS mx"
    )
    max_transfer = rec[0]["mx"]
    rec, _, _ = driver.execute_query(
        "MATCH (a:Account) RETURN max(a.opened_date) AS mx"
    )
    max_opened = rec[0]["mx"]
    return max_transfer, max_opened


def since_param(query: Query, max_transfer: DateTime, max_opened: Date) -> dt.datetime | dt.date:
    """Compute the ``$since`` cutoff for a windowed query."""
    window = dt.timedelta(days=query.since_window_days)
    if query.since_source == "opened":
        anchor = max_opened.to_native()  # datetime.date
        return anchor - window
    anchor = max_transfer.to_native()  # datetime.datetime
    cutoff = anchor - window
    return cutoff.date() if query.since_kind == "date" else cutoff


def run_cypher(driver: Driver, cypher: str, params: dict[str, object],
               timeout: float) -> list[Row]:
    """Run one statement in an explicit transaction (no managed-transaction retry)."""
    with driver.session() as session:
        tx = session.begin_transaction(timeout=timeout)
        try:
            result = tx.run(cypher, **params)
            return [record.data() for record in result]
        finally:
            tx.close()


def merge_enrichment(rows: list[Row], enrich_rows: list[Row], key: str,
                     columns: dict[str, object]) -> None:
    """Copy ``columns`` from the enrich rows onto ``rows`` by ``key``, in place.

    Replaces an ``OPTIONAL MATCH``: an account absent from the enrich result gets the
    given default for each column, so rows with no optional match are preserved.
    """
    lookup = {row[key]: row for row in enrich_rows}
    for row in rows:
        match = lookup.get(row[key])
        for col, default in columns.items():
            row[col] = match[col] if match is not None else default


def run_query(driver: Driver, query: Query, max_rows: int, timeout: float,
              max_transfer: DateTime, max_opened: Date) -> None:
    """Execute one query, merge any enrichment, apply the threshold, and print."""
    marker = "OK" if query.vg_supported else "unsupported"
    print(f"\n{'=' * 78}")
    print(f"[{query.number}] {query.title}  (Virtual Graph: {marker})")
    if query.note:
        print(f"  note: {query.note}")
    print("=" * 78)

    params: dict[str, object] = {}
    if query.since_window_days is not None:
        params["since"] = since_param(query, max_transfer, max_opened)
        print(f"  $since = {params['since']}")

    t0 = time.perf_counter()
    try:
        rows = run_cypher(driver, query.cypher, params, timeout)
        if query.enrich_cypher is not None:
            enrich_rows = run_cypher(driver, query.enrich_cypher, {}, timeout)
            merge_enrichment(rows, enrich_rows, query.enrich_key, query.enrich_columns)
    except Neo4jError as exc:
        note = " (expected — unsupported on the Virtual Graph)" if not query.vg_supported else ""
        print(f"  ERROR{note} after {time.perf_counter() - t0:.1f}s: {exc.code}\n  {exc.message}")
        return
    elapsed = time.perf_counter() - t0

    matched = [r for r in rows if query.client_filter is None or query.client_filter(r)]
    print(f"  OK {elapsed:.1f}s; {len(rows)} aggregated row(s); "
          f"{len(matched)} pass the threshold")
    print_table(matched[: max_rows], max_rows, total_matched=len(matched))


def print_table(rows: list[Row], max_rows: int, total_matched: int) -> None:
    """Print result rows as a simple aligned table."""
    if not rows:
        print("  (no rows pass the threshold)")
        return

    columns = list(rows[0].keys())
    widths = {
        col: max(len(col), *(len(_fmt(row.get(col))) for row in rows))
        for col in columns
    }
    print("  " + "  ".join(col.ljust(widths[col]) for col in columns))
    print("  " + "  ".join("-" * widths[col] for col in columns))
    for row in rows:
        print("  " + "  ".join(_fmt(row.get(col)).ljust(widths[col]) for col in columns))
    if total_matched > max_rows:
        print(f"  ... {total_matched - max_rows} more matching row(s)")


def _fmt(value: object) -> str:
    """Compact display of a cell value (truncate long account lists)."""
    if isinstance(value, list):
        text = ", ".join(str(v) for v in value)
        return text if len(text) <= 60 else text[:57] + "..."
    return str(value)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basic", action="store_true",
                        help="run the basic exploration / visualization queries instead")
    parser.add_argument("--all", action="store_true",
                        help="also attempt the unsupported cycles query (Q5)")
    parser.add_argument("--query", type=int, metavar="N",
                        help="run only the query with this number")
    parser.add_argument("--only", type=int, nargs="+", metavar="N",
                        help="run only these query numbers, in this order")
    parser.add_argument("--rows", type=int, default=10, metavar="N",
                        help="maximum rows to print per query (default: 10)")
    parser.add_argument("--timeout", type=float, default=120.0, metavar="SECONDS",
                        help="per-query server-side timeout (default: 120)")
    return parser.parse_args()


def select_queries(args: argparse.Namespace) -> list[Query]:
    """Resolve which queries to run from the CLI flags."""
    by_number = {q.number: q for q in QUERIES}
    if args.only:
        missing = [n for n in args.only if n not in by_number]
        if missing:
            sys.exit(f"No quer{'y' if len(missing) == 1 else 'ies'} numbered "
                     f"{', '.join(map(str, missing))}")
        return [by_number[n] for n in args.only]
    if args.query is not None:
        if args.query not in by_number:
            sys.exit(f"No query numbered {args.query} (valid: 1-{len(QUERIES)})")
        return [by_number[args.query]]
    if args.all:
        return list(QUERIES)
    return [q for q in QUERIES if q.vg_supported]


def main() -> None:
    args = parse_args()
    uri, auth = load_connection()
    selected = select_queries(args)

    print(f"Connecting to {uri} ...")
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        if args.basic:
            print("Connected. Running basic exploration / visualization queries.")
            run_basic(driver, args.rows, args.timeout)
            print(f"\n{'=' * 78}\nDone.")
            return
        max_transfer, max_opened = data_max_dates(driver)
        print(f"Connected. Data max transfer={max_transfer}, max opened={max_opened}.")
        print(f"Running {len(selected)} quer{'y' if len(selected) == 1 else 'ies'} "
              f"(timeout {args.timeout:g}s each).")
        for query in selected:
            run_query(driver, query, args.rows, args.timeout, max_transfer, max_opened)
    print(f"\n{'=' * 78}\nDone.")


if __name__ == "__main__":
    main()

"""Shared connection helpers for the Finance Genie Virtual Graph demo.

The sample fraud-signal query runner is **commented out**: the demo is currently
repurposed to test a GDS Session + PageRank against the Virtual Graph. Run that with:

    uv run gds_pagerank.py

See ``gds_pagerank.py`` and ``../docs/gds-guide.md``. To restore the plain-Cypher
fraud queries, uncomment the runner block below and the ``QUERIES`` list in
``queries.py``.

Connection details come from the parent ``finance-genie/.env`` (NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD), which points at the Aura Virtual Graph engine. The
helpers ``load_connection``, ``data_max_dates``, and ``since_param`` remain importable
and are reused by ``gds_pagerank.py`` and ``heavy_run.py``.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver
from neo4j.time import Date, DateTime

from queries import Query

PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"


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


# ---------------------------------------------------------------------------
# Sample fraud-query runner — COMMENTED OUT while the demo tests GDS Sessions.
# Uncomment this block (and restore ``QUERIES`` in queries.py) to run the
# plain-Cypher fraud queries again. ``argparse``, ``Neo4jError``, ``Row``,
# ``QUERIES``, and ``GraphDatabase`` imports are needed when re-enabling it.
# ---------------------------------------------------------------------------
#
# def run_query(driver: Driver, query: Query, max_rows: int, timeout: float,
#               max_transfer: DateTime, max_opened: Date) -> None:
#     """Execute one query, apply the client-side threshold, and print results."""
#     marker = "OK" if query.vg_supported else "unsupported"
#     print(f"\n{'=' * 78}")
#     print(f"[{query.number}] {query.title}  (Virtual Graph: {marker})")
#     if query.note:
#         print(f"  note: {query.note}")
#     print("=" * 78)
#
#     params: dict[str, object] = {}
#     if query.since_window_days is not None:
#         params["since"] = since_param(query, max_transfer, max_opened)
#         print(f"  $since = {params['since']}")
#
#     try:
#         with driver.session() as session:
#             tx = session.begin_transaction(timeout=timeout)
#             try:
#                 result = tx.run(query.cypher, **params)
#                 rows: list[Row] = [record.data() for record in result]
#             finally:
#                 tx.close()
#     except Neo4jError as exc:
#         note = " (expected — unsupported on the Virtual Graph)" if not query.vg_supported else ""
#         print(f"  ERROR{note}: {exc.code}\n  {exc.message}")
#         return
#
#     matched = [r for r in rows if query.client_filter is None or query.client_filter(r)]
#     print(f"  {len(rows)} aggregated row(s); {len(matched)} pass the threshold")
#     print_table(matched[: max_rows], max_rows, total_matched=len(matched))
#
#
# def print_table(rows: list[Row], max_rows: int, total_matched: int) -> None:
#     """Print result rows as a simple aligned table."""
#     if not rows:
#         print("  (no rows pass the threshold)")
#         return
#
#     columns = list(rows[0].keys())
#     widths = {
#         col: max(len(col), *(len(_fmt(row.get(col))) for row in rows))
#         for col in columns
#     }
#     print("  " + "  ".join(col.ljust(widths[col]) for col in columns))
#     print("  " + "  ".join("-" * widths[col] for col in columns))
#     for row in rows:
#         print("  " + "  ".join(_fmt(row.get(col)).ljust(widths[col]) for col in columns))
#     if total_matched > max_rows:
#         print(f"  ... {total_matched - max_rows} more matching row(s)")
#
#
# def _fmt(value: object) -> str:
#     """Compact display of a cell value (truncate long account lists)."""
#     if isinstance(value, list):
#         text = ", ".join(str(v) for v in value)
#         return text if len(text) <= 60 else text[:57] + "..."
#     return str(value)
#
#
# def parse_args() -> argparse.Namespace:
#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument("--all", action="store_true",
#                         help="also attempt the unsupported cycles query (Q5)")
#     parser.add_argument("--query", type=int, metavar="N",
#                         help="run only the query with this number")
#     parser.add_argument("--rows", type=int, default=10, metavar="N",
#                         help="maximum rows to print per query (default: 10)")
#     parser.add_argument("--timeout", type=float, default=120.0, metavar="SECONDS",
#                         help="per-query server-side timeout (default: 120)")
#     return parser.parse_args()
#
#
# def main() -> None:
#     args = parse_args()
#     uri, auth = load_connection()
#
#     if args.query is not None:
#         selected = [q for q in QUERIES if q.number == args.query]
#         if not selected:
#             sys.exit(f"No query numbered {args.query} (valid: 1-{len(QUERIES)})")
#     elif args.all:
#         selected = list(QUERIES)
#     else:
#         selected = [q for q in QUERIES if q.vg_supported]
#
#     print(f"Connecting to {uri} ...")
#     with GraphDatabase.driver(uri, auth=auth) as driver:
#         driver.verify_connectivity()
#         max_transfer, max_opened = data_max_dates(driver)
#         print(f"Connected. Data max transfer={max_transfer}, max opened={max_opened}.")
#         print(f"Running {len(selected)} quer{'y' if len(selected) == 1 else 'ies'} "
#               f"(timeout {args.timeout:g}s each).")
#         for query in selected:
#             run_query(driver, query, args.rows, args.timeout, max_transfer, max_opened)
#     print(f"\n{'=' * 78}\nDone.")


def main() -> None:
    """The sample fraud-query runner is disabled; point users at the GDS test."""
    print(
        "The sample fraud-query runner is commented out.\n"
        "This demo now tests a GDS Session + PageRank on the Virtual Graph.\n\n"
        "    uv run gds_pagerank.py\n\n"
        "See gds_pagerank.py and ../docs/gds-guide.md. To restore the fraud queries,\n"
        "uncomment the runner block in main.py and the QUERIES list in queries.py."
    )


if __name__ == "__main__":
    main()

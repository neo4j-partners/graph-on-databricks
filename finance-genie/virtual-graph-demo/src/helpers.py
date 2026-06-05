"""Shared query helpers for the Finance Genie Virtual Graph demos.

Connection-agnostic utilities used across the demos and the support scripts: the
``$since`` window math, the explicit-transaction query runner, the table printer, and
the error formatters.
"""

from __future__ import annotations

import datetime as dt

from neo4j import Driver
from neo4j.exceptions import DriverError
from neo4j.time import Date, DateTime

from queries import Query, Row


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


def _driver_error(exc: DriverError) -> str:
    """One-line description of a client-side driver failure (timeout, lost connection).

    These are not server ``Neo4jError`` codes; the useful detail is the exception type
    and its underlying cause (often ``TimeoutError`` from the 60s Bolt read timeout the
    fraud and basic paths do not override). The query usually keeps running server-side,
    so the run continues with the next query rather than aborting.
    """
    cause = exc.__cause__
    suffix = f" (cause: {type(cause).__name__})" if cause is not None else ""
    return (f"{type(exc).__name__}: {exc}{suffix}; likely the 60s Bolt read timeout or "
            "the warehouse is too small")

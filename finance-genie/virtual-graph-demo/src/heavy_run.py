"""Run the heavier fraud queries sequentially on the current (Small) warehouse.

Each query gets up to ``CAP`` seconds. If it does not finish, it is abandoned (it
keeps running server-side and holds a connection-pool slot), so after every query we
health-check the pool with ``RETURN 1`` and stop the batch if the pool degrades or
after two timeouts. One query at a time, never run concurrently.

    uv run vg-heavy                      # logs progress to stdout
"""

from __future__ import annotations

import argparse
import threading
import time

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from connection import load_connection
from helpers import data_max_dates, since_param
from queries import QUERIES, Query

CAP = 600.0  # 10 minutes per query
HEALTH_CAP = 60.0
# The heavy queries are the slow tier (unbounded two-hop joins, collect(DISTINCT) over a
# node group). Derived from queries.py so it stays correct as the query set changes.
ORDER = [q.number for q in QUERIES if q.tier == "slow" and q.vg_supported]
NOTES = {
    8: "unbounded two-hop pass-through join; checking how slow it runs",
    9: "date(t.txn_timestamp) grouping with collect(DISTINCT ...) ; checking it runs",
    10: "unbounded two-hop rapid-turnover join with epochMillis turnaround",
}


def by_number(number: int) -> Query:
    return next(q for q in QUERIES if q.number == number)


def run_capped(driver, query: Query, params: dict[str, object]) -> str:
    """Run one query in a worker thread, capped at CAP seconds (no server cancel).

    Uses an explicit auto-commit ``session.run`` (no managed-transaction retry), so a
    socket read timeout does not silently re-run the expensive query.
    """
    box: dict[str, object] = {}

    def work() -> None:
        t0 = time.perf_counter()
        try:
            with driver.session() as session:
                result = session.run(query.cypher, **params)
                rows = [r.data() for r in result]
            matched = [r for r in rows
                       if query.client_filter is None or query.client_filter(r)]
            box["res"] = (time.perf_counter() - t0, len(rows), len(matched))
        except Exception as exc:  # noqa: BLE001 - record any failure with its timing
            code = getattr(exc, "code", type(exc).__name__)
            msg = getattr(exc, "message", str(exc))
            box["err"] = (time.perf_counter() - t0, code, msg)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(CAP)
    if th.is_alive():
        return f"TIMEOUT after {CAP:.0f}s (abandoned, still running server-side)"
    if "err" in box:
        dt_s, code, msg = box["err"]
        return f"ERROR after {dt_s:.1f}s: {code} | {msg[:120]}"
    if "res" in box:
        dt_s, n, m = box["res"]
        return f"OK {dt_s:.1f}s; {n} aggregated row(s), {m} pass the threshold"
    return "UNKNOWN (worker produced no result)"


def health(driver) -> tuple[bool, str]:
    """Return (ok, detail) from a RETURN 1 probe, capped at HEALTH_CAP seconds."""
    box: dict[str, object] = {}

    def work() -> None:
        t0 = time.perf_counter()
        try:
            driver.execute_query("RETURN 1 AS ok")
            box["ok"] = time.perf_counter() - t0
        except Neo4jError as exc:
            box["err"] = f"{exc.code} | {exc.message[:80]}"

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(HEALTH_CAP)
    if th.is_alive():
        return False, f"RETURN 1 did not return within {HEALTH_CAP:.0f}s"
    if "err" in box:
        return False, str(box["err"])
    return True, f"RETURN 1 {box['ok']:.1f}s"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", type=int, nargs="+", metavar="N",
                        help="run only these query numbers, in this order")
    args = parser.parse_args()
    order = args.only if args.only else ORDER

    uri, auth = load_connection()
    print(f"Heavy batch on {uri}", flush=True)
    print(f"Order: {order} ; cap {CAP:.0f}s each\n", flush=True)

    timeouts = 0
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        max_transfer, max_opened = data_max_dates(driver)

        ok, detail = health(driver)
        print(f"pre-batch health: {detail}", flush=True)
        if not ok:
            print("Pool already unhealthy, aborting.", flush=True)
            return

        for number in order:
            query = by_number(number)
            params: dict[str, object] = {}
            if query.since_window_days is not None:
                params["since"] = since_param(query, max_transfer, max_opened)
            extra = f" [{NOTES[number]}]" if number in NOTES else ""
            since_txt = f" $since={params['since']}" if params else ""
            print(f"=== Q{number} {query.title}{extra}{since_txt}", flush=True)

            result = run_capped(driver, query, params)
            print(f"    {result}", flush=True)
            if result.startswith("TIMEOUT"):
                timeouts += 1

            ok, detail = health(driver)
            print(f"    post-health: {detail}\n", flush=True)
            if not ok:
                print("POOL DEGRADED, stopping batch to avoid full saturation.",
                      flush=True)
                break
            if timeouts >= 2:
                print("Two timeouts reached, stopping batch to protect the pool.",
                      flush=True)
                break

    print("=== BATCH DONE", flush=True)


if __name__ == "__main__":
    main()

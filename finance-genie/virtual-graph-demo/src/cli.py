"""Run the Finance Genie Virtual Graph demos.

A single entry point with four demos, selected with ``--demo``:

* ``--demo fraud`` (default) — the fast, pushdown-friendly fraud-signal queries from
  ``finding-fraud.md``. The server aggregates and orders; threshold (HAVING)
  filters run here in Python; "recent" windows are passed as a precomputed ``$since``
  parameter; fan-in/fan-out reshape a ``count(DISTINCT)`` into pair-grouping plus a
  client-side rollup. ``--all`` also attempts the slow / unsupported signals that have
  no fast form (kept to demonstrate what does not work). See ``queries.py``.
* ``--demo basic`` — the warm-up exploration / visualization queries from
  ``basic-graph-examples.md``: simple counts and small, anchored traversals that
  show the value of the relationships without any fraud logic.
* ``--demo fast-gds`` — the working GDS Session + PageRank path over a small, recent
  window of the Account transfer network, provisioned via the Cypher-projection form
  of ``gds.graph.project(...)``. See ``gds-guide.md``.
* ``--demo slow-gds`` — the GDS forms that do not work, kept to demonstrate the
  failures: the classic ``CALL gds.graph.project('g', 'Account', ...)`` form (rejected
  with ``42NG0``) and a large-window projection (trips the 60s Bolt read timeout).
* ``--demo gds-probe`` — sweep projections that add node / relationship properties one
  at a time on a thin window, to isolate which property configs the projection rejects
  (the edge-case bug in ``gds-limitations.md``). See ``src/demos/gds_probe.py``.

Connection details come from the parent ``finance-genie/.env`` (NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD), which points at the Aura Virtual Graph engine.

Usage:
    uv run vg-demo                          # fraud demo: every fast query
    uv run vg-demo --all                    # also attempt the slow / unsupported queries
    uv run vg-demo --query 5                # run a single fraud query by number
    uv run vg-demo --only 5 6               # run a subset, in this order
    uv run vg-demo --rows 5                 # cap printed rows per query
    uv run vg-demo --timeout 60             # per-query server timeout in seconds (default 120)

    uv run vg-demo --demo basic             # basic exploration / visualization queries

    uv run vg-demo --demo fast-gds          # 7-day window: size, project, stream top 10, drop
    uv run vg-demo --demo fast-gds --since-hours 2   # thin sub-day slice (~a couple hundred edges)
    uv run vg-demo --demo fast-gds --count-only      # only size the window; no session
    uv run vg-demo --demo fast-gds --limit 25        # stream the top 25
    uv run vg-demo --demo fast-gds --keep            # leave the projection/session in place

    uv run vg-demo --demo slow-gds          # demonstrate the GDS forms that fail

    uv run vg-demo --demo gds-probe --since-hours 2   # sweep property projections to isolate the edge-case bug
"""

from __future__ import annotations

import argparse

from neo4j import GraphDatabase

from connection import load_connection
from demos.basic import run_basic
from demos.fraud import run_fraud
from demos.gds_common import override_bolt_read_timeout
from demos.gds_fast import run_gds
from demos.gds_probe import run_probe
from demos.gds_slow import run_slow_gds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo",
                        choices=("fraud", "basic", "fast-gds", "slow-gds", "gds-probe"),
                        default="fraud", help="which demo to run (default: fraud)")

    fraud = parser.add_argument_group("fraud demo")
    fraud.add_argument("--all", action="store_true",
                       help="also attempt the slow / unsupported fraud queries (guarded)")
    fraud.add_argument("--query", type=int, metavar="N",
                       help="run only the query with this number")
    fraud.add_argument("--only", type=int, nargs="+", metavar="N",
                       help="run only these query numbers, in this order")

    shared = parser.add_argument_group("fraud + basic demos")
    shared.add_argument("--rows", type=int, default=10, metavar="N",
                        help="maximum rows to print per query (default: 10)")
    shared.add_argument("--timeout", type=float, default=120.0, metavar="SECONDS",
                        help="per-query server-side timeout (default: 120)")

    gds = parser.add_argument_group("gds demos (fast-gds / slow-gds)")
    gds.add_argument("--graph", default="account_transfers_recent", metavar="NAME",
                     help="projection / in-memory graph name (default: account_transfers_recent)")
    gds.add_argument("--since-days", type=int, default=7, metavar="N",
                     help="window size: project transfers from the last N days of data (default: 7)")
    gds.add_argument("--since-hours", type=float, default=None, metavar="H",
                     help="window size in hours; overrides --since-days for a thin recent "
                          "slice (e.g. --since-hours 2 projects ~a couple hundred edges)")
    gds.add_argument("--memory", default="2GB", metavar="SIZE",
                     help="session instance size that provisions the GDS Session (default: 2GB)")
    gds.add_argument("--limit", type=int, default=10, metavar="N",
                     help="number of top-ranked nodes to stream (default: 10)")
    gds.add_argument("--count-only", action="store_true",
                     help="only run the sizing count for the window; never provision a session")
    gds.add_argument("--keep", action="store_true",
                     help="skip the final drop so the projection/session can be reused")
    gds.add_argument("--read-timeout", type=float, default=None, metavar="SECONDS",
                     help="override the 60s Bolt read timeout Aura pins, to get past the "
                          "client-side trip on a long, silent provisioning. 0 disables it "
                          "entirely. Necessary but not sufficient: the server can still reset "
                          "the connection on long provisions. Unsupported; unset keeps 60s")
    gds.add_argument("--probe-read-timeout", type=float, default=300.0, metavar="SECONDS",
                     help="gds-probe only: default Bolt read-timeout clamp so a known-good "
                          "~130s provisioning is not aborted by the 60s client trip while the "
                          "sweep measures property failures (default: 300; --read-timeout wins)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # The GDS demos manage their own connection: the Bolt read-timeout override must be
    # installed before the driver opens, and they stream rather than running the shared
    # query loop.
    if args.demo == "fast-gds":
        run_gds(args)
        print(f"\n{'=' * 78}\nDone.")
        return
    if args.demo == "slow-gds":
        run_slow_gds(args)
        print(f"\n{'=' * 78}\nDone.")
        return
    if args.demo == "gds-probe":
        run_probe(args)
        print(f"\n{'=' * 78}\nDone.")
        return

    # The fraud --all set includes slow / unsupported queries. The server's 60s Bolt
    # read timeout (left in place) is what trips a silent slow query; --read-timeout can
    # raise or disable it. Install before the driver opens. The fast queries finish well
    # under 60s, so this only affects the slow ones.
    if args.demo == "fraud" and args.all and args.read_timeout is not None:
        seconds = None if args.read_timeout == 0 else args.read_timeout
        override_bolt_read_timeout(seconds)
        shown = "disabled (no timeout)" if seconds is None else f"{seconds:g}s"
        print(f"--all: Bolt read timeout overridden to {shown} for the slow queries.")

    uri, auth = load_connection()
    print(f"Connecting to {uri} ...")
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        if args.demo == "basic":
            print("Connected. Running basic exploration / visualization queries.")
            run_basic(driver, args.rows, args.timeout)
        else:
            run_fraud(driver, args)
    print(f"\n{'=' * 78}\nDone.")


if __name__ == "__main__":
    main()

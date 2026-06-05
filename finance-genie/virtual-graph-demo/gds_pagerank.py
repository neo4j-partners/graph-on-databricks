"""Test a GDS Session + PageRank against the Neo4j Virtual Graph.

GDS is not an in-database plugin on the Virtual Graph, so the classic
``CALL gds.graph.project('account_transfers', 'Account', ...)`` form is rejected with
``42NG0: Unsupported syntax`` (see ``workshop/aura_gds_guide.md``). The supported path,
documented in ``../docs/gds-guide.md``, is a **GDS Session**: pass a memory config to
the **Cypher-projection** form of ``gds.graph.project(...)`` to provision an ephemeral
session, then stream an algorithm against the named in-memory graph.

This harness probes that path for PageRank over the Account peer-to-peer transfer
network (``Account`` nodes + ``TRANSFERRED_TO`` relationships).

**Keeping the projection small.** Projecting all ~300k transfers is a full edge scan
and the slow step. Following the performance lessons in
``../docs/plain-cypher-examples-v2.md`` (rows scanned/moved set the wall-clock; a
7-day window cut a comparable query from ~223k rows / ~24.8s to ~22k rows / ~3.5s),
the projection is scoped by a **time window**: only ``TRANSFERRED_TO`` edges newer than
``max(transfer_timestamp) - N days`` are projected. Two steps:

1. A cheap ``count(t)`` **sizing query** runs first (no session), so you can see how big
   the projection will be before paying to provision one. ``--count-only`` stops here,
   which lets you tune ``--since-days`` cheaply.
2. The same windowed ``MATCH`` is then projected into the session and PageRank streamed.

The window PageRank measures centrality in the *recent* money-flow graph. There is no
write-back to the relational source on a Virtual Graph, so results are streamed to the
app rather than written to nodes.

Connection details come from the parent ``finance-genie/.env`` via ``main``.

Usage:
    uv run gds_pagerank.py                   # 7-day window, size, project, stream top 10, drop
    uv run gds_pagerank.py --since-days 3     # tighter window (smaller projection)
    uv run gds_pagerank.py --since-hours 2    # thin sub-day slice (~a couple hundred edges)
    uv run gds_pagerank.py --since-hours 2 --count-only  # size the thin slice without a session
    uv run gds_pagerank.py --count-only       # only size the window; never provision a session
    uv run gds_pagerank.py --limit 25         # stream the top 25
    uv run gds_pagerank.py --memory 4GB       # request a larger session instance
    uv run gds_pagerank.py --keep             # leave the projection/session in place
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError
# Private import: the only way to override the server-pinned Bolt read timeout (see
# override_bolt_read_timeout below). No public driver config exposes this.
from neo4j._sync.io._bolt_socket import BoltSocket

from main import data_max_dates, load_connection

COUNT_WINDOW = """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
RETURN count(t) AS edges
"""

PROJECT_WINDOW = """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
RETURN gds.graph.project(
  $graph,
  src,
  dst,
  {
    sourceNodeLabels: labels(src),
    targetNodeLabels: labels(dst),
    relationshipType: type(t)
  },
  { memory: $memory }
) AS result
"""

DROP_GRAPH = """
CALL gds.graph.drop($graph, false)
YIELD graphName
RETURN graphName
"""

PAGERANK_STREAM = """
CALL gds.pageRank.stream($graph)
YIELD nodeId, score
RETURN nodeId, score
ORDER BY score DESC
LIMIT $limit
"""


def override_bolt_read_timeout(seconds: float | None) -> None:
    """Raise or remove the Bolt socket read timeout the server pins via its hint.

    Aura sends a ``connection.recv_timeout_seconds: 60`` hint, so the driver declares
    a connection defunct after any 60s gap with no server bytes (no data and no NOOP
    keepalive). GDS Session provisioning can stay silent longer than 60s for
    projections above a few thousand edges, which kills the projection mid-flight with
    ``TimeoutError('The read operation timed out')``. The driver applies the hint
    unconditionally and exposes no public override, so this reaches into the sync
    ``BoltSocket`` and clamps every read timeout up to ``seconds``, or removes it
    entirely when ``seconds`` is ``None``.

    This is an unsupported workaround, and necessary but not sufficient. It only removes
    the client-side trip. A long provisioning that survives past 60s can still be torn
    down by the server with ``ConnectionResetError`` / ``SessionExpired``, observed
    empirically, which the client cannot control. With no read timeout a genuinely dead
    connection also blocks instead of erroring, so it is opt-in, never the default. The
    correct fix is server-side: Aura should emit keepalives during provisioning.
    """
    original = BoltSocket.set_read_timeout

    def set_read_timeout(self: BoltSocket, timeout: float | None) -> None:
        if timeout is not None:
            timeout = None if seconds is None else max(timeout, seconds)
        original(self, timeout)

    BoltSocket.set_read_timeout = set_read_timeout


def run_statement(driver: Driver, label: str, cypher: str,
                  params: dict[str, object]) -> list[dict[str, object]] | None:
    """Run one statement to completion, timing it and reporting any Neo4j error.

    Uses an explicit ``session.run`` (no managed-transaction retry) so a slow statement
    is never silently re-run, then returns its rows. On a Neo4jError the code and
    message are printed and ``None`` is returned, since learning *why* a statement is
    rejected is the point of this probe.
    """
    print(f"\n--- {label}")
    t0 = time.perf_counter()
    try:
        with driver.session() as session:
            rows = [record.data() for record in session.run(cypher, **params)]
    except Neo4jError as exc:
        elapsed = time.perf_counter() - t0
        print(f"  FAILED after {elapsed:.1f}s: {exc.code}\n  {exc.message}")
        return None
    elapsed = time.perf_counter() - t0
    print(f"  OK {elapsed:.1f}s, {len(rows)} row(s)")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", default="account_transfers_recent", metavar="NAME",
                        help="projection / in-memory graph name (default: account_transfers_recent)")
    parser.add_argument("--since-days", type=int, default=7, metavar="N",
                        help="window size: project transfers from the last N days of data (default: 7)")
    parser.add_argument("--since-hours", type=float, default=None, metavar="H",
                        help="window size in hours; overrides --since-days for a thin recent "
                             "slice (e.g. --since-hours 2 projects ~a couple hundred edges)")
    parser.add_argument("--memory", default="2GB", metavar="SIZE",
                        help="session instance size that provisions the GDS Session (default: 2GB)")
    parser.add_argument("--limit", type=int, default=10, metavar="N",
                        help="number of top-ranked nodes to stream (default: 10)")
    parser.add_argument("--count-only", action="store_true",
                        help="only run the sizing count for the window; never provision a session")
    parser.add_argument("--keep", action="store_true",
                        help="skip the final drop so the projection/session can be reused")
    parser.add_argument("--read-timeout", type=float, default=None, metavar="SECONDS",
                        help="override the 60s Bolt read timeout Aura pins, to get past the "
                             "client-side trip on a long, silent provisioning. 0 disables it "
                             "entirely. Necessary but not sufficient: the server can still reset "
                             "the connection on long provisions. Unsupported; unset keeps 60s")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uri, auth = load_connection()

    # Install the read-timeout override before any connection opens, so the patched
    # BoltSocket is used for the projection's long, silent provisioning wait.
    if args.read_timeout is not None:
        seconds = None if args.read_timeout == 0 else args.read_timeout
        override_bolt_read_timeout(seconds)
        shown = "disabled (no timeout)" if seconds is None else f"{seconds:g}s"
        print(f"Bolt read timeout overridden to {shown} (default is the server's 60s hint).")

    print(f"Connecting to {uri} ...")
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()

        # Step 0: find the window cutoff from the dataset's max transfer timestamp
        # (a cheap max() scan). The data ends in the past, so anchor to its max, not now.
        # --since-hours, when set, overrides --since-days for a thin sub-day slice. The
        # cutoff is computed here and passed as $since, so the WHERE stays a plain
        # `>= $since` comparison (the Virtual Graph cannot do temporal arithmetic).
        if args.since_hours is not None:
            window = dt.timedelta(hours=args.since_hours)
            window_label = f"last {args.since_hours}h"
        else:
            window = dt.timedelta(days=args.since_days)
            window_label = f"last {args.since_days}d"
        max_transfer, _ = data_max_dates(driver)
        since = max_transfer.to_native() - window
        print(f"Connected. Window: {window_label}, "
              f"transfer_timestamp >= {since} (data max {max_transfer.to_native()}).")
        print(f"Target graph '{args.graph}', memory={args.memory}.")

        # Step 1: cheap sizing query, no session. See how big the projection will be.
        sized = run_statement(driver, f"size window (count edges, {window_label})",
                              COUNT_WINDOW, {"since": since})
        if sized is None:
            return
        edges = sized[0]["edges"]
        print(f"  -> {edges} TRANSFERRED_TO edge(s) in the window will be projected.")
        if edges == 0:
            print("\nWindow is empty; widen --since-hours/--since-days. Not provisioning a session.")
            return
        if args.count_only:
            print("\n--count-only set; sized the window without provisioning a session.")
            return

        # Step 2a: clear any stale projection from a previous run (best effort).
        run_statement(driver, f"drop stale projection '{args.graph}'", DROP_GRAPH,
                      {"graph": args.graph})

        # Step 2b: provision the session and project the windowed subgraph. The final
        #          { memory } argument is what starts the GDS Session.
        projected = run_statement(
            driver,
            f"project '{args.graph}' from the window (provisions the session)",
            PROJECT_WINDOW,
            {"graph": args.graph, "memory": args.memory, "since": since},
        )
        if projected is None:
            print("\nProjection failed; cannot run PageRank. See the error above.")
            return
        for row in projected:
            print(f"  {row['result']}")

        # Step 3: stream PageRank. No write-back exists on a Virtual Graph, so results
        #         come back to the app rather than being written to nodes.
        ranked = run_statement(
            driver,
            f"PageRank stream (top {args.limit})",
            PAGERANK_STREAM,
            {"graph": args.graph, "limit": args.limit},
        )
        if ranked:
            print(f"\n  Top {len(ranked)} accounts by PageRank (recent window):")
            print("  nodeId        score")
            print("  ------------  ----------")
            for row in ranked:
                print(f"  {row['nodeId']!s:<12}  {row['score']:.6f}")

        # Step 4: clean up unless asked to keep the session alive for reuse.
        if args.keep:
            print(f"\n--keep set; leaving '{args.graph}' in place.")
        else:
            run_statement(driver, f"drop projection '{args.graph}'", DROP_GRAPH,
                          {"graph": args.graph})

    print(f"\n{'=' * 78}\nDone.")


if __name__ == "__main__":
    main()

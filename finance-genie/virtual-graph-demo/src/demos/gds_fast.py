"""Fast-gds demo (``--demo fast-gds``).

The working GDS Session + PageRank path over a small, recent window of the Account
transfer network, provisioned via the Cypher-projection form of
``gds.graph.project(...)``. See ``gds-guide.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt

from neo4j import GraphDatabase

from connection import load_connection
from demos.gds_common import DROP_GRAPH, override_bolt_read_timeout, run_statement
from helpers import data_max_dates

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

PAGERANK_STREAM = """
CALL gds.pageRank.stream($graph)
YIELD nodeId, score
RETURN nodeId, score
ORDER BY score DESC
LIMIT $limit
"""


def run_gds(args: argparse.Namespace) -> None:
    """Provision a GDS Session over a windowed transfer subgraph and stream PageRank."""
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

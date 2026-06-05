"""Slow-gds demo (``--demo slow-gds``).

The GDS forms that do not work, kept to demonstrate the failures: the classic
``CALL gds.graph.project('g', 'Account', ...)`` form (rejected with ``42NG0``) and a
large-window projection (trips the 60s Bolt read timeout).
"""

from __future__ import annotations

import argparse

from neo4j import GraphDatabase

from connection import load_connection
from demos.gds_common import DROP_GRAPH, override_bolt_read_timeout, run_statement

# slow-gds: the classic label/type CALL form, rejected on the Virtual Graph with 42NG0.
PROJECT_LABEL_FORM = """
CALL gds.graph.project($graph, 'Account', 'TRANSFERRED_TO')
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
"""

# slow-gds: a full-graph Cypher projection. Provisioning a session over every transfer
# stays silent long enough to trip the Bolt read timeout (and the server can also reset
# a long provision). Same shape as PROJECT_WINDOW but with no time filter.
PROJECT_ALL = """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
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


def run_slow_gds(args: argparse.Namespace) -> None:
    """Demonstrate the GDS forms that do not work on the Virtual Graph.

    Two failures, both expected and caught: the classic label/type ``CALL
    gds.graph.project`` form (rejected fast with ``42NG0``), and a full-graph Cypher
    projection (provisioning stays silent and trips the Bolt read timeout).
    """
    uri, auth = load_connection()

    # Leave the server's 60s Bolt read timeout in place: it is what trips a silent full
    # projection. --read-timeout can raise it or (with 0) disable it; disabling lets the
    # projection survive past 60s only to be reset by the server on a long provision.
    if args.read_timeout is not None:
        seconds = None if args.read_timeout == 0 else args.read_timeout
        override_bolt_read_timeout(seconds)
        shown = "disabled (no timeout)" if seconds is None else f"{seconds:g}s"
        print(f"Bolt read timeout overridden to {shown}.")
    print("These GDS forms are expected to FAIL. The full projection trips the 60s Bolt "
          "read timeout (often after minutes of silent provisioning) or is reset by the "
          "server; it cannot be cancelled and can saturate the pool. Run on a clean instance.")

    print(f"Connecting to {uri} ...")
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        print("Connected.")

        # Failure 1: the in-database label/type CALL form. Not supported on Virtual
        # Graph; rejected fast with 42NG0. The Cypher-projection form (fast-gds) is the
        # working path.
        run_statement(
            driver,
            "classic CALL gds.graph.project('g', 'Account', 'TRANSFERRED_TO')",
            PROJECT_LABEL_FORM, {"graph": args.graph})

        # Failure 2: project the full transfer graph (~300k edges). Provisioning stays
        # silent past the clamped read timeout and trips, or the server resets it.
        print("\nAttempting a full-graph projection (expected to trip the read timeout)...")
        run_statement(
            driver,
            f"project ALL transfers into '{args.graph}' (provisions a session)",
            PROJECT_ALL, {"graph": args.graph, "memory": args.memory})

        # Best-effort cleanup of any partial projection so a later run starts clean.
        run_statement(driver, f"drop any partial projection '{args.graph}'", DROP_GRAPH,
                      {"graph": args.graph})

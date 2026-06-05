"""Shared GDS helpers used by the fast-gds and slow-gds demos (and the CLI).

Holds the Bolt read-timeout override, the single-statement runner, and the graph-drop
Cypher that both GDS paths need.
"""

from __future__ import annotations

import time

from neo4j import Driver

# Private import: the only way to override the server-pinned Bolt read timeout (see
# override_bolt_read_timeout below). No public driver config exposes this.
from neo4j._sync.io._bolt_socket import BoltSocket
from neo4j.exceptions import DriverError, Neo4jError

from helpers import _driver_error

DROP_GRAPH = """
CALL gds.graph.drop($graph, false)
YIELD graphName
RETURN graphName
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
    except DriverError as exc:
        elapsed = time.perf_counter() - t0
        print(f"  FAILED after {elapsed:.1f}s: {_driver_error(exc)}")
        return None
    elapsed = time.perf_counter() - t0
    print(f"  OK {elapsed:.1f}s, {len(rows)} row(s)")
    return rows

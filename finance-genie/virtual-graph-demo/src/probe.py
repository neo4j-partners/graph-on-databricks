"""Single-query probe for the Virtual Graph.

Runs one Cypher statement, measures wall-clock time, prints the result, and never
abandons the query (no thread cap, no client timeout). Pass the Cypher as argv[1].

    uv run vg-probe "RETURN 1 AS ok"

Reads the parent ``finance-genie/.env`` by default; set ``PROBE_ENV`` to point at
another dotenv.
"""

from __future__ import annotations

import sys
import time

from neo4j import GraphDatabase

from connection import load_connection


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: uv run vg-probe "<cypher>"')
    cypher = sys.argv[1]
    uri, auth = load_connection()

    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        print(f"connected: {uri}", flush=True)
        t0 = time.perf_counter()
        recs, _, _ = driver.execute_query(cypher)
        elapsed = time.perf_counter() - t0
        sample = recs[0].data() if recs else None
        print(f"OK {elapsed:.1f}s rows={len(recs)} sample={sample}", flush=True)


if __name__ == "__main__":
    main()

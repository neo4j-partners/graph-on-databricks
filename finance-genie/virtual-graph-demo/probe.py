"""Single-query probe for the Virtual Graph.

Runs one Cypher statement, measures wall-clock time, prints the result, and never
abandons the query (no thread cap, no client timeout). Pass the Cypher as argv[1].

    uv run probe.py "RETURN 1 AS ok"
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: uv run probe.py "<cypher>"')
    cypher = sys.argv[1]
    env_file = Path(os.environ["PROBE_ENV"]).expanduser() if os.environ.get("PROBE_ENV") else PARENT_ENV
    load_dotenv(env_file, override=True)
    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])

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

"""Probe which Cypher features the Neo4j Virtual Graph translator supports.

Each probe isolates a single language feature so the pass/fail boundary is
unambiguous. Connection details come from the parent ``finance-genie/.env``.

Hardened after the lessons in ``../virtual-graph-demo/test-vg-next.md``:

- **EXPLAIN by default.** A probe is a *translation* question: does the Virtual
  Graph turn this Cypher into SQL at all? ``EXPLAIN`` answers that without
  executing on the Databricks warehouse, so it cannot saturate the ~10-slot
  JDBC connection pool and cannot hang on a heavy aggregation. Unsupported
  syntax still surfaces as ``42NG0`` at translate time. Use ``--run`` to execute
  for real (slower, pool-sensitive).
- **No managed-transaction retry.** Each probe runs in an explicit
  ``session.begin_transaction(timeout=...)`` / ``tx.run``. The managed
  ``driver.execute_query`` silently retries on a read timeout, which turns one
  slow query into a retry/DNS-failure storm that aborts the whole batch.
- **Broad exception catch.** Any failure (``Neo4jError``, ``ServiceUnavailable``,
  ``DriverError``, socket errors) is recorded for that probe and the batch
  continues, instead of one drop killing every remaining probe.
- **Incremental results.** Each verdict is appended to a JSONL file and stdout is
  flushed as it lands, so a mid-run failure still leaves a partial record.
- **Pool health gate.** ``RETURN 1`` is checked between probes; the batch stops
  if the pool degrades or after two timeouts.

Usage:
    uv run python -u capability_probe.py                  # EXPLAIN every probe
    uv run python -u capability_probe.py --only 1 2       # just probes 1 and 2
    uv run python -u capability_probe.py --run --only 8   # actually execute probe 8
    uv run python -u capability_probe.py --timeout 90     # per-probe cap (seconds)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"
RESULTS_FILE = Path(__file__).resolve().parent / "probe_results.jsonl"

DEFAULT_TIMEOUT = 120.0  # per-probe cap, seconds
HEALTH_CAP = 60.0
MAX_TIMEOUTS = 2  # stop the batch after this many timeouts to protect the pool


@dataclass(frozen=True)
class Probe:
    number: int
    feature: str
    cypher: str


PROBES: list[Probe] = [
    Probe(1, "baseline MATCH + RETURN prop", "MATCH (a:Account) RETURN a.account_id LIMIT 3"),
    Probe(
        2,
        "WHERE on raw node property",
        "MATCH (a:Account) WHERE a.balance > 0 RETURN a.account_id LIMIT 3",
    ),
    Probe(
        3,
        "aggregation in RETURN (no WITH)",
        "MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account) RETURN count(t) AS c",
    ),
    Probe(
        4,
        "aggregating WITH then RETURN",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, count(t) AS c
RETURN a.account_id, c ORDER BY c DESC LIMIT 3
""",
    ),
    Probe(
        5,
        "aggregating WITH then HAVING-style WHERE",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, count(t) AS c
WHERE c >= 5
RETURN a.account_id, c ORDER BY c DESC LIMIT 3
""",
    ),
    Probe(
        6,
        "count(DISTINCT x) in WITH",
        """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH dst, count(DISTINCT src) AS senders
RETURN dst.account_id, senders ORDER BY senders DESC LIMIT 3
""",
    ),
    Probe(
        7,
        "count(DISTINCT x) in RETURN",
        """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
RETURN count(DISTINCT src) AS distinct_senders
""",
    ),
    Probe(
        8,
        "sum() in WITH",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, sum(t.amount) AS outflow
RETURN a.account_id, outflow ORDER BY outflow DESC LIMIT 3
""",
    ),
    Probe(
        9,
        "round(sum()) in WITH",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, round(sum(t.amount), 2) AS outflow
RETURN a.account_id, outflow ORDER BY outflow DESC LIMIT 3
""",
    ),
    Probe(
        10,
        "avg() in WITH",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, avg(t.amount) AS mean
RETURN a.account_id, mean ORDER BY mean DESC LIMIT 3
""",
    ),
    Probe(
        11,
        "multiple aggregates in one WITH",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WITH a, count(t) AS n, sum(t.amount) AS s
RETURN a.account_id, n, s ORDER BY n DESC LIMIT 3
""",
    ),
    Probe(12, "datetime() literal", "RETURN datetime() AS now"),
    Probe(13, "datetime() - duration()", "RETURN datetime() - duration({days: 7}) AS cutoff"),
    Probe(14, "date() literal", "RETURN date() AS today"),
    Probe(
        15,
        "WHERE temporal arithmetic before WITH",
        """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime() - duration({days: 7})
RETURN count(t) AS recent
""",
    ),
    Probe(
        16,
        "date(property) projection",
        """
MATCH (a:Account)-[t:TRANSACTED_WITH]->(:Merchant)
RETURN date(t.txn_timestamp) AS day LIMIT 3
""",
    ),
    Probe(
        17,
        "two-hop path RETURN",
        """
MATCH (a:Account)-[:TRANSFERRED_TO]->(b:Account)-[:TRANSFERRED_TO]->(c:Account)
RETURN a.account_id, b.account_id, c.account_id LIMIT 3
""",
    ),
    Probe(
        18,
        "reciprocal 2-cycle (query 4 shape)",
        """
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id
RETURN a.account_id, b.account_id, count(*) AS legs
ORDER BY legs DESC LIMIT 3
""",
    ),
    Probe(
        19,
        "collect() in WITH",
        """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH dst, collect(src.account_id) AS senders
RETURN dst.account_id, size(senders) AS n ORDER BY n DESC LIMIT 3
""",
    ),
    Probe(
        20,
        "collect(DISTINCT) in WITH",
        """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH dst, collect(DISTINCT src.account_id) AS senders
RETURN dst.account_id, size(senders) AS n ORDER BY n DESC LIMIT 3
""",
    ),
    Probe(
        21,
        "OPTIONAL MATCH",
        """
MATCH (a:Account)
OPTIONAL MATCH (a)-[t:TRANSFERRED_TO]->(:Account)
RETURN a.account_id, count(t) AS n ORDER BY n DESC LIMIT 3
""",
    ),
    Probe(
        22,
        "undirected relationship pattern",
        """
MATCH (a:Account)-[t:TRANSFERRED_TO]-(:Account)
WITH a, count(t) AS deg
RETURN a.account_id, deg ORDER BY deg DESC LIMIT 3
""",
    ),
    Probe(
        23,
        "CASE expression in RETURN",
        """
MATCH (a:Account)
RETURN a.account_id,
       CASE WHEN a.balance < 10000 THEN 'low' ELSE 'high' END AS tier
LIMIT 3
""",
    ),
    Probe(
        24,
        "DISTINCT in RETURN (row-level)",
        "MATCH (a:Account) RETURN DISTINCT a.account_type AS t",
    ),
    Probe(
        25,
        "variable-length path {2,4}",
        """
MATCH path = (a:Account)-[:TRANSFERRED_TO]->{2,4}(a)
RETURN a.account_id LIMIT 3
""",
    ),
    Probe(
        26,
        "two aggregating WITH chained",
        """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WITH dst, count(t) AS inflow
WITH dst, inflow ORDER BY inflow DESC LIMIT 3
RETURN dst.account_id, inflow
""",
    ),
]


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


def run_capped(driver: Driver, cypher: str, timeout: float) -> dict[str, object]:
    """Run one statement in a worker thread, capped at ``timeout`` seconds.

    Uses an explicit ``begin_transaction`` (no managed-transaction retry) so a
    read timeout cannot silently re-run the query. Returns a verdict dict with
    keys: verdict (PASS/FAIL/TIMEOUT), detail, seconds.
    """
    box: dict[str, object] = {}

    def work() -> None:
        t0 = time.perf_counter()
        try:
            with driver.session() as session:
                tx = session.begin_transaction(timeout=timeout)
                try:
                    result = tx.run(cypher)
                    rows = [record.data() for record in result]
                finally:
                    tx.close()
            box["res"] = (time.perf_counter() - t0, len(rows))
        except Exception as exc:  # noqa: BLE001 - record any failure, keep batch alive
            code = getattr(exc, "code", type(exc).__name__)
            msg = getattr(exc, "message", str(exc))
            box["err"] = (time.perf_counter() - t0, str(code), str(msg).splitlines()[0])

    th = threading.Thread(target=work, daemon=True)
    th.start()
    # Give the worker a little longer than the server timeout to unwind cleanly.
    th.join(timeout + 15.0)
    if th.is_alive():
        return {"verdict": "TIMEOUT", "detail": f"no return within {timeout:.0f}s",
                "seconds": timeout}
    if "err" in box:
        secs, code, msg = box["err"]
        return {"verdict": "FAIL", "detail": f"{code}: {msg}", "seconds": round(secs, 1)}
    secs, n = box["res"]
    return {"verdict": "PASS", "detail": f"{n} row(s)", "seconds": round(secs, 1)}


def health(driver: Driver) -> tuple[bool, str]:
    """Return (ok, detail) from a RETURN 1 probe, capped at HEALTH_CAP seconds."""
    box: dict[str, object] = {}

    def work() -> None:
        t0 = time.perf_counter()
        try:
            driver.execute_query("RETURN 1 AS ok")
            box["ok"] = time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001
            box["err"] = f"{getattr(exc, 'code', type(exc).__name__)}"

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(HEALTH_CAP)
    if th.is_alive():
        return False, f"RETURN 1 did not return within {HEALTH_CAP:.0f}s"
    if "err" in box:
        return False, str(box["err"])
    return True, f"RETURN 1 {box['ok']:.1f}s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", type=int, nargs="+", metavar="N",
                        help="run only these probe numbers, in this order")
    parser.add_argument("--run", action="store_true",
                        help="execute on the warehouse instead of EXPLAIN-only")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        metavar="SECONDS", help=f"per-probe cap (default {DEFAULT_TIMEOUT:g})")
    parser.add_argument("--out", type=Path, default=RESULTS_FILE,
                        help=f"JSONL results file (default {RESULTS_FILE.name})")
    return parser.parse_args()


def select_probes(only: list[int] | None) -> list[Probe]:
    by_number = {p.number: p for p in PROBES}
    if only is None:
        return list(PROBES)
    missing = [n for n in only if n not in by_number]
    if missing:
        sys.exit(f"No probe(s) numbered {missing} (valid: 1-{len(PROBES)})")
    return [by_number[n] for n in only]


def main() -> None:
    args = parse_args()
    selected = select_probes(args.only)
    mode = "RUN" if args.run else "EXPLAIN"
    prefix = "" if args.run else "EXPLAIN\n"

    uri, auth = load_connection()
    print(f"Connecting to {uri} ...", flush=True)
    print(f"Mode: {mode}; {len(selected)} probe(s); cap {args.timeout:g}s each", flush=True)
    print(f"Results -> {args.out}\n", flush=True)

    results: list[tuple[Probe, dict[str, object]]] = []
    timeouts = 0
    with GraphDatabase.driver(uri, auth=auth) as driver, args.out.open("a") as out:
        driver.verify_connectivity()
        ok, detail = health(driver)
        print(f"pre-batch health: {detail}", flush=True)
        if not ok:
            print("Pool already unhealthy, aborting.", flush=True)
            return

        for probe in selected:
            print(f"\n[{probe.number}] {probe.feature}", flush=True)
            verdict = run_capped(driver, prefix + probe.cypher, args.timeout)
            record = {"n": probe.number, "feature": probe.feature, "mode": mode, **verdict}
            out.write(json.dumps(record) + "\n")
            out.flush()
            print(f"    {verdict['verdict']} ({verdict['seconds']}s) {verdict['detail']}",
                  flush=True)
            results.append((probe, verdict))

            if verdict["verdict"] == "TIMEOUT":
                timeouts += 1
            ok, detail = health(driver)
            print(f"    post-health: {detail}", flush=True)
            if not ok:
                print("POOL DEGRADED, stopping batch.", flush=True)
                break
            if timeouts >= MAX_TIMEOUTS:
                print(f"{MAX_TIMEOUTS} timeouts reached, stopping batch.", flush=True)
                break

    print(f"\n{'=' * 78}\nSUMMARY ({mode})\n{'=' * 78}", flush=True)
    for probe, verdict in results:
        print(f"  [{verdict['verdict']:7}] {probe.number:>2}  {probe.feature}"
              f"  -- {verdict['detail']}", flush=True)


if __name__ == "__main__":
    main()

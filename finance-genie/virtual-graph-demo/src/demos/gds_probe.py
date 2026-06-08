"""Gds-probe demo (``--demo gds-probe``).

Isolate the edge-case projection failure noted in ``gds-limitations.md``: "Cypher
projections can fail on certain relationship property values." The working fast-gds
projection maps only labels and ``relationshipType``; it never projects ``amount`` or
``transfer_timestamp`` as graph properties. A GDS in-memory graph only accepts numeric
property types (Long / Double / numeric arrays), so this probe sweeps a series of
projections that add node and relationship properties one at a time, on a thin window
(so the 60s read timeout is out of the picture), to find which property configs the
projection rejects and how.

Each scenario provisions its own session, so the sweep is slow; keep the window thin.
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass

from neo4j import GraphDatabase, Driver
from neo4j.time import Date, DateTime, Time, Duration

from connection import load_connection
from demos.gds_common import DROP_GRAPH, override_bolt_read_timeout, run_statement
from helpers import data_max_dates

COUNT_WINDOW = """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
RETURN count(t) AS edges
"""

# Sample one windowed relationship and its endpoints to introspect the property keys
# and types actually present, so the sweep projects real properties and the summary can
# explain a failure in terms of the value type GDS saw.
SAMPLE_ROW = """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
RETURN properties(t) AS rel, properties(src) AS node
LIMIT 1
"""

# Build the projection around a data-config body assembled per scenario. The body is a
# Cypher map literal whose expressions reference src / dst / t; it is an internal string,
# not user input.
PROJECT_TEMPLATE = """
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= $since
RETURN gds.graph.project(
  $graph,
  src,
  dst,
  {{ {data_config} }},
  {{ memory: $memory }}
) AS result
"""

# After a projection that carries a numeric relationship property, confirm the property
# is real and usable by running PageRank weighted by it.
PAGERANK_WEIGHTED = """
CALL gds.pageRank.stream($graph, {{ relationshipWeightProperty: '{prop}' }})
YIELD nodeId, score
RETURN nodeId, score
ORDER BY score DESC
LIMIT 5
"""

# The label/type-only base every scenario starts from (the known-good fast-gds shape).
BASE_CONFIG = (
    "sourceNodeLabels: labels(src), "
    "targetNodeLabels: labels(dst), "
    "relationshipType: type(t)"
)


@dataclass
class Scenario:
    """One projection variant in the sweep."""

    key: str
    description: str
    data_config: str
    weight_prop: str | None = None  # if set, run a weighted PageRank after projecting


def _type_name(value: object) -> str:
    """Readable type label for a sampled property value (numeric vs not)."""
    if isinstance(value, bool):
        return "boolean (non-numeric)"
    if isinstance(value, int):
        return "integer (numeric)"
    if isinstance(value, float):
        return "float (numeric)"
    if isinstance(value, (Date, DateTime, Time, Duration)):
        return f"{type(value).__name__} (temporal, non-numeric)"
    if isinstance(value, str):
        return "string (non-numeric)"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _pick_props(node_props: dict[str, object]) -> tuple[str | None, str | None]:
    """Pick one numeric and one non-numeric node property to probe, if available."""
    numeric = next(
        (k for k, v in node_props.items()
         if isinstance(v, (int, float)) and not isinstance(v, bool)),
        None,
    )
    non_numeric = next(
        (k for k, v in node_props.items()
         if isinstance(v, str) or isinstance(v, (Date, DateTime, Time, Duration))),
        None,
    )
    return numeric, non_numeric


def _build_scenarios(node_num: str | None, node_str: str | None) -> list[Scenario]:
    """Assemble the property sweep, adapting node-property scenarios to the schema."""
    scenarios = [
        Scenario("A_control", "labels + relationshipType only (the working fast-gds shape)",
                 BASE_CONFIG),
        Scenario("B_rel_amount", "relationshipProperties { amount } (numeric)",
                 BASE_CONFIG + ", relationshipProperties: { amount: t.amount }",
                 weight_prop="amount"),
        Scenario("C_rel_timestamp",
                 "relationshipProperties { transfer_timestamp } (temporal, expected to fail)",
                 BASE_CONFIG + ", relationshipProperties: { ts: t.transfer_timestamp }"),
        Scenario("D_rel_both", "relationshipProperties { amount, transfer_timestamp }",
                 BASE_CONFIG
                 + ", relationshipProperties: { amount: t.amount, ts: t.transfer_timestamp }"),
    ]
    if node_num is not None:
        scenarios.append(Scenario(
            f"E_node_numeric ({node_num})",
            f"sourceNodeProperties / targetNodeProperties {{ {node_num} }} (numeric)",
            BASE_CONFIG
            + f", sourceNodeProperties: {{ {node_num}: src.{node_num} }}"
            + f", targetNodeProperties: {{ {node_num}: dst.{node_num} }}"))
    if node_str is not None:
        scenarios.append(Scenario(
            f"F_node_nonnumeric ({node_str})",
            f"sourceNodeProperties / targetNodeProperties {{ {node_str} }} "
            "(non-numeric, expected to fail)",
            BASE_CONFIG
            + f", sourceNodeProperties: {{ {node_str}: src.{node_str} }}"
            + f", targetNodeProperties: {{ {node_str}: dst.{node_str} }}"))
    return scenarios


def run_probe(args: argparse.Namespace) -> None:
    """Sweep projection property configs on a thin window to isolate the edge-case bug."""
    uri, auth = load_connection()

    # Default to clamping (not disabling) the Bolt read timeout so the known-good ~130s
    # provisioning is not aborted by the 60s client trip, while a genuinely dead
    # connection still errors. This keeps the sweep measuring *property* failures, not
    # the timeout. --read-timeout overrides; 0 disables entirely.
    clamp = args.probe_read_timeout if args.read_timeout is None else args.read_timeout
    seconds = None if clamp == 0 else clamp
    override_bolt_read_timeout(seconds)
    shown = "disabled (no timeout)" if seconds is None else f"{seconds:g}s"
    print(f"Bolt read timeout clamped to {shown} (server pins 60s; clamped so the sweep "
          "measures property failures, not the timeout).")

    print(f"Connecting to {uri} ...")
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()

        # Window cutoff from the dataset max (data ends in the past), passed as $since.
        if args.since_hours is not None:
            window = dt.timedelta(hours=args.since_hours)
            window_label = f"last {args.since_hours}h"
        else:
            window = dt.timedelta(days=args.since_days)
            window_label = f"last {args.since_days}d"
        max_transfer, _ = data_max_dates(driver)
        since = max_transfer.to_native() - window
        print(f"Connected. Window: {window_label}, transfer_timestamp >= {since}.")

        sized = run_statement(driver, f"size window (count edges, {window_label})",
                              COUNT_WINDOW, {"since": since})
        if sized is None:
            return
        edges = sized[0]["edges"]
        print(f"  -> {edges} edge(s) in the window.")
        if edges == 0:
            print("\nWindow is empty; widen --since-hours/--since-days.")
            return

        node_num, node_str = _introspect(driver, since)
        if args.count_only:
            print("\n--count-only set; introspected the schema without provisioning.")
            return

        scenarios = _build_scenarios(node_num, node_str)
        print(f"\nRunning {len(scenarios)} projection scenario(s) on '{args.graph}', "
              f"memory={args.memory}. Each provisions its own session.")

        results: list[tuple[str, str, str]] = []
        for scenario in scenarios:
            results.append(_run_scenario(driver, args, since, scenario))

        _print_summary(results)


def _introspect(driver: Driver, since: dt.datetime) -> tuple[str | None, str | None]:
    """Print the sampled relationship/node property types and pick node props to probe."""
    sample = run_statement(driver, "introspect one windowed relationship + endpoint",
                           SAMPLE_ROW, {"since": since})
    if not sample:
        print("  Could not sample a row; node-property scenarios will be skipped.")
        return None, None
    rel_props = sample[0]["rel"] or {}
    node_props = sample[0]["node"] or {}
    print("  Relationship (TRANSFERRED_TO) property types:")
    for key, value in rel_props.items():
        print(f"    {key}: {_type_name(value)}")
    print("  Node (:Account) property types:")
    for key, value in node_props.items():
        print(f"    {key}: {_type_name(value)}")
    node_num, node_str = _pick_props(node_props)
    print(f"  Probing node properties: numeric={node_num!r}, non-numeric={node_str!r}.")
    return node_num, node_str


def _run_scenario(driver: Driver, args: argparse.Namespace, since: dt.datetime,
                  scenario: Scenario) -> tuple[str, str, str]:
    """Drop any stale graph, run one projection scenario, optionally check it, then drop."""
    print(f"\n{'=' * 78}\nScenario {scenario.key}: {scenario.description}")
    run_statement(driver, f"drop stale '{args.graph}'", DROP_GRAPH, {"graph": args.graph})

    cypher = PROJECT_TEMPLATE.format(data_config=scenario.data_config)
    projected = run_statement(
        driver, f"project ({scenario.key})", cypher,
        {"graph": args.graph, "memory": args.memory, "since": since})

    if projected is None:
        return (scenario.key, "FAIL", "projection rejected (see error above)")

    detail = "projected"
    for row in projected:
        result = row["result"]
        if isinstance(result, dict):
            detail = (f"{result.get('nodeCount')} nodes / "
                      f"{result.get('relationshipCount')} rels, "
                      f"projectMillis={result.get('projectMillis')}")

    # If the scenario carried a numeric relationship weight, confirm it is usable.
    if scenario.weight_prop is not None:
        weighted = run_statement(
            driver, f"weighted PageRank on '{scenario.weight_prop}'",
            PAGERANK_WEIGHTED.format(prop=scenario.weight_prop), {"graph": args.graph})
        if weighted is None:
            run_statement(driver, f"drop '{args.graph}'", DROP_GRAPH, {"graph": args.graph})
            return (scenario.key, "PARTIAL",
                    f"{detail}; but weighted PageRank on '{scenario.weight_prop}' failed")
        detail += f"; weighted PageRank OK ({len(weighted)} rows)"

    run_statement(driver, f"drop '{args.graph}'", DROP_GRAPH, {"graph": args.graph})
    return (scenario.key, "OK", detail)


def _print_summary(results: list[tuple[str, str, str]]) -> None:
    """Print the scenario / status / detail summary table."""
    print(f"\n{'=' * 78}\nSweep summary\n")
    key_w = max(len("scenario"), *(len(r[0]) for r in results))
    status_w = max(len("status"), *(len(r[1]) for r in results))
    print(f"  {'scenario'.ljust(key_w)}  {'status'.ljust(status_w)}  detail")
    print(f"  {'-' * key_w}  {'-' * status_w}  {'-' * 6}")
    for key, status, detail in results:
        print(f"  {key.ljust(key_w)}  {status.ljust(status_w)}  {detail}")

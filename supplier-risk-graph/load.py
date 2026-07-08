"""Load the supplier-risk-graph CSVs into Neo4j.

Reads the node and relationship CSVs written by generate_data.py and loads
them with the plain neo4j Python driver: uniqueness constraints first, then
nodes, then relationships, batched with UNWIND. Re-runnable: the target
database is wiped before loading, so it must be dedicated to this demo.

Usage:
    uv run load.py            # wipe the database and load data/
    uv run load.py --check    # parse and validate the CSVs only, no database

Connection settings come from .env (see .env.sample): NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase, Session

HERE = Path(__file__).parent
BATCH_SIZE = 1000

Converter = Callable[[str], Any]


def to_number(value: str) -> int | float:
    """Parse a numeric string, preferring int when the value is integral."""
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


CONVERTERS: dict[str, Converter] = {
    "int": int,
    "float": float,
    "number": to_number,
    "bool": lambda value: value == "true",
    "date": date.fromisoformat,
    "datetime": datetime.fromisoformat,
}


@dataclass(frozen=True)
class NodeSpec:
    csv_name: str
    label: str
    types: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RelSpec:
    csv_name: str
    rel_type: str
    src_col: str
    src_label: str
    dst_col: str
    dst_label: str
    types: dict[str, str] = field(default_factory=dict)


NODE_SPECS = [
    NodeSpec(
        "customers.csv",
        "Customer",
        {"upsellScore": "int", "avgDaysLate": "float", "overdueShare": "float"},
    ),
    NodeSpec("suppliers.csv", "Supplier", {"riskScore": "int"}),
    NodeSpec("business_units.csv", "BusinessUnit"),
    NodeSpec(
        "invoices.csv",
        "Invoice",
        {
            "amount": "float",
            "issueDate": "date",
            "dueDate": "date",
            "paidDate": "date",
            "daysLate": "int",
        },
    ),
    NodeSpec("payments.csv", "Payment", {"amount": "float", "date": "date"}),
    NodeSpec(
        "revenue_entries.csv",
        "RevenueEntry",
        {"amount": "float", "reconciled": "bool"},
    ),
    NodeSpec("compliance_findings.csv", "ComplianceFinding", {"openedDate": "date"}),
    NodeSpec("edm_entities.csv", "EDMEntity"),
    NodeSpec("business_terms.csv", "BusinessTerm"),
    NodeSpec("business_rules.csv", "BusinessRule", {"threshold": "number"}),
    NodeSpec("policies.csv", "Policy"),
    NodeSpec("thresholds.csv", "Threshold", {"value": "number"}),
    NodeSpec("data_sources.csv", "DataSource"),
]

REL_SPECS = [
    RelSpec("has_invoice.csv", "HAS_INVOICE", "customer_id", "Customer", "invoice_id", "Invoice"),
    RelSpec("settled_by.csv", "SETTLED_BY", "invoice_id", "Invoice", "payment_id", "Payment"),
    RelSpec("belongs_to.csv", "BELONGS_TO", "customer_id", "Customer", "business_unit_id", "BusinessUnit"),
    RelSpec("recognizes.csv", "RECOGNIZES", "business_unit_id", "BusinessUnit", "revenue_entry_id", "RevenueEntry"),
    RelSpec("supplies.csv", "SUPPLIES", "supplier_id", "Supplier", "business_unit_id", "BusinessUnit"),
    RelSpec("has_finding.csv", "HAS_FINDING", "customer_id", "Customer", "finding_id", "ComplianceFinding"),
    # Pre-planted classifications are customer-only (Platinum Customer and
    # Strategic Account); the other terms get written live during the demo.
    RelSpec(
        "classified_as.csv",
        "CLASSIFIED_AS",
        "entity_id",
        "Customer",
        "term_id",
        "BusinessTerm",
        {"evaluatedAt": "datetime"},
    ),
    RelSpec("defined_by.csv", "DEFINED_BY", "term_id", "BusinessTerm", "rule_id", "BusinessRule"),
    RelSpec("evaluates.csv", "EVALUATES", "rule_id", "BusinessRule", "edm_entity_id", "EDMEntity"),
    RelSpec("constrains.csv", "CONSTRAINS", "policy_id", "Policy", "edm_entity_id", "EDMEntity"),
    RelSpec("governs.csv", "GOVERNS", "policy_id", "Policy", "rule_id", "BusinessRule"),
    RelSpec("applies_to.csv", "APPLIES_TO", "threshold_id", "Threshold", "term_id", "BusinessTerm"),
    RelSpec("maps_to.csv", "MAPS_TO", "edm_entity_id", "EDMEntity", "data_source_id", "DataSource"),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def convert(raw: dict[str, str], types: dict[str, str]) -> dict[str, Any]:
    """Apply the spec's type conversions; empty strings become None."""
    converted: dict[str, Any] = {}
    for key, value in raw.items():
        if value == "":
            converted[key] = None
        elif key in types:
            converted[key] = CONVERTERS[types[key]](value)
        else:
            converted[key] = value
    return converted


def read_node_rows(data_dir: Path, spec: NodeSpec) -> list[dict[str, Any]]:
    return [convert(raw, spec.types) for raw in read_csv(data_dir / spec.csv_name)]


def read_rel_rows(data_dir: Path, spec: RelSpec) -> list[dict[str, Any]]:
    rows = []
    for raw in read_csv(data_dir / spec.csv_name):
        converted = convert(raw, spec.types)
        props = {
            key: value
            for key, value in converted.items()
            if key not in (spec.src_col, spec.dst_col)
        }
        rows.append({"src": raw[spec.src_col], "dst": raw[spec.dst_col], "props": props})
    return rows


def expand_realized_as(data_dir: Path) -> list[tuple[RelSpec, list[dict[str, Any]]]]:
    """realized_as.csv targets multiple labels; split it into one spec per label."""
    by_label: dict[str, list[dict[str, Any]]] = {}
    for raw in read_csv(data_dir / "realized_as.csv"):
        row = {"src": raw["edm_entity_id"], "dst": raw["instance_id"], "props": {}}
        by_label.setdefault(raw["instance_label"], []).append(row)
    return [
        (RelSpec("realized_as.csv", "REALIZED_AS", "edm_entity_id", "EDMEntity", "instance_id", label), rows)
        for label, rows in sorted(by_label.items())
    ]


def check_integrity(
    node_rows: dict[str, list[dict[str, Any]]],
    rel_data: list[tuple[RelSpec, list[dict[str, Any]]]],
) -> list[str]:
    """Verify every relationship endpoint id exists in its node CSV."""
    ids = {label: {row["id"] for row in rows} for label, rows in node_rows.items()}
    errors = []
    for spec, rows in rel_data:
        unknown = [label for label in (spec.src_label, spec.dst_label) if label not in ids]
        if unknown:
            errors.append(f"{spec.csv_name}: unknown node label(s) {', '.join(unknown)}")
            continue
        for row in rows:
            if row["src"] not in ids[spec.src_label]:
                errors.append(f"{spec.csv_name}: unknown {spec.src_label} id {row['src']}")
            if row["dst"] not in ids[spec.dst_label]:
                errors.append(f"{spec.csv_name}: unknown {spec.dst_label} id {row['dst']}")
    return errors


def batches(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def wipe(session: Session) -> None:
    result = session.run(
        "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
    )
    deleted = result.consume().counters.nodes_deleted
    print(f"Wiped database ({deleted} nodes deleted).")


def create_constraints(session: Session) -> None:
    for spec in NODE_SPECS:
        session.run(
            f"CREATE CONSTRAINT {spec.label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{spec.label}) REQUIRE n.id IS UNIQUE"
        ).consume()
    print(f"Ensured {len(NODE_SPECS)} uniqueness constraints.")


def load_nodes(session: Session, spec: NodeSpec, rows: list[dict[str, Any]]) -> int:
    query = f"UNWIND $rows AS row CREATE (n:{spec.label}) SET n = row"
    created = 0
    for batch in batches(rows):
        created += session.execute_write(
            lambda tx, batch=batch: tx.run(query, rows=batch).consume().counters.nodes_created
        )
    return created


def load_rels(session: Session, spec: RelSpec, rows: list[dict[str, Any]]) -> int:
    query = (
        f"UNWIND $rows AS row "
        f"MATCH (a:{spec.src_label} {{id: row.src}}) "
        f"MATCH (b:{spec.dst_label} {{id: row.dst}}) "
        f"CREATE (a)-[r:{spec.rel_type}]->(b) SET r += row.props"
    )
    created = 0
    for batch in batches(rows):
        created += session.execute_write(
            lambda tx, batch=batch: tx.run(query, rows=batch).consume().counters.relationships_created
        )
    return created


def require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="parse and validate the CSVs without connecting to Neo4j",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="directory holding the generated CSVs (default: data/)",
    )
    args = parser.parse_args()

    node_rows = {
        spec.label: read_node_rows(args.data_dir, spec) for spec in NODE_SPECS
    }
    rel_data = [
        (spec, read_rel_rows(args.data_dir, spec)) for spec in REL_SPECS
    ] + expand_realized_as(args.data_dir)

    errors = check_integrity(node_rows, rel_data)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        sys.exit(f"{len(errors)} referential integrity errors; not loading.")

    total_nodes = sum(len(rows) for rows in node_rows.values())
    total_rels = sum(len(rows) for _, rows in rel_data)
    print(f"Parsed {total_nodes} nodes and {total_rels} relationships from {args.data_dir}.")
    if args.check:
        print("Check passed: all relationship endpoints resolve.")
        return

    load_dotenv(HERE / ".env")
    uri = require_env("NEO4J_URI")
    auth = (require_env("NEO4J_USERNAME", "neo4j"), require_env("NEO4J_PASSWORD"))
    database = require_env("NEO4J_DATABASE", "neo4j")

    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            wipe(session)
            create_constraints(session)
            for spec in NODE_SPECS:
                created = load_nodes(session, spec, node_rows[spec.label])
                expected = len(node_rows[spec.label])
                if created != expected:
                    sys.exit(f"{spec.label}: created {created} of {expected} nodes.")
                print(f"  {spec.label}: {created} nodes")
            for spec, rows in rel_data:
                created = load_rels(session, spec, rows)
                if created != len(rows):
                    sys.exit(
                        f"{spec.rel_type} ({spec.src_label}->{spec.dst_label}): "
                        f"created {created} of {len(rows)} relationships."
                    )
                print(f"  {spec.rel_type} ({spec.src_label}->{spec.dst_label}): {created} relationships")

    print(f"Load complete: {total_nodes} nodes, {total_rels} relationships.")


if __name__ == "__main__":
    main()

"""Load the supplier-risk-graph CSVs into Neo4j.

Reads the node and relationship CSVs written by generate_data.py and loads
them with the plain neo4j Python driver: uniqueness constraints first, then
nodes, then relationships, batched with UNWIND. The loader derives nothing:
every classification is pre-planted verbatim in classified_as.csv, so the
CSVs are loaded as-is. Re-runnable: the target database is wiped before
loading, so it must be dedicated to this demo.

The instance layer carries two same-graph edges beyond the customer/supplier/
business-unit fan-out: supplier-to-supplier SUPPLIES (from supply_relationships.csv,
Cascade feeding the tier-1 bottle suppliers) and customer-to-customer OWNED_BY
(loaded from owned_by.csv with its ownership stake, the Kestrel ownership
group). classified_as.csv now targets
both Customer and Supplier, so it is split on its entity_label column into one
CLASSIFIED_AS spec per label, the same way realized_as.csv is split on
instance_label; the four column-findable terms (Strategic Account, Defaulted
Customer, Delinquent Customer, High-Risk Supplier) all ride in that one file.

The two graph-native terms, Critical Supplier and Ownership Risk, are never
written as CLASSIFIED_AS edges here or anywhere: they are resolved live at demo
time from the betweenness and PageRank node properties that gds.py (Phase 2)
precomputes. They do carry a SCORED_BY edge to a GraphMetric node naming that
property formally, which binds the term to its implementation without
materializing a classification. The knowledge layer is rebuilt around the two
stories and includes the new SupplyRelationship entity, which is just another
row in entities.csv and needs no special handling.

Everything else in the knowledge layer runs outbound from the BusinessTerm, so a
model doing schema discovery can walk from a term to the rule, the threshold
value (USES_THRESHOLD), the graph metric that implements it (SCORED_BY), the euro
measure (MEASURED_BY), the entities, and the physical Unity Catalog tables.

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
        {
            "upsellScore": "int",
            "avgDaysLate": "float",
            "overdueShare": "float",
            "creditLimit": "number",
        },
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
    NodeSpec(
        "revenue_entries.csv",
        "RevenueEntry",
        {"amount": "float", "reconciled": "bool"},
    ),
    NodeSpec("compliance_findings.csv", "ComplianceFinding", {"openedDate": "date"}),
    NodeSpec("entities.csv", "Entity"),
    NodeSpec("business_terms.csv", "BusinessTerm"),
    NodeSpec("business_rules.csv", "BusinessRule", {"threshold": "number"}),
    NodeSpec("measures.csv", "Measure"),
    NodeSpec("graph_metrics.csv", "GraphMetric"),
    NodeSpec("policies.csv", "Policy"),
    NodeSpec("thresholds.csv", "Threshold", {"value": "number"}),
    NodeSpec("data_sources.csv", "DataSource"),
]

REL_SPECS = [
    RelSpec("has_invoice.csv", "HAS_INVOICE", "customer_id", "Customer", "invoice_id", "Invoice"),
    RelSpec("belongs_to.csv", "BELONGS_TO", "customer_id", "Customer", "business_unit_id", "BusinessUnit"),
    RelSpec("recognizes.csv", "RECOGNIZES", "business_unit_id", "BusinessUnit", "revenue_entry_id", "RevenueEntry"),
    RelSpec("supplies.csv", "SUPPLIES", "supplier_id", "Supplier", "business_unit_id", "BusinessUnit"),
    # Supplier-to-supplier SUPPLIES: same rel type as the Supplier->BusinessUnit
    # edge above, different endpoints. A row from=SUP-901,to=SUP-902 means
    # SUP-901 supplies SUP-902, so the edge points fromSupplierId -> toSupplierId.
    RelSpec("supply_relationships.csv", "SUPPLIES", "fromSupplierId", "Supplier", "toSupplierId", "Supplier"),
    RelSpec("has_finding.csv", "HAS_FINDING", "customer_id", "Customer", "finding_id", "ComplianceFinding"),
    # Customer-to-customer OWNED_BY, child -> parent, carrying the ownership
    # stake. A subsidiary can have more than one owner, so this is its own CSV
    # rather than a column on the customer row. ownershipPct is what makes the
    # Story 2 propagation weighted: influence follows the size of the stake, not
    # the number of hops. The same file backs the lakehouse table plain Genie
    # reads, so the raw ownership is not hidden from it.
    RelSpec("owned_by.csv", "OWNED_BY", "customer_id", "Customer", "parent_customer_id", "Customer",
            {"ownershipPct": "float"}),
    # classified_as.csv targets both Customer and Supplier, so it is not a static
    # spec: expand_classified_as() splits it on its entity_label column, one
    # CLASSIFIED_AS spec per label. The two graph-native terms (Critical Supplier,
    # Ownership Risk) are never planted as edges; they are resolved live at demo
    # time from the gds.py node properties.
    RelSpec("defined_by.csv", "DEFINED_BY", "term_id", "BusinessTerm", "rule_id", "BusinessRule"),
    # Measure->BusinessRule DEFINED_BY: same rel type as the BusinessTerm->BusinessRule
    # edge above, different endpoints and a second source file, so the measure reaches
    # its rule with no new vocabulary. Each spec loads its own CSV independently, so
    # neither file overwrites the other's edges.
    RelSpec("measure_defined_by.csv", "DEFINED_BY", "measure_id", "Measure", "rule_id", "BusinessRule"),
    # The three edges below close the discovery asymmetry left by APPLIES_TO, which
    # runs Threshold->BusinessTerm and so is invisible to a traversal walking outbound
    # from a term. MEASURED_BY leads to the euro measure, SCORED_BY to the precomputed
    # GDS node property that resolves a graph-native term, and USES_THRESHOLD gives the
    # rule a forward path to the cutoff value it is standing on.
    RelSpec("measured_by.csv", "MEASURED_BY", "term_id", "BusinessTerm", "measure_id", "Measure"),
    RelSpec("scored_by.csv", "SCORED_BY", "term_id", "BusinessTerm", "metric_id", "GraphMetric"),
    RelSpec("rule_thresholds.csv", "USES_THRESHOLD", "rule_id", "BusinessRule", "threshold_id", "Threshold"),
    RelSpec("evaluates.csv", "EVALUATES", "rule_id", "BusinessRule", "entity_id", "Entity"),
    RelSpec("constrains.csv", "CONSTRAINS", "policy_id", "Policy", "entity_id", "Entity"),
    RelSpec("governs.csv", "GOVERNS", "policy_id", "Policy", "rule_id", "BusinessRule"),
    RelSpec("applies_to.csv", "APPLIES_TO", "threshold_id", "Threshold", "term_id", "BusinessTerm"),
    RelSpec("maps_to.csv", "MAPS_TO", "entity_id", "Entity", "data_source_id", "DataSource"),
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
        row = {"src": raw["entity_id"], "dst": raw["instance_id"], "props": {}}
        by_label.setdefault(raw["instance_label"], []).append(row)
    return [
        (RelSpec("realized_as.csv", "REALIZED_AS", "entity_id", "Entity", "instance_id", label), rows)
        for label, rows in sorted(by_label.items())
    ]


def expand_classified_as(data_dir: Path) -> list[tuple[RelSpec, list[dict[str, Any]]]]:
    """classified_as.csv targets Customer and Supplier; split it by entity_label.

    Every column-findable classification (Strategic Account, Defaulted Customer,
    Delinquent Customer, High-Risk Supplier) is pre-planted verbatim in the CSV,
    so the loader carries the provenance props (reason, evaluatedAt, ruleVersion)
    through unchanged and derives nothing. entity_label selects the source node
    label the same way instance_label does for realized_as.csv; it is not stored
    on the edge.
    """
    types = {"evaluatedAt": "datetime"}
    by_label: dict[str, list[dict[str, Any]]] = {}
    for raw in read_csv(data_dir / "classified_as.csv"):
        converted = convert(raw, types)
        props = {
            key: value
            for key, value in converted.items()
            if key not in ("entity_id", "entity_label", "term_id")
        }
        row = {"src": raw["entity_id"], "dst": raw["term_id"], "props": props}
        by_label.setdefault(raw["entity_label"], []).append(row)
    return [
        (
            RelSpec(
                "classified_as.csv",
                "CLASSIFIED_AS",
                "entity_id",
                label,
                "term_id",
                "BusinessTerm",
                types,
            ),
            rows,
        )
        for label, rows in sorted(by_label.items())
    ]


def check_integrity(
    node_rows: dict[str, list[dict[str, Any]]],
    rel_data: list[tuple[RelSpec, list[dict[str, Any]]]],
) -> list[str]:
    """Verify every relationship endpoint resolves and no endpoint pair repeats.

    load_rels issues CREATE, not MERGE, so a repeated (src, dst) pair in a CSV
    becomes a second parallel edge rather than being folded into the first. That
    is silent everywhere except the two weighted networks the demo turns on: a
    duplicated owned_by.csv row doubles a stake in the PageRank propagation that
    THR-04 is placed from, and a duplicated supply_relationships.csv row shifts
    the betweenness distribution behind THR-03. Neither shows up as a load error,
    and both move a threshold the stories are asserted against, so the pairs are
    checked here rather than trusted.
    """
    ids = {label: {row["id"] for row in rows} for label, rows in node_rows.items()}
    errors = []
    for spec, rows in rel_data:
        unknown = [label for label in (spec.src_label, spec.dst_label) if label not in ids]
        if unknown:
            errors.append(f"{spec.csv_name}: unknown node label(s) {', '.join(unknown)}")
            continue
        seen: set[tuple[str, str]] = set()
        duplicates: set[tuple[str, str]] = set()
        for row in rows:
            if row["src"] not in ids[spec.src_label]:
                errors.append(f"{spec.csv_name}: unknown {spec.src_label} id {row['src']}")
            if row["dst"] not in ids[spec.dst_label]:
                errors.append(f"{spec.csv_name}: unknown {spec.dst_label} id {row['dst']}")
            pair = (row["src"], row["dst"])
            if pair in seen:
                duplicates.add(pair)
            seen.add(pair)
        for src, dst in sorted(duplicates):
            errors.append(
                f"{spec.csv_name}: duplicate {spec.rel_type} edge "
                f"{spec.src_label} {src} -> {spec.dst_label} {dst}"
            )
    return errors


def batches(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def wipe(session: Session) -> None:
    result = session.run(
        "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
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
    rel_data = (
        [(spec, read_rel_rows(args.data_dir, spec)) for spec in REL_SPECS]
        + expand_realized_as(args.data_dir)
        + expand_classified_as(args.data_dir)
    )

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

    print(f"Load complete: {total_nodes} nodes, {total_rels} relationships from CSVs.")


if __name__ == "__main__":
    main()

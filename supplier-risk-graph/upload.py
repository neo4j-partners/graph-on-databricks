"""Upload the supplier-risk-graph instance data to Unity Catalog as Delta tables.

Two-layer demo: the lakehouse owns the data/instance layer while Neo4j owns the
knowledge layer. This script materializes the lakehouse side. It uploads the
seven instance node CSVs into a UC volume and builds one Delta table each with
`read_files`, then reads the two graph-derived tables back out of Neo4j:

  - `classifications`         — every CLASSIFIED_AS edge (rule- and GDS-planted)
  - `business_unit_exposure`  — the Q4 supplier-risk propagation result

CSV headers stay verbatim (camelCase), so the demo's Cypher and the UC column
names line up. Re-runnable: tables are CREATE OR REPLACE and the schema/volume
are created idempotently.

Usage:
    uv run upload.py            # upload CSVs, build tables, pull derived tables
    uv run upload.py --check    # parse and validate the base CSVs only, offline

Databricks auth comes from .env (see .env.sample): either DATABRICKS_CONFIG_PROFILE
or DATABRICKS_HOST + DATABRICKS_TOKEN, plus DATABRICKS_WAREHOUSE_ID and the
UC_CATALOG / UC_SCHEMA / UC_VOLUME target. Reading the derived tables reuses the
Neo4j settings (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE).
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

HERE = Path(__file__).parent

# Poll interval, in seconds, while a SQL statement is still running.
POLL_INTERVAL = 1.0

# load.py's type-name vocabulary mapped to Spark SQL types for read_files
# schemaHints. Inference would otherwise read dates and amounts as strings.
SPARK_TYPES = {
    "int": "INT",
    "float": "DOUBLE",
    "number": "DOUBLE",
    "bool": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
}


@dataclass(frozen=True)
class TableSpec:
    """A base instance table sourced from one node CSV.

    `types` names the columns whose inferred type needs correcting; the rest
    stay strings. Type names match load.py's CONVERTERS so both sides agree.
    """

    csv_name: str
    table: str
    types: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedSpec:
    """A gold table materialized from a Neo4j query."""

    table: str
    columns: list[str]
    cypher: str
    types: dict[str, str] = field(default_factory=dict)


# The seven instance node CSVs that become UC tables. Type maps mirror the
# matching NODE_SPECS in load.py; knowledge-layer and relationship CSVs stay
# graph-only. Table names match data_sources.csv.
BASE_SPECS = [
    TableSpec(
        "customers.csv",
        "customers",
        {"upsellScore": "int", "avgDaysLate": "float", "overdueShare": "float"},
    ),
    TableSpec("suppliers.csv", "suppliers", {"riskScore": "int"}),
    TableSpec("business_units.csv", "business_units"),
    TableSpec(
        "invoices.csv",
        "invoices",
        {
            "amount": "float",
            "issueDate": "date",
            "dueDate": "date",
            "paidDate": "date",
            "daysLate": "int",
        },
    ),
    TableSpec("payments.csv", "payments", {"amount": "float", "date": "date"}),
    TableSpec(
        "revenue_entries.csv",
        "revenue_entries",
        {"amount": "float", "reconciled": "bool"},
    ),
    TableSpec("compliance_findings.csv", "compliance_findings", {"openedDate": "date"}),
]

# Gold table: all CLASSIFIED_AS edges written back from the graph. Rule-planted
# edges carry ruleVersion and no source/algorithm/score; GDS edges (gds.py,
# Phase 5) carry source='gds', algorithm, score and no ruleVersion. Both land
# here, so nullable columns are expected.
CLASSIFICATIONS_SPEC = DerivedSpec(
    table="classifications",
    columns=[
        "entity_id",
        "entity_type",
        "term",
        "source",
        "algorithm",
        "score",
        "reason",
        "evaluated_at",
        "rule_version",
    ],
    cypher=(
        "MATCH (e)-[r:CLASSIFIED_AS]->(t:BusinessTerm) "
        "RETURN e.id AS entity_id, labels(e)[0] AS entity_type, t.name AS term, "
        "coalesce(r.source, 'rule') AS source, r.algorithm AS algorithm, "
        "r.score AS score, r.reason AS reason, "
        "toString(r.evaluatedAt) AS evaluated_at, r.ruleVersion AS rule_version"
    ),
    types={"score": "float", "evaluated_at": "datetime"},
)

# Gold table: the Q4 supplier-risk propagation result, one row per business
# unit. Columns match ground_truth.json's gds_q4_supplier_exposure_by_business_unit.
# supplierExposureScore is written by gds.py (Phase 5); if it has not run the
# exposure column lands null, which is fine.
EXPOSURE_SPEC = DerivedSpec(
    table="business_unit_exposure",
    columns=[
        "business_unit_id",
        "name",
        "supplier_exposure_score",
        "supplier_count",
        "avg_supplier_risk",
        "max_supplier_risk",
    ],
    cypher=(
        "MATCH (bu:BusinessUnit) "
        "OPTIONAL MATCH (s:Supplier)-[:SUPPLIES]->(bu) "
        "RETURN bu.id AS business_unit_id, bu.name AS name, "
        "bu.supplierExposureScore AS supplier_exposure_score, "
        "count(s) AS supplier_count, round(avg(s.riskScore), 1) AS avg_supplier_risk, "
        "max(s.riskScore) AS max_supplier_risk "
        "ORDER BY supplier_exposure_score DESC"
    ),
    types={
        "supplier_exposure_score": "float",
        "supplier_count": "int",
        "avg_supplier_risk": "float",
        "max_supplier_risk": "int",
    },
)

DERIVED_SPECS = [CLASSIFICATIONS_SPEC, EXPOSURE_SPEC]


@dataclass(frozen=True)
class Config:
    """Resolved Databricks and Neo4j connection settings."""

    profile: str | None
    host: str | None
    token: str | None
    warehouse_id: str
    catalog: str
    schema: str
    volume: str
    neo4j_uri: str
    neo4j_auth: tuple[str, str]
    neo4j_database: str


def require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def read_config() -> Config:
    """Read connection settings from the environment (.env already loaded)."""
    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE") or None
    if profile:
        host, token = None, None
    else:
        host = require_env("DATABRICKS_HOST")
        token = require_env("DATABRICKS_TOKEN")
    return Config(
        profile=profile,
        host=host,
        token=token,
        warehouse_id=require_env("DATABRICKS_WAREHOUSE_ID"),
        catalog=require_env("UC_CATALOG", "graph-on-databricks"),
        schema=require_env("UC_SCHEMA", "supplier_risk"),
        volume=require_env("UC_VOLUME", "supplier_risk_files"),
        neo4j_uri=require_env("NEO4J_URI"),
        neo4j_auth=(
            require_env("NEO4J_USERNAME", "neo4j"),
            require_env("NEO4J_PASSWORD"),
        ),
        neo4j_database=require_env("NEO4J_DATABASE", "neo4j"),
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def schema_hints(types: dict[str, str]) -> str | None:
    """Render a read_files schemaHints clause from a type map, or None."""
    if not types:
        return None
    return ", ".join(f"{column} {SPARK_TYPES[kind]}" for column, kind in types.items())


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    """Serialize query rows to CSV bytes; None becomes an empty field."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(column) is None else row[column] for column in columns])
    return buffer.getvalue().encode("utf-8")


def volume_path(cfg: Config, filename: str) -> str:
    return f"/Volumes/{cfg.catalog}/{cfg.schema}/{cfg.volume}/{filename}"


def fqn(cfg: Config, table: str) -> str:
    """Backtick-quoted catalog.schema.table (the catalog name has hyphens)."""
    return f"`{cfg.catalog}`.`{cfg.schema}`.`{table}`"


def run_sql(w: Any, cfg: Config, statement: str) -> Any:
    """Execute one SQL statement on the warehouse, polling until it finishes."""
    from databricks.sdk.service.sql import StatementState

    response = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=cfg.warehouse_id,
        wait_timeout="50s",
    )
    while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(POLL_INTERVAL)
        response = w.statement_execution.get_statement(response.statement_id)
    if response.status.state is not StatementState.SUCCEEDED:
        error = response.status.error
        detail = error.message if error else "no error detail"
        raise RuntimeError(f"statement failed ({response.status.state.value}): {detail}")
    return response


def count_rows(w: Any, cfg: Config, table: str) -> int:
    response = run_sql(w, cfg, f"SELECT count(*) FROM {fqn(cfg, table)}")
    return int(response.result.data_array[0][0])


def ensure_schema_and_volume(w: Any, cfg: Config) -> None:
    run_sql(w, cfg, f"CREATE SCHEMA IF NOT EXISTS `{cfg.catalog}`.`{cfg.schema}`")
    run_sql(
        w,
        cfg,
        f"CREATE VOLUME IF NOT EXISTS `{cfg.catalog}`.`{cfg.schema}`.`{cfg.volume}`",
    )
    print(f"Ensured schema `{cfg.catalog}`.`{cfg.schema}` and volume `{cfg.volume}`.")


def create_table(w: Any, cfg: Config, table: str, filename: str, hints: str | None) -> None:
    """Build a Delta table from a CSV already uploaded to the volume."""
    options = ["format => 'csv'", "header => true", "inferColumnTypes => true"]
    if hints:
        options.append(f"schemaHints => '{hints}'")
    run_sql(
        w,
        cfg,
        f"CREATE OR REPLACE TABLE {fqn(cfg, table)} AS "
        f"SELECT * FROM read_files('{volume_path(cfg, filename)}', {', '.join(options)})",
    )


def upload_csv(w: Any, cfg: Config, filename: str, contents: bytes) -> None:
    w.files.upload(volume_path(cfg, filename), io.BytesIO(contents), overwrite=True)


def upload_base_tables(w: Any, cfg: Config, data_dir: Path) -> list[tuple[str, int]]:
    print("Uploading base instance tables:")
    results = []
    for spec in BASE_SPECS:
        upload_csv(w, cfg, spec.csv_name, (data_dir / spec.csv_name).read_bytes())
        create_table(w, cfg, spec.table, spec.csv_name, schema_hints(spec.types))
        rows = count_rows(w, cfg, spec.table)
        results.append((spec.table, rows))
        print(f"  {spec.table}: {rows} rows")
    return results


def read_graph_rows(cfg: Config, cypher: str) -> list[dict[str, Any]]:
    from neo4j import GraphDatabase

    with GraphDatabase.driver(cfg.neo4j_uri, auth=cfg.neo4j_auth) as driver:
        driver.verify_connectivity()
        with driver.session(database=cfg.neo4j_database) as session:
            return [record.data() for record in session.run(cypher)]


def upload_derived_table(w: Any, cfg: Config, spec: DerivedSpec) -> int:
    rows = read_graph_rows(cfg, spec.cypher)
    filename = f"{spec.table}.csv"
    upload_csv(w, cfg, filename, rows_to_csv(spec.columns, rows))
    create_table(w, cfg, spec.table, filename, schema_hints(spec.types))
    count = count_rows(w, cfg, spec.table)
    print(f"  {spec.table}: {count} rows")
    return count


def check(data_dir: Path) -> None:
    """Offline: confirm the base CSVs read and report the row counts."""
    print(f"Validating base CSVs in {data_dir}:")
    total = 0
    for spec in BASE_SPECS:
        path = data_dir / spec.csv_name
        if not path.is_file():
            sys.exit(f"Missing CSV: {path}")
        rows = read_csv(path)
        total += len(rows)
        print(f"  {spec.table}: {len(rows)} rows ({spec.csv_name})")
    print(f"Check passed: {len(BASE_SPECS)} base tables, {total} rows ready to upload.")
    print(
        f"Derived tables read from Neo4j at upload time: "
        f"{', '.join(spec.table for spec in DERIVED_SPECS)}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the base CSVs without connecting to Databricks or Neo4j",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="directory holding the generated CSVs (default: data/)",
    )
    args = parser.parse_args()

    if args.check:
        check(args.data_dir)
        return

    load_dotenv(HERE / ".env")
    cfg = read_config()

    from databricks.sdk import WorkspaceClient

    if cfg.profile:
        w = WorkspaceClient(profile=cfg.profile)
    else:
        w = WorkspaceClient(host=cfg.host, token=cfg.token)

    ensure_schema_and_volume(w, cfg)
    base_results = upload_base_tables(w, cfg, args.data_dir)

    print("Materializing gold tables from Neo4j:")
    derived_results = [(spec.table, upload_derived_table(w, cfg, spec)) for spec in DERIVED_SPECS]

    total = sum(rows for _, rows in base_results) + sum(rows for _, rows in derived_results)
    tables = len(base_results) + len(derived_results)
    print(
        f"Upload complete: {tables} tables in "
        f"`{cfg.catalog}`.`{cfg.schema}`, {total} rows."
    )


if __name__ == "__main__":
    main()

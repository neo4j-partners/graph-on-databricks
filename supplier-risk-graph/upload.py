"""Upload the supplier-risk-graph instance data to Unity Catalog as Delta tables.

Two-layer demo: the lakehouse owns the data/instance layer while Neo4j owns the
knowledge layer. This script materializes the lakehouse side. It uploads nine
base instance CSVs — the six instance node CSVs (customers, suppliers,
business_units, invoices, revenue_entries, compliance_findings), the
supplier-to-business-unit bridge (supplier_business_units), the
supplier-to-supplier link (supply_relationships), and the customer ownership
stakes (owned_by) — into a UC volume and builds one Delta table each with
`read_files`, then reads the two graph-derived tables back out of Neo4j:

  - `classifications`         — every CLASSIFIED_AS edge (the four column-findable
                                terms plus derived Critical Supplier and Risky Customer)
  - `business_unit_exposure`  — each business unit's aggregate supplier-risk exposure

The `supply_relationships` and `owned_by` tables carry the raw edges behind the
graph's two structural relationships, uploaded so plain Genie can see both
networks in full; Neo4j sources SUPPLIES and OWNED_BY from the same CSVs. Neither
network is withheld: the demo is won on questions the lakehouse cannot compute
from those rows, not on tables it was never given. The `customers` table gains
creditLimit (the Story 2 exposure figure) and defaultedPeriod (the quarter a
customer defaulted), and `suppliers` gains subcategory (the supplier specialty).

The two gold tables (`classifications`, `business_unit_exposure`) must never be
added to the Genie space: they materialize the graph's answers, and re-adding
them re-introduces write-back leakage and lets plain Genie tie.

CSV headers stay verbatim (camelCase), so the demo's Cypher and the UC column
names line up. Instance tables carry foreign-key columns (invoices.customerId,
revenue_entries.businessUnitId, compliance_findings.customerId,
customers.businessUnitId) so the lakehouse side can be joined on shared keys.
Re-runnable: tables are CREATE OR REPLACE and the schema/volume are created
idempotently.

Once the base tables exist they get their semantic metadata (see SEMANTICS): a
comment on every table, and a comment on the columns whose meaning cannot be read
off the name. A bare `CREATE TABLE AS SELECT *` leaves Genie nothing but names
and types. This is metadata about shape, not answers; the graph still owns the
knowledge layer. `CREATE OR REPLACE TABLE` drops comments, so the step reruns on
every upload, which also makes the whole script idempotent with no bookkeeping.

Then `create_metric_view` builds `customer_risk_exposure`, which is the real fix
for Genie multiplying customer aggregates: it declares the invoice and finding
joins `one_to_many` so each measure aggregates at its own grain.

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
    `required` names the load-bearing columns `--check` confirms are present, so
    a dropped or renamed contract column fails offline instead of at upload.
    `inferred_types` names columns that land on the right type through inference
    alone and cannot be hinted, verified against the built table instead.
    `exclude` names CSV columns to drop from the built table: they still ship in
    the CSV so the graph loader keeps them, but never reach the lakehouse.
    """

    csv_name: str
    table: str
    types: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    inferred_types: dict[str, str] = field(default_factory=dict)
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class DerivedSpec:
    """A gold table materialized from a Neo4j query."""

    table: str
    columns: list[str]
    cypher: str
    types: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TableSemantics:
    """The semantic metadata Genie reads: a table comment and column comments.

    `CREATE OR REPLACE TABLE ... AS SELECT *` leaves a table with column names
    and types and nothing else, so Genie has to guess what a row means. The table
    comment states the grain. Column comments are deliberately sparse: only
    columns whose meaning cannot be read off the name get one. Databricks' Genie
    guidance calls descriptions critical and in the same breath warns against
    unnecessary detail, and a comment restating the column name is noise
    competing with the comments that carry real information.
    """

    comment: str
    columns: dict[str, str] = field(default_factory=dict)


# The nine base instance CSVs that become UC tables. Type maps mirror the
# matching NODE_SPECS in load.py; knowledge-layer and remaining relationship
# CSVs stay graph-only. The six node tables plus supply_relationships are the
# DS-01..DS-07 rows in data_sources.csv and owned_by is DS-08; the
# supplier_business_units bridge is lakehouse-only and has no data_sources.csv
# row.
BASE_SPECS = [
    TableSpec(
        "customers.csv",
        "customers",
        {
            # defaultedPeriod is a string (inference is fine); only creditLimit
            # needs a hint so it lands DOUBLE, not string/int.
            "creditLimit": "number",
        },
        required=("creditLimit", "defaultedPeriod"),
        # Predicted labels and derived scores. They stay in customers.csv so the
        # graph loader keeps them on the Customer nodes, but they are withheld from
        # the lakehouse table: Genie reading a pre-baked judgement that carries no
        # authored definition is exactly the ungrounded shortcut the demo avoids.
        # defaultedPeriod is deliberately not dropped, the Defaulted and Delinquent
        # rules key on it.
        exclude=("churnRisk", "profitabilityTrend", "upsellScore", "avgDaysLate", "overdueShare"),
    ),
    TableSpec("suppliers.csv", "suppliers", {"riskScore": "int"}, required=("subcategory",)),
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
    TableSpec(
        "revenue_entries.csv",
        "revenue_entries",
        {"amount": "float", "reconciled": "bool"},
        # period carries YYYY-MM, which an explicit DATE schemaHint does not
        # parse; inference resolves it to a DATE on the first of the month. The
        # quarterly revenue figure in the demo rests on that, so assert it.
        inferred_types={"period": "date"},
    ),
    TableSpec("compliance_findings.csv", "compliance_findings", {"openedDate": "date"}),
    # Bridge table for the many-to-many supplier-to-business-unit link, so Genie
    # can join suppliers to the units they supply. Both columns are strings.
    TableSpec("supplier_business_units.csv", "supplier_business_units"),
    # Supplier-to-supplier link (fromSupplierId, toSupplierId), the raw edges
    # behind the graph's SUPPLIES relationship. Uploaded so plain Genie can see
    # the links in the lakehouse. Both columns are strings, so no schemaHints.
    TableSpec(
        "supply_relationships.csv",
        "supply_relationships",
        required=("fromSupplierId", "toSupplierId"),
    ),
    # Customer-to-customer ownership (child, parent, stake), the raw edges behind
    # the graph's OWNED_BY relationship. Uploaded for the same reason
    # supply_relationships is: the lakehouse-only engine is given the ownership
    # structure and the stakes in full. It still cannot answer Story 2, because
    # the answer is a weighted propagation over the whole book rather than
    # anything a join or a GROUP BY produces. The demo has to be won on the
    # question, not by withholding the table.
    TableSpec(
        "owned_by.csv",
        "owned_by",
        {"ownershipPct": "float"},
        required=("customer_id", "parent_customer_id", "ownershipPct"),
    ),
]

# Gold table: the CLASSIFIED_AS edges written back from the graph. The four
# column-findable terms are planted by the generator, each carrying rule
# provenance (reason, evaluatedAt, ruleVersion). Critical Supplier and Risky
# Customer are written by `gds.py` only after their scores resolve, which is why
# neither can be planted with the others.
#
# **Do not add a term filter here.** The graph-native rows in this table look like
# write-back leakage and are not. The gold tables are never attached to the
# Genie space, which `banned_tables` in `guard.py` enforces against the space's
# declared data sources on every run, so the lakehouse-only engine cannot read
# them. Filtering the term out instead would return the graph to the state where
# an agent asking which suppliers are critical gets zero rows and truthfully
# answers that the system does not classify them. That failure is recorded in
# the re-probe worklog. Ownership Risk still carries no edges and still
# materializes nowhere, so Story 2 has the failure this filter would recreate.
CLASSIFICATIONS_SPEC = DerivedSpec(
    table="classifications",
    columns=[
        "entity_id",
        "entity_type",
        "term",
        "reason",
        "evaluated_at",
        "rule_version",
    ],
    cypher=(
        "MATCH (e)-[r:CLASSIFIED_AS]->(t:BusinessTerm) "
        "RETURN e.id AS entity_id, labels(e)[0] AS entity_type, t.name AS term, "
        "r.reason AS reason, toString(r.evaluatedAt) AS evaluated_at, "
        "r.ruleVersion AS rule_version"
    ),
    types={"evaluated_at": "datetime"},
)

# Gold table: each business unit's aggregate supplier-risk exposure, one row per
# unit. The table reports supplier count, average, and max risk per unit, ordered
# by supplier count.
EXPOSURE_SPEC = DerivedSpec(
    table="business_unit_exposure",
    columns=[
        "business_unit_id",
        "name",
        "supplier_count",
        "avg_supplier_risk",
        "max_supplier_risk",
    ],
    cypher=(
        "MATCH (bu:BusinessUnit) "
        "OPTIONAL MATCH (s:Supplier)-[:SUPPLIES]->(bu) "
        "RETURN bu.id AS business_unit_id, bu.name AS name, "
        "count(s) AS supplier_count, round(avg(s.riskScore), 1) AS avg_supplier_risk, "
        "max(s.riskScore) AS max_supplier_risk "
        "ORDER BY supplier_count DESC"
    ),
    types={
        "supplier_count": "int",
        "avg_supplier_risk": "float",
        "max_supplier_risk": "int",
    },
)

DERIVED_SPECS = [CLASSIFICATIONS_SPEC, EXPOSURE_SPEC]

# Semantic metadata for the base tables, keyed by table name. The gold tables get
# none: they stay out of the Genie space, so nothing reads their metadata.
#
# These comments state schema facts: grain, units, join paths, and what a coded
# value means. They deliberately stop short of analysis. The demo turns on Genie
# reading every column correctly and still missing what only the graph can see,
# so a comment that hints at a traversal or pre-judges what a metric implies
# would hand over the answer and break the premise.
#
# A column earns a comment only if its meaning cannot be read off its name. That
# leaves three kinds: coded vocabularies (segment, status, region), units and
# scales (EUR amounts, 0-100 scores), and grain rules. "Registered customer name"
# is not a comment, it is the column name with extra words, and every one of
# those dilutes the ones that matter.
#
# Three observed failures set the emphasis, and every comment that survives past
# a bare definition is here because one of them happened. Genie rendered euro
# amounts with a dollar sign, so every amount and currency column says EUR
# outright rather than leaving it a SELECT DISTINCT away. Genie multiplied
# customer aggregates by joining two one-to-many branches at once, so the branch
# tables name their grain; the customer_risk_exposure metric view is the real
# defense there. And Genie answered a regional supplier question globally, so
# suppliers and supplier_business_units carry the bridge join path.
#
# The leak test is directional, and it is narrower than "no analysis". A comment
# that helps Genie read the lakehouse is the fairness rule working: the demo
# needs Run A sharp, because Run A looking incompetent breaks the premise just
# as badly as Run A winning. What must never appear is a comment carrying
# something only the graph should know: a traversal that walks tiers to a hidden
# source, a term that pre-labels a supplier critical, or an example list that
# points at the story's commodities. So: does this help Genie read a column, or
# does it hand over the finding?
#
# Two things were cut under that test. The subcategory comment used to give
# "glass bottles, raw glass" as examples, naming Story 1's commodity and its
# punchline out of a fifteen-value vocabulary. And several status columns used
# to append what the value implies ("only open rows are live exposure") rather
# than what it is.
SEMANTICS: dict[str, TableSemantics] = {
    "customers": TableSemantics(
        comment=(
            "One row per customer. Invoices hang off this table as a one-to-many "
            "branch; aggregate them to customer grain before joining to another "
            "customer-grain table."
        ),
        columns={
            "segment": "Commercial tier: platinum, gold, or silver.",
            "creditLimit": "Total committed credit facility in EUR.",
            "defaultedPeriod": (
                "Quarter in which the customer recorded a default, format YYYY-Qn. "
                "Null if the customer has never defaulted."
            ),
        },
    ),
    "suppliers": TableSemantics(
        comment=(
            "One row per supplier. Has no business unit column: a supplier serves "
            "many units and a unit uses many suppliers, so scope any supplier "
            "question to a region or unit through the supplier_business_units "
            "bridge."
        ),
        columns={
            "category": "Procurement category: ingredients, packaging, logistics, equipment, or services.",
            "subcategory": "Specialty within the category.",
            "riskScore": "Procurement risk score, 0-100, higher is riskier.",
        },
    ),
    "business_units": TableSemantics(
        comment="One row per business unit.",
        columns={
            "region": (
                "Region code: AMER is the Americas, EMEA is Europe, Middle East and "
                "Africa, APAC is Asia Pacific."
            ),
        },
    ),
    "invoices": TableSemantics(
        comment=(
            "One row per invoice, many per customer. Aggregate to customer grain "
            "before joining to another customer-grain table."
        ),
        columns={
            "amount": "Invoice amount in EUR.",
            "currency": "ISO 4217 currency code. Every amount in this dataset is EUR; render amounts with the euro symbol.",
            "daysLate": "Days between dueDate and payment.",
            "status": "Lifecycle state: paid, open, or overdue.",
        },
    ),
    "revenue_entries": TableSemantics(
        comment="One row per business unit per accounting period.",
        columns={
            "period": (
                "Accounting month, stored as a DATE on the first of the month. "
                "Derive quarters with YEAR and QUARTER."
            ),
            "amount": "Recognized revenue in EUR.",
            "currency": "ISO 4217 currency code. Every amount in this dataset is EUR; render amounts with the euro symbol.",
        },
    ),
    "compliance_findings": TableSemantics(
        comment="One row per compliance finding, many per customer.",
        columns={
            "type": "Finding category: KYC, AML, or sanctions.",
            "status": "Finding state: open or closed.",
        },
    ),
    "supplier_business_units": TableSemantics(
        comment=(
            "Many-to-many bridge mapping which suppliers serve which business "
            "units. Suppliers and business_units share no column, so route through "
            "this table to scope a supplier question to a region or unit. One row "
            "per supplier-unit pair."
        ),
    ),
    "supply_relationships": TableSemantics(
        comment=(
            "One row per supplier-to-supplier supply link. The supplier in "
            "fromSupplierId supplies the supplier in toSupplierId; both sides join "
            "to suppliers.id. A supplier can appear on either side, or on both."
        ),
    ),
    "owned_by": TableSemantics(
        comment=(
            "One row per ownership stake between customers. The customer in "
            "customer_id is owned by the customer in parent_customer_id, and "
            "ownershipPct is the fraction held, from 0 to 1. Both sides join to "
            "customers.id. A customer can have more than one owner, so this is not "
            "a single parent column."
        ),
    ),
}


# The metric view over customer risk exposure. `customers` has two independent
# one-to-many branches hanging off it, invoices and compliance_findings, and
# joining both in one pass multiplies each by the other's row count: a customer's
# open exposure comes back multiplied by its finding count, and its finding count
# multiplied by its invoice count. Genie did exactly this against the raw tables
# and reported both wrong. `cardinality: one_to_many` makes each measure aggregate
# at its own source grain, so the fanout stops being a thing a query can express
# rather than a thing a comment warns about.
#
# No worked example is given here on purpose. The dataset regenerates from today's
# date, so any customer named with concrete figures goes stale on the next run.
# To check the fanout by hand, pick a customer off the live data that has BOTH a
# nonzero open exposure and two or more open compliance findings — both branches
# have to be non-empty or there is nothing to multiply — then compare the metric
# view's open_exposure_amount and open_finding_count against the same two figures
# computed one branch at a time. Against the raw tables the single-pass join
# returns each measure scaled by the other branch's row count; through the metric
# view the two agree.
#
# __SCHEMA__ is replaced with the backtick-quoted catalog.schema at build time.
# Plain str.format is unusable here because the YAML `format:` blocks contain
# literal braces. The token is underscore-delimited so the replace cannot collide
# with the prose in the comment and synonym fields below.
METRIC_VIEW_NAME = "customer_risk_exposure"

SCHEMA_TOKEN = "__SCHEMA__"

METRIC_VIEW_YAML = """
version: 1.1
comment: "Per-customer risk and exposure. One row per customer. Invoice and compliance measures aggregate at their own grain, so combining them never fans out."
source: '__SCHEMA__.`customers`'

joins:
  - name: business_unit
    source: '__SCHEMA__.`business_units`'
    'on': source.businessUnitId = business_unit.id
    rely:
      at_most_one_match: true
  - name: invoices
    source: '__SCHEMA__.`invoices`'
    'on': invoices.customerId = source.id
    cardinality: one_to_many
  - name: findings
    source: '__SCHEMA__.`compliance_findings`'
    'on': findings.customerId = source.id
    cardinality: one_to_many

fields:
  - name: customer_name
    expr: source.name
    display_name: "Customer"
    synonyms: ['customer', 'client', 'account name']
  - name: customer_id
    expr: source.id
  - name: segment
    expr: source.segment
    display_name: "Segment"
    synonyms: ['tier', 'customer segment']
  - name: defaulted_period
    expr: source.defaultedPeriod
    display_name: "Defaulted Period"
  - name: business_unit_name
    expr: business_unit.name
    display_name: "Business Unit"
    synonyms: ['BU', 'unit']
  - name: region
    expr: business_unit.region
    display_name: "Region"
    synonyms: ['geo', 'territory']

measures:
  - name: customer_count
    expr: COUNT(1)
    display_name: "Customers"
    synonyms: ['number of customers', 'customer count']
  - name: open_exposure_amount
    expr: COALESCE(SUM(CASE WHEN invoices.status <> 'paid' THEN invoices.amount END), 0)
    display_name: "Open Exposure (EUR)"
    comment: "Amount on invoices not yet paid (status open or overdue). Excludes paid invoices."
    synonyms: ['open exposure', 'outstanding balance', 'unpaid amount', 'amount at risk']
    format: {type: currency, currency_code: EUR, decimal_places: {type: exact, places: 2}}
  - name: overdue_amount
    expr: COALESCE(SUM(CASE WHEN invoices.status = 'overdue' THEN invoices.amount END), 0)
    display_name: "Overdue Amount (EUR)"
    comment: "Amount on invoices with status overdue."
    synonyms: ['overdue', 'past due amount', 'arrears']
    format: {type: currency, currency_code: EUR, decimal_places: {type: exact, places: 2}}
  - name: open_invoice_count
    expr: COUNT(CASE WHEN invoices.status <> 'paid' THEN invoices.id END)
    display_name: "Open Invoices"
    comment: "Count of invoices not yet paid (open plus overdue)."
    synonyms: ['unpaid invoices', 'outstanding invoices']
  - name: overdue_invoice_count
    expr: COUNT(CASE WHEN invoices.status = 'overdue' THEN invoices.id END)
    display_name: "Overdue Invoices"
  - name: invoice_count
    expr: COUNT(invoices.id)
    display_name: "Total Invoices"
  - name: total_invoiced_amount
    expr: COALESCE(SUM(invoices.amount), 0)
    display_name: "Total Invoiced (EUR)"
    comment: "All invoiced amount regardless of status."
    synonyms: ['total invoiced', 'gross billings', 'total billed']
    format: {type: currency, currency_code: EUR, decimal_places: {type: exact, places: 2}}
  - name: open_finding_count
    expr: COUNT(CASE WHEN findings.status = 'open' THEN findings.id END)
    display_name: "Open Compliance Findings"
    comment: "Compliance findings with status open. Independent of invoice grain."
    synonyms: ['open findings', 'unresolved findings', 'compliance issues']
  - name: finding_count
    expr: COUNT(findings.id)
    display_name: "Total Compliance Findings"
  - name: credit_limit
    expr: COALESCE(SUM(source.creditLimit), 0)
    display_name: "Credit Limit (EUR)"
    format: {type: currency, currency_code: EUR, decimal_places: {type: exact, places: 2}}
  - name: credit_utilization
    expr: COALESCE(SUM(CASE WHEN invoices.status <> 'paid' THEN invoices.amount END), 0) / NULLIF(SUM(source.creditLimit), 0)
    display_name: "Credit Utilization"
    comment: "Open exposure divided by credit limit. Ratio of two independently-grained aggregates."
    format: {type: percentage, decimal_places: {type: exact, places: 1}}
"""


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
    """Read one env var, falling back to `default`, or exit with a usage hint.

    The `or` rather than a two-argument `os.environ.get` is deliberate: an empty
    string in .env is a variable someone left blank, not a value, so it falls
    through to the default the same way an absent one does.
    """
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def read_config() -> Config:
    """Read connection settings from the environment (.env already loaded).

    The two Databricks auth modes are exclusive. A profile names an entry in
    ~/.databrickscfg that already carries a host and credentials, so host and
    token are left unset rather than demanded and ignored; without a profile both
    are required and a missing one exits here rather than at the first API call.
    """
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
    """Read a CSV into row dicts, values left as strings.

    Only `--check` uses this. The upload path never parses the CSVs in Python: it
    ships the bytes to the volume and lets `read_files` do the typing, so this
    reader exists to inspect headers offline, not to feed the tables.
    """
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def schema_hints(types: dict[str, str]) -> str | None:
    """Render a read_files schemaHints clause from a type map, or None.

    Hints are per-column and partial: a column named here is forced to the given
    type and every other column still goes through inference. None rather than an
    empty string so `create_table` can leave the option off entirely for the
    all-string tables.
    """
    if not types:
        return None
    return ", ".join(f"{column} {SPARK_TYPES[kind]}" for column, kind in types.items())


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    """Serialize query rows to CSV bytes; None becomes an empty field.

    `columns` fixes the field order rather than trusting the order the driver
    returns, so the built table's columns match the DerivedSpec that declared
    them. A null property in Neo4j writes as an empty field, which `read_files`
    then reads back as NULL.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(column) is None else row[column] for column in columns])
    return buffer.getvalue().encode("utf-8")


def volume_path(cfg: Config, filename: str) -> str:
    """The /Volumes path a CSV is uploaded to and read back from.

    Unlike `fqn`, this is a filesystem path rather than an identifier, so the
    hyphenated catalog name needs no quoting.
    """
    return f"/Volumes/{cfg.catalog}/{cfg.schema}/{cfg.volume}/{filename}"


def fqn(cfg: Config, table: str) -> str:
    """Backtick-quoted catalog.schema.table (the catalog name has hyphens)."""
    return f"`{cfg.catalog}`.`{cfg.schema}`.`{table}`"


def run_sql(w: Any, cfg: Config, statement: str) -> Any:
    """Execute one SQL statement on the warehouse, polling until it finishes.

    `wait_timeout` is the API's own maximum, so a fast statement returns
    finished from the first call and the loop never runs. The poll covers the
    slow cases: a warehouse cold-starting, or a CREATE TABLE over a volume file
    that outlasts the wait. Anything other than SUCCEEDED raises, so a failed
    statement stops the upload instead of leaving a half-built schema behind.

    The SDK import is deferred to keep `--check` runnable with no databricks-sdk
    installed and no network.
    """
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
    """Row count of a built table, read back so the run reports what landed.

    Counting the table rather than the CSV catches a load that silently dropped
    rows, which the printed count would otherwise hide.
    """
    response = run_sql(w, cfg, f"SELECT count(*) FROM {fqn(cfg, table)}")
    return int(response.result.data_array[0][0])


def ensure_schema_and_volume(w: Any, cfg: Config) -> None:
    """Create the target schema and volume if they are not already there.

    Both are IF NOT EXISTS, so this is the first half of the script's
    re-runnability: a fresh workspace and a workspace loaded ten times take the
    same path. The catalog is not created here; it is assumed to exist.
    """
    run_sql(w, cfg, f"CREATE SCHEMA IF NOT EXISTS `{cfg.catalog}`.`{cfg.schema}`")
    run_sql(
        w,
        cfg,
        f"CREATE VOLUME IF NOT EXISTS `{cfg.catalog}`.`{cfg.schema}`.`{cfg.volume}`",
    )
    print(f"Ensured schema `{cfg.catalog}`.`{cfg.schema}` and volume `{cfg.volume}`.")


def create_table(
    w: Any,
    cfg: Config,
    table: str,
    filename: str,
    hints: str | None,
    exclude: tuple[str, ...] = (),
) -> None:
    """Build a Delta table from a CSV already uploaded to the volume.

    `read_files` always appends a `_rescued_data` column for values that did not
    match the inferred schema. It is null on every row here, but Genie reads it as
    a real column and the space had prompt matching switched on for it, so drop it
    rather than ship a column whose only effect is noise in the schema.

    `exclude` names CSV columns to project out of the table. They are still parsed
    by `read_files`, so the same CSV keeps feeding the graph loader, and dropped
    from the SELECT so they never land in the lakehouse.
    """
    options = ["format => 'csv'", "header => true", "inferColumnTypes => true"]
    if hints:
        options.append(f"schemaHints => '{hints}'")
    dropped = ", ".join(("_rescued_data", *exclude))
    run_sql(
        w,
        cfg,
        f"CREATE OR REPLACE TABLE {fqn(cfg, table)} AS "
        f"SELECT * EXCEPT ({dropped}) "
        f"FROM read_files('{volume_path(cfg, filename)}', {', '.join(options)})",
    )


def upload_csv(w: Any, cfg: Config, filename: str, contents: bytes) -> None:
    """Write CSV bytes to the volume, replacing any file already at that path.

    `overwrite` is what lets a rerun pick up a regenerated dataset. Without it a
    second run would keep the first run's file and build tables from stale rows.
    """
    w.files.upload(volume_path(cfg, filename), io.BytesIO(contents), overwrite=True)


def sql_string(value: str) -> str:
    """Render a Python string as a single-quoted SQL string literal.

    Backslash is an escape character inside Spark SQL string literals, so it has
    to be doubled before the quotes are, or a comment containing one would either
    swallow the next character or fail to parse.
    """
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def apply_comments(w: Any, cfg: Config, table: str, semantics: TableSemantics) -> None:
    """Attach one table's comment and its column comments.

    One statement per comment, because Databricks has no batched form. The column
    loop only visits columns SEMANTICS names, so a comment for a column the CSV
    no longer has would fail here; `check_semantics` catches that offline first.
    """
    target = fqn(cfg, table)
    run_sql(w, cfg, f"COMMENT ON TABLE {target} IS {sql_string(semantics.comment)}")
    for column, comment in semantics.columns.items():
        run_sql(
            w,
            cfg,
            f"ALTER TABLE {target} ALTER COLUMN `{column}` "
            f"COMMENT {sql_string(comment)}",
        )


def apply_semantics(w: Any, cfg: Config) -> None:
    """Attach the table and column comments to the base tables.

    Runs after upload_base_tables because CREATE OR REPLACE TABLE drops comments,
    so they have to be reapplied on every run.

    There are deliberately no primary or foreign key constraints here. They were
    tried, as the hypothesized fix for Genie multiplying customer aggregates
    across two one-to-many branches, and the customer_risk_exposure metric view
    turned out to be what actually fixes that, structurally. Databricks' Genie
    guidance ranks descriptions, metric views, and example SQL as the levers that
    matter and does not mention constraints at all, so declaring 8 primary and 9
    foreign keys was 44 statements of unvalidated ceremony on a 4,289-row demo.
    """
    print("Applying semantic metadata:")
    for spec in BASE_SPECS:
        semantics = SEMANTICS[spec.table]
        apply_comments(w, cfg, spec.table, semantics)
        print(
            f"  {spec.table}: table comment, {len(semantics.columns)} column comments"
        )


def create_metric_view(w: Any, cfg: Config) -> None:
    """Build the customer-exposure metric view over the freshly loaded tables.

    Runs after apply_semantics for the same reason that step exists: the base
    tables are CREATE OR REPLACE, so anything defined on top of them has to be
    rebuilt each run.
    """
    schema = f"`{cfg.catalog}`.`{cfg.schema}`"
    yaml = METRIC_VIEW_YAML.replace(SCHEMA_TOKEN, schema)
    run_sql(
        w,
        cfg,
        f"CREATE OR REPLACE VIEW {fqn(cfg, METRIC_VIEW_NAME)} "
        f"WITH METRICS LANGUAGE YAML AS $${yaml}$$",
    )
    print(f"Built metric view {METRIC_VIEW_NAME} (fanout-free customer exposure).")


def upload_base_tables(w: Any, cfg: Config, data_dir: Path) -> list[tuple[str, int]]:
    """Upload every base CSV and build its Delta table, returning (table, rows).

    The CSV is read straight to bytes and handed to the volume without being
    parsed here, so the header stays verbatim and camelCase survives into the
    column names. Comments and the metric view are applied afterwards, because
    CREATE OR REPLACE TABLE inside `create_table` would drop them.
    """
    print("Uploading base instance tables:")
    results = []
    for spec in BASE_SPECS:
        upload_csv(w, cfg, spec.csv_name, (data_dir / spec.csv_name).read_bytes())
        create_table(w, cfg, spec.table, spec.csv_name, schema_hints(spec.types), spec.exclude)
        rows = count_rows(w, cfg, spec.table)
        results.append((spec.table, rows))
        print(f"  {spec.table}: {rows} rows")
    return results


def verify_inferred_types(w: Any, cfg: Config) -> None:
    """Confirm the columns that rely on type inference landed on the right type.

    `schemaHints` is the fix wherever it works, and `types` uses it. It does not
    work for revenue_entries.period: the CSV carries YYYY-MM, an explicit DATE
    hint does not parse that, and the DATE the column becomes is inference's
    doing. Story 1's quarterly revenue figure depends on it, and a silent drift
    to STRING would surface as a wrong number on stage rather than an error here.
    """
    expected = [
        (spec.table, column, SPARK_TYPES[kind].lower())
        for spec in BASE_SPECS
        for column, kind in spec.inferred_types.items()
    ]
    if not expected:
        return
    for table, column, kind in expected:
        response = run_sql(
            w,
            cfg,
            "SELECT full_data_type FROM "
            f"`{cfg.catalog}`.information_schema.columns "
            f"WHERE table_schema = {sql_string(cfg.schema)} "
            f"AND table_name = {sql_string(table)} "
            f"AND column_name = {sql_string(column)}",
        )
        rows = response.result.data_array or []
        actual = rows[0][0].lower() if rows else "absent"
        if actual != kind:
            raise RuntimeError(
                f"{table}.{column}: inference produced {actual}, expected {kind}"
            )
    print(f"Verified {len(expected)} inferred column type(s).")


def read_graph_rows(cfg: Config, cypher: str) -> list[dict[str, Any]]:
    """Run one read query against Neo4j and return the rows as dicts.

    The result set is materialized inside the session because the driver's
    records are only valid while it is open. Both gold tables are small enough
    that holding them in memory costs nothing. As with the SDK, the neo4j import
    is deferred so `--check` runs without the driver installed.
    """
    from neo4j import GraphDatabase

    with GraphDatabase.driver(cfg.neo4j_uri, auth=cfg.neo4j_auth) as driver:
        driver.verify_connectivity()
        with driver.session(database=cfg.neo4j_database) as session:
            return [record.data() for record in session.run(cypher)]


def upload_derived_table(w: Any, cfg: Config, spec: DerivedSpec) -> int:
    """Query the graph, stage the answer as a CSV, and build the gold table.

    The round trip through a volume CSV is what keeps this identical to the base
    path: same `read_files` call, same schemaHints mechanism, one way that a
    table in this schema comes into being.
    """
    rows = read_graph_rows(cfg, spec.cypher)
    filename = f"{spec.table}.csv"
    upload_csv(w, cfg, filename, rows_to_csv(spec.columns, rows))
    create_table(w, cfg, spec.table, filename, schema_hints(spec.types))
    count = count_rows(w, cfg, spec.table)
    print(f"  {spec.table}: {count} rows")
    return count


def check_semantics(spec: TableSpec, header: set[str]) -> None:
    """Offline: confirm this table's comments still match its CSV.

    Comments are written by column name, so a renamed or dropped column would
    otherwise fail mid-upload as a SQL error. There is no converse check that
    every column carries a comment: most deliberately do not.
    """
    semantics = SEMANTICS.get(spec.table)
    if semantics is None:
        sys.exit(f"{spec.table}: no SEMANTICS entry; add one before uploading.")
    if ghosts := sorted(set(semantics.columns) - header):
        sys.exit(f"{spec.table}: comments name absent column(s) {', '.join(ghosts)}")


def check(data_dir: Path) -> None:
    """Offline: confirm the base CSVs read, carry their load-bearing columns and
    matching comments, and report the row counts."""
    print(f"Validating base CSVs in {data_dir}:")
    total = 0
    for spec in BASE_SPECS:
        path = data_dir / spec.csv_name
        if not path.is_file():
            sys.exit(f"Missing CSV: {path}")
        rows = read_csv(path)
        header = set(rows[0]) if rows else set()
        expected = set(spec.types) | set(spec.required) | set(spec.inferred_types)
        missing = sorted(expected - header)
        if missing:
            sys.exit(f"{spec.csv_name}: missing column(s) {', '.join(missing)}")
        check_semantics(spec, header)
        total += len(rows)
        print(f"  {spec.table}: {len(rows)} rows ({spec.csv_name})")
    print(f"Check passed: {len(BASE_SPECS)} base tables, {total} rows ready to upload.")
    print(
        f"Derived tables read from Neo4j at upload time: "
        f"{', '.join(spec.table for spec in DERIVED_SPECS)}."
    )


def main() -> None:
    """Parse arguments and run either the offline check or the full upload.

    The upload order is not arbitrary. Schema and volume come first because
    everything else writes into them; base tables next; type verification
    immediately after, so a drifted column fails before anything is built on top
    of it; then comments and the metric view, both of which CREATE OR REPLACE
    TABLE would have discarded had they been applied earlier. Gold tables come
    last because they depend on Neo4j rather than on anything above them, so a
    graph that is down does not cost the lakehouse work already done.
    """
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
    verify_inferred_types(w, cfg)
    apply_semantics(w, cfg)
    create_metric_view(w, cfg)

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

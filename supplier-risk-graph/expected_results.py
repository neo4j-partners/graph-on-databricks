"""Render the presenter's expected-results table from data/ground_truth.json.

The demo data is regenerated from today's date on purpose: generate_data.py
defaults its as-of date to date.today() because the demo shows forward-looking
risk. That splits the dataset in two.

  - Seed-stable. Entity names, IDs and supplier risk scores come from the fixed
    seed and are the same on every run. A presenter can memorize these.
  - Date-derived. Every euro amount, revenue figure, invoice and finding count,
    quarter label and exposure number is computed from the as-of date and moves
    on every run. Nobody can know these in advance.

This table exists for the second half. Run it after `make demo` and the figures
a presenter has to confirm on stage are on one screen, read out of the same
ground_truth.json that generate_data.py wrote and gds.py reads back.

Every value is read from the JSON; nothing is hardcoded. ROWS declares the
label, units and date-sensitivity of each figure, and `check_coverage` fails if
the file carries a value no row accounts for, so a schema change surfaces here
rather than as a figure quietly missing from the table.

Usage:
    uv run expected_results.py                    # render data/ground_truth.json
    uv run expected_results.py --data-dir other/  # render another build

Reads a file. Touches neither Neo4j nor Databricks.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

# Width of the value column before it wraps onto continuation lines.
VALUE_WIDTH = 58

# Marker on figures that move with the as-of date.
VARIES_MARK = "*"


@dataclass(frozen=True)
class Row:
    """One line of the table: where the value lives and how to render it.

    `path` is the dotted key path into ground_truth.json. It may point at a
    scalar, at a list of ids, or at a dict of id-to-score; `render` handles all
    three. `varies` marks the date-derived figures, the ones worth reading off
    this table rather than off a rehearsal. `unit` is "eur" for the euro
    amounts and "" otherwise.
    """

    label: str
    path: str
    varies: bool = False
    unit: str = ""


@dataclass(frozen=True)
class Section:
    """A titled group of rows."""

    title: str
    rows: tuple[Row, ...]


# The full contents of ground_truth.json, in presenter order. Marked `varies`
# where the figure is computed from the as-of date: the amounts, the counts
# that follow from generated invoices and findings, the quarter labels, and the
# cohorts whose membership turns on invoice lateness. Everything else falls out
# of the fixed seed and is identical on every build.
SECTIONS = (
    Section(
        "Build",
        (
            Row("As-of date", "as_of_date", varies=True),
            Row("Seed", "seed"),
            Row("Ground-truth schema version", "schema_version"),
        ),
    ),
    Section(
        "Row counts",
        (
            Row("Customers", "summary.customers"),
            Row("Suppliers", "summary.suppliers"),
            Row("Business units", "summary.business_units"),
            Row("Invoices", "summary.invoices", varies=True),
            Row("Revenue entries", "summary.revenue_entries"),
            Row("Compliance findings", "summary.compliance_findings", varies=True),
            Row("Supply relationships", "summary.supply_relationships"),
            Row("Ownership edges", "summary.owned_by_edges"),
        ),
    ),
    Section(
        "Story 1 - the hidden glassworks",
        (
            Row("Cascade (the choke point)", "story1_hidden_glassworks.cascade_id"),
            Row("Cascade risk score", "story1_hidden_glassworks.cascade_risk_score"),
            Row("Tier-1 suppliers it feeds", "story1_hidden_glassworks.tier1_ids"),
            Row("Tier-1 risk scores", "story1_hidden_glassworks.tier1_risk_scores"),
            Row("Business unit at stake", "story1_hidden_glassworks.business_unit"),
            Row("Last full quarter", "story1_hidden_glassworks.last_quarter", varies=True),
            Row(
                "That quarter's BU-03 revenue",
                "story1_hidden_glassworks.bu03_last_quarter_revenue",
                varies=True,
                unit="eur",
            ),
        ),
    ),
    Section(
        "Story 2 - the clean payer in a bad group",
        (
            Row("Group parent (Kestrel)", "story2_clean_payer.kestrel_id"),
            Row("The clean payer (Jade)", "story2_clean_payer.jade_id"),
            Row("Kestrel group", "story2_clean_payer.group_ids"),
            Row("Defaults inside the group", "story2_clean_payer.kestrel_default_ids"),
            Row("PageRank seed set (all defaults)", "story2_clean_payer.seed_ids"),
            Row("Defaulted quarter", "story2_clean_payer.defaulted_period", varies=True),
            Row(
                "Jade open invoice balance",
                "story2_clean_payer.jade_open_invoice_balance",
                varies=True,
                unit="eur",
            ),
            Row(
                "Jade credit limit",
                "story2_clean_payer.jade_credit_limit",
                unit="eur",
            ),
            Row(
                "Jade exposure",
                "story2_clean_payer.jade_exposure",
                varies=True,
                unit="eur",
            ),
        ),
    ),
    Section(
        "Classification cohorts",
        (
            Row("High-Risk Supplier", "classification_cohorts.high_risk_suppliers"),
            Row(
                "Delinquent Customer",
                "classification_cohorts.delinquent_customers",
                varies=True,
            ),
            Row("Strategic Account", "classification_cohorts.strategic_accounts"),
            Row("Defaulted Customer", "classification_cohorts.defaulted_customers"),
            # Planted payment behaviour, not a planted classification, so this is
            # the one row here that does not name a cohort the graph will return.
            # The Risky Customer cohort is resolved by gds.py from the scored
            # neighbourhoods and is deliberately not the same set: it catches
            # customers nobody planted and misses planted ones that came in under
            # the governed share. Read the cohort off the gds.py output, not here.
            Row(
                "Near-miss payment behaviour (planted)",
                "classification_cohorts.near_miss_customers",
                varies=True,
            ),
        ),
    ),
)


def resolve(data: dict[str, Any], path: str) -> Any:
    """Follow a dotted key path into the loaded JSON."""
    value: Any = data
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            sys.exit(f"ground_truth.json: no value at {path}")
        value = value[key]
    return value


def leaf_paths(value: Any, prefix: str = "") -> list[str]:
    """Every scalar path in the JSON, dotted, with list items indexed."""
    if isinstance(value, dict):
        return [
            path
            for key, item in value.items()
            for path in leaf_paths(item, f"{prefix}.{key}" if prefix else key)
        ]
    if isinstance(value, list):
        return [
            path
            for index, item in enumerate(value)
            for path in leaf_paths(item, f"{prefix}[{index}]")
        ]
    return [prefix]


def check_coverage(data: dict[str, Any]) -> None:
    """Fail if the file holds a value no row in SECTIONS accounts for.

    A row covers its own path and everything beneath it, so one row covers a
    whole id list or score map. What it will not do is silently skip a key
    someone adds to ground_truth.json later: the presenter would just never see
    that figure, which is the one failure mode this table cannot afford.
    """
    declared = [row.path for section in SECTIONS for row in section.rows]
    orphans = sorted(
        path
        for path in leaf_paths(data)
        if not any(path == d or path.startswith(f"{d}.") or path.startswith(f"{d}[")
                   for d in declared)
    )
    if orphans:
        sys.exit(
            "ground_truth.json carries value(s) no row renders: "
            f"{', '.join(orphans)}. Add them to SECTIONS in expected_results.py."
        )


def render(value: Any, unit: str) -> str:
    """Render one value: a euro amount, an id list, a score map, or a scalar."""
    if isinstance(value, dict):
        return ", ".join(f"{key} {render(item, unit)}" for key, item in value.items())
    if isinstance(value, list):
        return f"{len(value)}: {', '.join(str(item) for item in value)}"
    if unit == "eur":
        return f"EUR {value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def print_section(section: Section, data: dict[str, Any], label_width: int) -> None:
    print(f"\n{section.title}")
    print("-" * (label_width + VALUE_WIDTH + 5))
    for row in section.rows:
        mark = VARIES_MARK if row.varies else " "
        text = render(resolve(data, row.path), row.unit)
        lines = textwrap.wrap(text, VALUE_WIDTH) or [""]
        print(f"{mark} {row.label:<{label_width}}  {lines[0]}")
        for line in lines[1:]:
            print(f"  {'':<{label_width}}  {line}")


def print_table(data: dict[str, Any]) -> None:
    label_width = max(
        len(row.label) for section in SECTIONS for row in section.rows
    )
    print("Expected results for this build of the supplier-risk-graph demo")
    print(f"Source: ground_truth.json, as-of {data['as_of_date']}")
    for section in SECTIONS:
        print_section(section, data, label_width)
    print(
        f"\n{VARIES_MARK} moves with the as-of date and is different on every "
        "build. Unmarked\n  figures come from the fixed seed and are the same "
        "every time."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="directory holding ground_truth.json (default: data/)",
    )
    args = parser.parse_args()

    path = args.data_dir / "ground_truth.json"
    if not path.is_file():
        sys.exit(f"Missing {path}: run `make data` (or uv run generate_data.py) first.")
    data = json.loads(path.read_text())

    check_coverage(data)
    print_table(data)


if __name__ == "__main__":
    main()

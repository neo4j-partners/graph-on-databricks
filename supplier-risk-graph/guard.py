"""The vocabulary guard: proves no authored artifact is visible to Run A.

CONTRACT.md section 1 states the demo's load-bearing claim: no Run A answer
cites a governed business definition, because none exists in the lakehouse.
That claim is true by construction, but only while it stays true by
construction. The moment a term name, a rule name, or a TERM-/RULE-/MEAS-/THR-/
GM- identifier reaches a Unity Catalog comment or a Genie space instruction,
Run A can cite an authored definition and the claim is gone. Section 7 asserts
against exactly that, and this file is the assert.

Four surfaces can leak one: Unity Catalog table names, column names, table
comments, and column comments, plus the Genie space text instructions and its
example SQL. All six are checked here.

Why this is a standalone script and not a flag on upload.py. The Genie space is
hand-synced through the manage_genie MCP tool, so anyone who edits the space
between the build and the demo reintroduces a leak with nothing to catch it.
The guard therefore runs twice: once during the rebuild, and once in pre-flight
on the day, after everything else has passed. A pre-flight check must not
require loading a module whose ordinary behavior replaces tables, and must not
demand Neo4j credentials it has no use for, which is why the connection config
here is its own smaller thing rather than upload.py's.

What this catches and what it does not. A literal leak, always. A paraphrase,
never: a comment reading "suppliers that bridge many supply paths matter most"
passes every check here and still hands over the finding. The editorial rule in
upload.py stays the human review for that, and the two are not interchangeable.

Usage:
    uv run guard.py             # live: Unity Catalog and the Genie space
    uv run guard.py --offline   # authored comments in upload.py, no credentials

Exit status is 0 when clean and 1 when anything leaked, so it can gate a build.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent

# The Story 1 Genie space. Overridable so the guard can be pointed at a rebuilt
# or duplicated space without editing code.
DEFAULT_GENIE_SPACE_ID = "01f17a8bf82813d38c45162703c92a01"

POLL_INTERVAL = 2.0


# --- What counts as a leak -------------------------------------------------
#
# The identifier pattern is anchored on the digits so that "GM-" cannot fire on
# ordinary prose. The name patterns are word-bounded and case-insensitive: a
# comment saying "critical supplier" in lower case is the same leak as one
# saying it in title case.

IDENTIFIER_PATTERN = re.compile(r"\b(?:TERM|RULE|MEAS|THR|GM)-\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class Leak:
    """One governed string found on one surface Run A can read."""

    surface: str
    location: str
    found: str
    excerpt: str

    def render(self) -> str:
        return (
            f"  {self.surface}: {self.location}\n"
            f"    found: {self.found}\n"
            f"    in:    {self.excerpt}"
        )


def governed_vocabulary() -> list[str]:
    """Every governed name the knowledge layer defines.

    Read from the generator rather than restated here, so a new term or measure
    is covered by this guard the moment it is authored. CONTRACT.md section 1
    enumerates term names, rule names, and the five identifier prefixes; the
    measure, threshold, and graph-metric names are included too because a
    comment reading "Supply Exposure" hands Run A an authored definition just as
    squarely as one reading "Critical Supplier", and section 1's intent is the
    governed vocabulary rather than that specific list of three.
    """
    import generate_data as g

    names: list[str] = []
    for row in g.BUSINESS_TERMS:
        names.append(row["name"])
    for row in g.BUSINESS_RULES:
        names.append(row["name"])
    for row in g.MEASURES:
        names.append(row["name"])
    for row in g.THRESHOLDS:
        names.append(row["name"])
    for row in g.GRAPH_METRICS:
        names.append(row["name"])
    # Longest first, so a report names "Critical Supplier Rule" rather than the
    # "Critical Supplier" nested inside it.
    return sorted(set(names), key=len, reverse=True)


def commodity_subcategories() -> dict[str, set[str]]:
    """The authored commodity grouping, which is a leak in its own right."""
    import generate_data as g

    return {name: set(values) for name, values in g.COMMODITY_SUBCATEGORIES.items()}


def excerpt(text: str, match_start: int, match_end: int, width: int = 60) -> str:
    """A readable window around a hit, so a failure is actionable."""
    start = max(0, match_start - width // 2)
    end = min(len(text), match_end + width // 2)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def scan_vocabulary(
    text: str | None, surface: str, location: str, names: list[str]
) -> list[Leak]:
    """Governed names and identifiers appearing literally in one string."""
    if not text:
        return []
    leaks: list[Leak] = []
    for match in IDENTIFIER_PATTERN.finditer(text):
        leaks.append(
            Leak(surface, location, match.group(0), excerpt(text, *match.span()))
        )
    for name in names:
        pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            leaks.append(Leak(surface, location, name, excerpt(text, *match.span())))
    return leaks


def scan_commodity_grouping(
    text: str | None,
    surface: str,
    location: str,
    commodities: dict[str, set[str]],
) -> list[Leak]:
    """Two or more members of one commodity named together.

    The extension CONTRACT.md's vocabulary assert does not cover. The grouping
    carries no governed identifier, so the scan above passes it, and yet a
    comment listing "raw glass, glass bottles" hands over the traversal filter
    that scopes Supply Exposure. One member on its own is instance data and
    fine: 'glass bottles' is a value in a column Run A can already read. It is
    the enumeration that is the authored judgment.
    """
    if not text:
        return []
    leaks: list[Leak] = []
    for commodity, values in commodities.items():
        present = sorted(
            value
            for value in values
            if re.search(rf"\b{re.escape(value)}\b", text, re.IGNORECASE)
        )
        if len(present) >= 2:
            leaks.append(
                Leak(
                    surface,
                    location,
                    f"{commodity} grouping: {', '.join(present)}",
                    excerpt(text, 0, min(len(text), 80)),
                )
            )
    return leaks


def scan(
    text: str | None,
    surface: str,
    location: str,
    names: list[str],
    commodities: dict[str, set[str]],
) -> list[Leak]:
    """Both checks over one string."""
    return scan_vocabulary(text, surface, location, names) + scan_commodity_grouping(
        text, surface, location, commodities
    )


# --- Connection ------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Only what the guard needs. No Neo4j, no volume, no write path."""

    profile: str | None
    host: str | None
    token: str | None
    warehouse_id: str
    catalog: str
    schema: str
    genie_space_id: str


def require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Missing {name}: copy .env.sample to .env and fill it in.")
    return value


def read_config() -> Config:
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
        genie_space_id=require_env("GENIE_SPACE_ID", DEFAULT_GENIE_SPACE_ID),
    )


def run_sql(w: Any, cfg: Config, statement: str) -> list[list[Any]]:
    """Execute one read-only statement and return its rows."""
    import time

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
    return list(response.result.data_array or [])


# --- The surfaces ----------------------------------------------------------


def check_unity_catalog(
    w: Any, cfg: Config, names: list[str], commodities: dict[str, set[str]]
) -> list[Leak]:
    """Table names, column names, and both kinds of comment.

    Read back from information_schema rather than from upload.py's SEMANTICS
    dict on purpose. Twice in this project's history a change recorded as
    applied was absent from the live workspace, so what matters is what the
    workspace holds, not what the repo intended to send it.
    """
    leaks: list[Leak] = []

    tables = run_sql(
        w,
        cfg,
        f"SELECT table_name, comment FROM `{cfg.catalog}`.information_schema.tables "
        f"WHERE table_schema = '{cfg.schema}'",
    )
    for table_name, comment in tables:
        leaks += scan(table_name, "table name", table_name, names, commodities)
        leaks += scan(comment, "table comment", table_name, names, commodities)

    columns = run_sql(
        w,
        cfg,
        f"SELECT table_name, column_name, comment "
        f"FROM `{cfg.catalog}`.information_schema.columns "
        f"WHERE table_schema = '{cfg.schema}'",
    )
    for table_name, column_name, comment in columns:
        where = f"{table_name}.{column_name}"
        leaks += scan(column_name, "column name", where, names, commodities)
        leaks += scan(comment, "column comment", where, names, commodities)

    print(f"  Unity Catalog: {len(tables)} tables, {len(columns)} columns scanned")
    return leaks


def check_genie_space(
    w: Any, cfg: Config, names: list[str], commodities: dict[str, set[str]]
) -> list[Leak]:
    """The space title, description, and its full serialized definition.

    serialized_space carries the text instructions, the column configs, and the
    example SQLs in one blob. Scanning it whole rather than field by field is
    deliberate: the guard should not need updating every time the space gains a
    new kind of authored text.

    include_serialized_space must be passed explicitly. Without it the API omits
    the field entirely and the guard scans an empty string, which reports clean
    while checking nothing. That is the silent-no-op failure the Story 2
    landmine asserts exist to catch, so the emptiness check below is not
    defensive clutter: it is the difference between this function passing and
    this function meaning something.
    """
    space = w.genie.get_space(cfg.genie_space_id, include_serialized_space=True)
    if not space.serialized_space:
        sys.exit(
            f"Genie space {cfg.genie_space_id} returned no serialized definition. "
            "The guard cannot verify the space's instructions or example SQL, so "
            "this run proves nothing about the surface that matters most. "
            "Refusing to report clean."
        )
    leaks: list[Leak] = []
    where = f"space {cfg.genie_space_id}"
    leaks += scan(space.title, "genie title", where, names, commodities)
    leaks += scan(space.description, "genie description", where, names, commodities)
    leaks += scan(
        space.serialized_space, "genie definition", where, names, commodities
    )
    size = len(space.serialized_space or "")
    print(f"  Genie space:   '{space.title}', {size} chars of definition scanned")
    return leaks


def check_authored_comments(
    names: list[str], commodities: dict[str, set[str]]
) -> list[Leak]:
    """upload.py's SEMANTICS, before any of it reaches the workspace.

    The offline half. Catching a leak in the repo is cheaper than catching it
    after upload, and this runs with no credentials so it can gate `make check`.
    It is not a substitute for the live scan: the Genie space is not in this
    repo at all, and the workspace can drift from what upload.py would send.
    """
    import upload

    leaks: list[Leak] = []
    for table, semantics in upload.SEMANTICS.items():
        leaks += scan(
            semantics.comment, "authored table comment", table, names, commodities
        )
        for column, comment in semantics.columns.items():
            leaks += scan(
                comment,
                "authored column comment",
                f"{table}.{column}",
                names,
                commodities,
            )
    print(f"  upload.py:     {len(upload.SEMANTICS)} table specs scanned")
    return leaks


def report(leaks: list[Leak], mode: str) -> int:
    if not leaks:
        print(f"\nVocabulary guard clean ({mode}). Claim A holds on every surface checked.")
        return 0
    print(f"\nVocabulary guard FAILED ({mode}): {len(leaks)} leak(s).\n")
    for leak in leaks:
        print(leak.render())
        print()
    print(
        "Each of these is an authored artifact Run A can read, which is what "
        "CONTRACT.md section 1 says cannot exist. Fix the surface, not the guard."
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline",
        action="store_true",
        help="scan upload.py's authored comments only; connects to nothing",
    )
    args = parser.parse_args()

    load_dotenv(HERE / ".env")
    names = governed_vocabulary()
    commodities = commodity_subcategories()
    print(
        f"Governed vocabulary: {len(names)} names plus TERM-/RULE-/MEAS-/THR-/GM- "
        f"identifiers.\nCommodity groupings: "
        f"{', '.join(f'{k} ({len(v)})' for k, v in commodities.items())}\n"
    )

    if args.offline:
        return report(check_authored_comments(names, commodities), "offline")

    cfg = read_config()
    from databricks.sdk import WorkspaceClient

    if cfg.profile:
        w = WorkspaceClient(profile=cfg.profile)
    else:
        w = WorkspaceClient(host=cfg.host, token=cfg.token)

    leaks = check_authored_comments(names, commodities)
    leaks += check_unity_catalog(w, cfg, names, commodities)
    leaks += check_genie_space(w, cfg, names, commodities)
    return report(leaks, "live")


if __name__ == "__main__":
    sys.exit(main())

"""Validate the Ask page's presets outside Streamlit: retrieval, generation, and both runs.

Exercises the exact functions `page_ask.render` calls per click — `mcp_retrieval.run_retrieval`,
`query_generation.generate_queries`, `page_ask._run_sql`, `page_ask._run_cypher` — against the
live MCP server, warehouse, and operational graph, so a preset that silently regresses to an
empty answer fails here instead of only being noticed in the browser.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import app_connections
import mcp_retrieval
import query_generation
from config import load_demo_env
from page_ask import PRESETS, _run_cypher, _run_sql
from query_semantic_map import require_grounded_identifiers


@dataclass(frozen=True)
class PresetResult:
    """One preset's outcome for both the Lakehouse SQL and operational Cypher runs."""

    question: str
    sql_row_count: int | None
    sql_error: str | None
    cypher_row_count: int | None
    cypher_error: str | None

    @property
    def passed(self) -> bool:
        return (
            self.sql_error is None
            and self.cypher_error is None
            and self.sql_row_count
            and self.cypher_row_count
        )


def run_preset(
    question: str,
    *,
    warehouse: app_connections.WarehouseCredentials,
    operational_graph: app_connections.GraphConnection,
) -> PresetResult:
    """Run one preset through the full Ask pipeline and report both row counts."""
    trace = mcp_retrieval.run_retrieval(question, warehouse.catalog, warehouse.schema)
    generated = query_generation.generate_queries(
        question, trace, catalog=warehouse.catalog, schema=warehouse.schema
    )
    require_grounded_identifiers(generated.identifiers, trace.retrieved_names())

    sql_result = _run_sql(warehouse, generated.sql)
    cypher_result = _run_cypher(operational_graph, generated.cypher)

    return PresetResult(
        question=question,
        sql_row_count=len(sql_result["dataframe"]) if "dataframe" in sql_result else None,
        sql_error=sql_result.get("error"),
        cypher_row_count=len(cypher_result["dataframe"]) if "dataframe" in cypher_result else None,
        cypher_error=cypher_result.get("error"),
    )


def validate() -> dict[str, object]:
    """Run every Ask preset and raise if any fails to return rows on both sides."""
    load_demo_env()
    warehouse = app_connections.warehouse_credentials()
    if not warehouse.ok:
        raise RuntimeError(f"SQL warehouse unavailable: {warehouse.error}")
    operational_graph = app_connections.operational_graph_connection()
    if not operational_graph.ok:
        raise RuntimeError(f"Operational graph unavailable: {operational_graph.error}")

    results = [
        run_preset(question, warehouse=warehouse, operational_graph=operational_graph)
        for question in PRESETS
    ]

    failed = [result.question for result in results if not result.passed]
    report = {
        "status": "failed" if failed else "passed",
        "presets": [
            {
                "question": result.question,
                "sql_row_count": result.sql_row_count,
                "sql_error": result.sql_error,
                "cypher_row_count": result.cypher_row_count,
                "cypher_error": result.cypher_error,
            }
            for result in results
        ],
    }
    if failed:
        raise RuntimeError(
            f"Ask presets returned no results: {failed}. Full report: {json.dumps(report, indent=2)}"
        )
    return report


def main() -> None:
    """Run validation and print a machine-readable result."""
    try:
        report = validate()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

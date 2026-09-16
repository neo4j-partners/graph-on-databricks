"""Statement execution helper for the configured SQL warehouse.

Wraps `WorkspaceClient.statement_execution.execute_statement` and returns rows
as a list of dicts keyed by column name.
"""

from __future__ import annotations

from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Disposition,
    Format,
    StatementParameterListItem,
    StatementState,
)


def execute(
    ws: WorkspaceClient,
    warehouse_id: str,
    sql: str,
    parameters: list[StatementParameterListItem] | None = None,
) -> list[dict[str, Any]]:
    """Execute a SQL statement and return result rows as dicts.

    Raises a RuntimeError if the warehouse_id is empty or the statement does
    not reach SUCCEEDED state.
    """
    if not warehouse_id:
        raise RuntimeError(
            "GRAPH_FRAUD_ANALYST_WAREHOUSE_ID is not configured; cannot execute SQL."
        )

    response = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=sql,
        parameters=parameters,
        format=Format.JSON_ARRAY,
        disposition=Disposition.INLINE,
        wait_timeout="50s",
    )

    if response.status and response.status.state != StatementState.SUCCEEDED:
        error_msg = (
            response.status.error.message
            if response.status.error and response.status.error.message
            else f"Statement ended in state {response.status.state}"
        )
        raise RuntimeError(f"SQL execution failed: {error_msg}")

    if not response.manifest or not response.manifest.schema or not response.manifest.schema.columns:
        return []

    columns = [c.name or "" for c in response.manifest.schema.columns]
    rows = response.result.data_array if response.result and response.result.data_array else []
    return [dict(zip(columns, row)) for row in rows]

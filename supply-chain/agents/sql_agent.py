"""
SQL Agent — answers supply chain questions by generating and executing SQL
against Databricks gold tables via the SQL Statement Execution API.

Uses Claude Opus 4.6 with adaptive thinking + tool use.
The agent may issue multiple SQL queries (e.g., two lookups joined logically)
before producing a final natural-language answer.
"""
import json
import logging
import time
from typing import Any

import anthropic
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from .config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MAX_SQL_ROWS,
)
from .prompts import SQL_AGENT_SYSTEM, SQL_AGENT_TOOLS

logger = logging.getLogger(__name__)

# Maximum tool-call iterations to prevent infinite loops
_MAX_ITERS = 6


class SQLAgent:
    def __init__(self) -> None:
        self._claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._dbx = WorkspaceClient()
        self._warehouse_id: str | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def answer(self, question: str, relevant_tables: list[str]) -> dict[str, Any]:
        """
        Generate SQL, execute it, and return a structured answer.

        Returns:
        {
            "answer": str,          # Natural-language answer
            "queries": [...],       # List of {sql, description, rows} dicts
            "relevant_tables": [...],
        }
        """
        system = SQL_AGENT_SYSTEM.format(max_rows=MAX_SQL_ROWS)
        messages = [{"role": "user", "content": question}]

        executed_queries: list[dict] = []

        for _ in range(_MAX_ITERS):
            response = self._claude.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=system,
                tools=SQL_AGENT_TOOLS,
                messages=messages,
            )

            # Collect assistant message content
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # Extract final text answer
                answer_text = self._extract_text(response.content)
                return {
                    "answer": answer_text,
                    "queries": executed_queries,
                    "relevant_tables": relevant_tables,
                }

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    sql = block.input.get("sql", "")
                    desc = block.input.get("description", "")
                    logger.debug("SQL Agent executing: %s", desc)

                    try:
                        rows = self._execute_sql(sql)
                        result_str = json.dumps(rows[:MAX_SQL_ROWS])
                        executed_queries.append(
                            {"sql": sql, "description": desc, "rows": rows[:MAX_SQL_ROWS]}
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })
                    except Exception as exc:
                        error_msg = f"SQL error: {exc}"
                        logger.warning(error_msg)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": error_msg,
                            "is_error": True,
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                break

        # Fallback
        return {
            "answer": "Could not produce a complete answer within the iteration limit.",
            "queries": executed_queries,
            "relevant_tables": relevant_tables,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_warehouse_id(self) -> str:
        if self._warehouse_id:
            return self._warehouse_id
        for wh in self._dbx.warehouses.list():
            if wh.state and wh.state.value in ("RUNNING", "STARTING"):
                self._warehouse_id = wh.id
                return self._warehouse_id
        warehouses = list(self._dbx.warehouses.list())
        if not warehouses:
            raise RuntimeError("No SQL warehouses available.")
        self._warehouse_id = warehouses[0].id
        return self._warehouse_id

    def _execute_sql(self, sql: str) -> list[dict]:
        """Execute SQL and return rows as a list of dicts."""
        stmt = self._dbx.statement_execution.execute_statement(
            warehouse_id=self._get_warehouse_id(),
            statement=sql,
        )
        while stmt.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(0.5)
            stmt = self._dbx.statement_execution.get_statement(stmt.statement_id)

        if stmt.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(
                f"Statement failed [{stmt.status.state}]: {stmt.status.error}"
            )

        if not stmt.result or not stmt.result.data_array:
            return []

        # Map column names to values
        columns = [col.name for col in stmt.manifest.schema.columns]
        return [dict(zip(columns, row)) for row in stmt.result.data_array]

    @staticmethod
    def _extract_text(content: list) -> str:
        parts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                parts.append(block.text)
        return "\n".join(parts).strip()

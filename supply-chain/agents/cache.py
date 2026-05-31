"""
Answer cache backed by Delta Lake.

Table: supplychain.supply_chain_medallion.answer_cache

Columns
-------
question_hash   STRING   SHA-256 of normalised question text (primary key)
question_text   STRING   Original question
query_type      STRING   'sql' | 'graph'
subgraph_type   STRING   Graph projection type, e.g. 'supplier_risk' (NULL for SQL)
result_json     STRING   JSON-serialised answer payload
computed_at     TIMESTAMP
ttl_hours       INT      How long this entry is valid
hit_count       BIGINT   Incremented on every cache read
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from databricks.sdk import WorkspaceClient

from .config import ANSWER_CACHE_TABLE, CATALOG, SCHEMA

logger = logging.getLogger(__name__)

# DDL – created once on first use
_CREATE_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {ANSWER_CACHE_TABLE} (
    question_hash  STRING       NOT NULL,
    question_text  STRING,
    query_type     STRING,
    subgraph_type  STRING,
    result_json    STRING,
    computed_at    TIMESTAMP,
    ttl_hours      INT,
    hit_count      BIGINT
)
USING DELTA
CLUSTER BY (question_hash)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
"""


def _hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()


def _get_warehouse_id(client: WorkspaceClient) -> str:
    """Return the first running SQL warehouse."""
    for wh in client.warehouses.list():
        if wh.state and wh.state.value in ("RUNNING", "STARTING"):
            return wh.id
    # Fall back to first available
    warehouses = list(client.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses found in workspace.")
    return warehouses[0].id


class AnswerCache:
    def __init__(self) -> None:
        self._client = WorkspaceClient()
        self._warehouse_id: str | None = None
        self._ensure_table()

    def _wh(self) -> str:
        if self._warehouse_id is None:
            self._warehouse_id = _get_warehouse_id(self._client)
        return self._warehouse_id

    def _execute(self, sql: str, params: list | None = None) -> Any:
        from databricks.sdk.service.sql import StatementState

        stmt = self._client.statement_execution.execute_statement(
            warehouse_id=self._wh(),
            statement=sql,
            parameters=params or [],
        )
        # Poll until done
        import time
        while stmt.status.state in (
            StatementState.PENDING,
            StatementState.RUNNING,
        ):
            time.sleep(0.5)
            stmt = self._client.statement_execution.get_statement(stmt.statement_id)

        if stmt.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(
                f"SQL failed [{stmt.status.state}]: {stmt.status.error}"
            )
        return stmt.result

    def _ensure_table(self) -> None:
        try:
            self._execute(_CREATE_TABLE_DDL)
        except Exception as exc:
            logger.warning("Could not create answer_cache table: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, question: str) -> dict | None:
        """Return cached result if present and not expired, else None."""
        h = _hash(question)
        sql = f"""
            SELECT result_json, computed_at, ttl_hours
            FROM {ANSWER_CACHE_TABLE}
            WHERE question_hash = '{h}'
            LIMIT 1
        """
        try:
            result = self._execute(sql)
            if not result or not result.data_array:
                return None

            row = result.data_array[0]
            result_json, computed_at_str, ttl_hours = row[0], row[1], row[2]

            # TTL check
            computed_at = datetime.fromisoformat(str(computed_at_str).replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - computed_at).total_seconds() / 3600
            if age_hours > float(ttl_hours or 24):
                logger.debug("Cache expired for hash %s (age=%.1fh)", h, age_hours)
                return None

            # Increment hit counter (fire-and-forget)
            self._execute(
                f"UPDATE {ANSWER_CACHE_TABLE} SET hit_count = hit_count + 1 "
                f"WHERE question_hash = '{h}'"
            )
            return json.loads(result_json)

        except Exception as exc:
            logger.warning("Cache read error: %s", exc)
            return None

    def put(
        self,
        question: str,
        result: dict,
        query_type: str,
        subgraph_type: str | None = None,
        ttl_hours: int | None = None,
    ) -> None:
        """Write or overwrite a cache entry."""
        from .config import CACHE_TTL_HOURS

        h = _hash(question)
        q_escaped = question.replace("'", "''")
        result_json = json.dumps(result).replace("'", "''")
        sub = subgraph_type or ""
        ttl = ttl_hours or CACHE_TTL_HOURS
        now = datetime.now(timezone.utc).isoformat()

        sql = f"""
            MERGE INTO {ANSWER_CACHE_TABLE} AS t
            USING (
                SELECT
                    '{h}'          AS question_hash,
                    '{q_escaped}'  AS question_text,
                    '{query_type}' AS query_type,
                    '{sub}'        AS subgraph_type,
                    '{result_json}' AS result_json,
                    TIMESTAMP '{now}' AS computed_at,
                    {ttl}          AS ttl_hours,
                    0              AS hit_count
            ) AS s ON t.question_hash = s.question_hash
            WHEN MATCHED THEN UPDATE SET
                t.result_json  = s.result_json,
                t.computed_at  = s.computed_at,
                t.ttl_hours    = s.ttl_hours,
                t.hit_count    = 0
            WHEN NOT MATCHED THEN INSERT *
        """
        try:
            self._execute(sql)
            logger.debug("Cached answer for hash %s (type=%s)", h, query_type)
        except Exception as exc:
            logger.warning("Cache write error: %s", exc)

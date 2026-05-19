"""Finance Genie dbxcarta preset.

Single source of truth for the Finance Genie Lakehouse contract: the UC scope,
the expected base and Gold tables, the dbxcarta env overlay, the readiness
check, and the demo-question upload helper.

The exported `preset` attribute is what `dbxcarta preset
sql_semantics:preset ...` resolves against.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from dbxcarta.client.databricks import quote_identifier, validate_identifier
from dbxcarta.client.presets import ReadinessReport

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


_DEFAULT_CATALOG = "graph-enriched-lakehouse"
_DEFAULT_SCHEMA = "graph-enriched-schema"
_DEFAULT_VOLUME = "graph-enriched-volume"

_BASE_TABLES: tuple[str, ...] = (
    "accounts",
    "merchants",
    "transactions",
    "account_links",
    "account_labels",
)

_GOLD_TABLES: tuple[str, ...] = (
    "gold_accounts",
    "gold_account_similarity_pairs",
    "gold_fraud_ring_communities",
)

_EXPECTED_TABLES = _BASE_TABLES + _GOLD_TABLES

_QUESTIONS_FILE = Path(__file__).resolve().with_name("questions.json")


@dataclass(frozen=True)
class FinanceGeniePreset:
    """Preset implementation for the Finance Genie Lakehouse."""

    catalog: str = _DEFAULT_CATALOG
    schema: str = _DEFAULT_SCHEMA
    volume: str = _DEFAULT_VOLUME
    base_tables: tuple[str, ...] = field(default=_BASE_TABLES)
    optional_tables: tuple[str, ...] = field(default=_GOLD_TABLES)

    def __post_init__(self) -> None:
        validate_identifier(self.catalog, label="catalog")
        validate_identifier(self.schema, label="schema")
        validate_identifier(self.volume, label="volume")

    @property
    def volume_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/{self.volume}"

    def env(self) -> dict[str, str]:
        volume_path = self.volume_path
        return {
            "DBXCARTA_CATALOG": self.catalog,
            "DBXCARTA_SCHEMAS": self.schema,
            "DATABRICKS_VOLUME_PATH": volume_path,
            "DBXCARTA_SUMMARY_VOLUME": f"{volume_path}/dbxcarta/runs",
            "DBXCARTA_SUMMARY_TABLE": f"{self.catalog}.{self.schema}.dbxcarta_run_summary",
            "DBXCARTA_INCLUDE_VALUES": "true",
            "DBXCARTA_SAMPLE_LIMIT": "10",
            "DBXCARTA_SAMPLE_CARDINALITY_THRESHOLD": "50",
            "DBXCARTA_INCLUDE_EMBEDDINGS_TABLES": "true",
            "DBXCARTA_INCLUDE_EMBEDDINGS_COLUMNS": "true",
            "DBXCARTA_INCLUDE_EMBEDDINGS_VALUES": "true",
            "DBXCARTA_INCLUDE_EMBEDDINGS_SCHEMAS": "true",
            "DBXCARTA_INCLUDE_EMBEDDINGS_DATABASES": "true",
            "DBXCARTA_INFER_SEMANTIC": "true",
            "DBXCARTA_EMBEDDING_ENDPOINT": "databricks-gte-large-en",
            "DBXCARTA_EMBEDDING_DIMENSION": "1024",
            "DBXCARTA_EMBEDDING_FAILURE_THRESHOLD": "0.10",
            "DBXCARTA_CLIENT_QUESTIONS": f"{volume_path}/dbxcarta/questions.json",
            "DBXCARTA_CLIENT_ARMS": "no_context,schema_dump,graph_rag",
            "DBXCARTA_INJECT_CRITERIA": "false",
        }

    def readiness(
        self,
        ws: "WorkspaceClient",
        warehouse_id: str,
    ) -> ReadinessReport:
        table_names = _fetch_table_names(ws, warehouse_id, self.catalog, self.schema)
        present_set = {name.strip() for name in table_names if name and name.strip()}
        present = tuple(name for name in _EXPECTED_TABLES if name in present_set)
        missing_required = tuple(
            name for name in self.base_tables if name not in present_set
        )
        missing_optional = tuple(
            name for name in self.optional_tables if name not in present_set
        )
        return ReadinessReport(
            catalog=self.catalog,
            schema=self.schema,
            present=present,
            missing_required=missing_required,
            missing_optional=missing_optional,
        )

    def upload_questions(self, ws: "WorkspaceClient") -> None:
        dest = os.environ.get("DBXCARTA_CLIENT_QUESTIONS", "")
        if not dest:
            raise RuntimeError(
                "DBXCARTA_CLIENT_QUESTIONS is not set; cannot determine upload destination."
            )
        if not dest.startswith("/Volumes/") or not dest.endswith(".json"):
            raise ValueError(
                f"DBXCARTA_CLIENT_QUESTIONS must be a /Volumes/... .json path, got {dest!r}"
            )
        _validate_questions_file(_QUESTIONS_FILE)
        _ensure_parent_dir(ws, dest)
        with _QUESTIONS_FILE.open("rb") as fh:
            ws.files.upload(file_path=dest, contents=fh, overwrite=True)


def _fetch_table_names(
    ws: "WorkspaceClient",
    warehouse_id: str,
    catalog: str,
    schema: str,
) -> list[str]:
    from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout

    statement = (
        "SELECT table_name "
        f"FROM {quote_identifier(catalog)}.information_schema.tables "
        f"WHERE table_schema = '{schema}'"
    )
    response = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
    )
    rows = getattr(getattr(response, "result", None), "data_array", None) or []
    return [row[0] for row in rows if row]


def _validate_questions_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"questions file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list) or not data:
        raise ValueError(f"questions file must be a non-empty JSON array: {path}")


def _ensure_parent_dir(ws: "WorkspaceClient", dest: str) -> None:
    from databricks.sdk.errors import ResourceAlreadyExists

    parent = dest.rsplit("/", 1)[0]
    try:
        ws.files.create_directory(parent)
    except ResourceAlreadyExists:
        pass


preset = FinanceGeniePreset()


__all__ = ["FinanceGeniePreset", "preset"]

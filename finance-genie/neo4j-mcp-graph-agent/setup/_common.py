"""Shared setup helpers for local Databricks provisioning scripts."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, ResourceAlreadyExists
from databricks.sdk.service.compute import Language
from databricks.sdk.service.sql import StatementState
from pydantic import BaseModel, Field, ValidationError, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Settings, load_settings  # noqa: E402

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AgentCoreCredentials(BaseModel):
    gateway_url: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    token_url: str = Field(min_length=1)
    scope: str = Field(min_length=1)

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def gateway_host(self) -> str:
        parsed = urlparse(self.gateway_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "gateway_url must be an absolute http(s) URL, "
                f"got {self.gateway_url!r}"
            )
        return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class CliContext:
    settings: Settings
    ws: WorkspaceClient


def fail(message: str) -> NoReturn:
    print(f"FAIL  {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"OK    {message}")


def validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_RE.match(value):
        fail(
            f"{label}={value!r} is not a simple Databricks identifier. "
            "Use letters, numbers, and underscores, starting with a letter "
            "or underscore."
        )


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--profile", help="Databricks CLI profile to use")
    return parser


def make_context(profile: str | None = None) -> CliContext:
    settings = load_settings()
    selected_profile = profile or settings.databricks_profile
    ws = WorkspaceClient(profile=selected_profile) if selected_profile else WorkspaceClient()
    if selected_profile:
        ok(f"using Databricks profile: {selected_profile}")
    return CliContext(settings=settings, ws=ws)


def load_agentcore_credentials(path: Path) -> AgentCoreCredentials:
    if not path.is_file():
        fail(f"credentials file not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"credentials file is not valid JSON: {exc}")
    try:
        return AgentCoreCredentials.model_validate(raw)
    except ValidationError as exc:
        missing = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()
            if error["type"].startswith("missing") or error["type"].endswith("too_short")
        ]
        if missing:
            fail(f"missing or empty in credentials file: {', '.join(missing)}")
        fail(f"invalid credentials file: {exc}")


def create_secret_scope_if_needed(ws: WorkspaceClient, scope: str) -> None:
    try:
        ws.secrets.create_scope(scope=scope)
        ok(f"created secret scope: {scope}")
    except ResourceAlreadyExists:
        ok(f"secret scope already exists: {scope}")


def secret_scope_exists(ws: WorkspaceClient, scope: str) -> bool:
    return any(item.name == scope for item in ws.secrets.list_scopes())


def execute_sql(settings: Settings, ws: WorkspaceClient, sql: str) -> None:
    if settings.databricks_warehouse_id:
        response = ws.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=settings.databricks_warehouse_id,
            wait_timeout="50s",
        )
        statement_id = response.statement_id
        state = response.status.state if response.status else None
        while state in {StatementState.PENDING, StatementState.RUNNING}:
            if not statement_id:
                fail("SQL statement did not return a statement_id for polling")
            time.sleep(2)
            response = ws.statement_execution.get_statement(statement_id)
            state = response.status.state if response.status else None
        if state != StatementState.SUCCEEDED:
            message = response.status.error.message if response.status and response.status.error else response
            fail(f"SQL statement failed: {message}")
        return

    if not settings.databricks_cluster_id:
        fail("set DATABRICKS_WAREHOUSE_ID or DATABRICKS_CLUSTER_ID in .env")

    context = ws.command_execution.create(
        cluster_id=settings.databricks_cluster_id,
        language=Language.SQL,
    ).result()
    if not context.id:
        fail("Databricks command execution did not return a context id")
    try:
        result = ws.command_execution.execute(
            cluster_id=settings.databricks_cluster_id,
            context_id=context.id,
            language=Language.SQL,
            command=sql,
        ).result()
        status = str(getattr(result.status, "value", result.status))
        if status != "Finished":
            fail(f"cluster SQL command failed with status {status}: {result.results}")
    finally:
        ws.command_execution.destroy(settings.databricks_cluster_id, context.id)


def get_connection(ws: WorkspaceClient, name: str):
    try:
        return ws.connections.get(name)
    except NotFound:
        return None

"""Configuration for the Neo4j MCP graph agent.

Values are loaded from ``.env`` in this directory and then from the process
environment. The process environment is how ``databricks_job_runner`` forwards
the same values to remote Databricks Python tasks.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / ".env"
ROOT_ENV_PATH = PROJECT_DIR.parent / ".env"

load_dotenv(ROOT_ENV_PATH, override=False)
load_dotenv(ENV_PATH, override=False)


class Settings(BaseModel):
    """Typed settings shared by setup, validation, jobs, and agent code."""

    model_config = ConfigDict(frozen=True)

    databricks_profile: str | None = Field(default=None, alias="DATABRICKS_PROFILE")
    databricks_compute_mode: str = Field(default="cluster", alias="DATABRICKS_COMPUTE_MODE")
    databricks_cluster_id: str | None = Field(default=None, alias="DATABRICKS_CLUSTER_ID")
    databricks_serverless_env_version: str = Field(
        default="3", alias="DATABRICKS_SERVERLESS_ENV_VERSION"
    )
    databricks_workspace_dir: str | None = Field(
        default=None,
        alias="DATABRICKS_WORKSPACE_DIR",
        validation_alias=AliasChoices(
            "NEO4J_MCP_AGENT_DATABRICKS_WORKSPACE_DIR",
            "DATABRICKS_WORKSPACE_DIR",
        ),
    )
    databricks_volume_path: str | None = Field(default=None, alias="DATABRICKS_VOLUME_PATH")
    databricks_warehouse_id: str | None = Field(
        default=None,
        alias="DATABRICKS_WAREHOUSE_ID",
        validation_alias=AliasChoices("DATABRICKS_WAREHOUSE_ID", "SQL_WAREHOUSE_ID"),
    )

    agentcore_credentials_path: Path = Field(
        default=PROJECT_DIR / ".mcp-credentials.json",
        alias="AGENTCORE_CREDENTIALS_PATH",
    )
    mcp_secret_scope: str = Field(default="mcp-neo4j-secrets", alias="MCP_SECRET_SCOPE")
    uc_connection_name: str = Field(
        default="neo4j_agentcore_mcp", alias="UC_CONNECTION_NAME"
    )
    catalog: str = Field(default="mcp_demo_catalog", alias="CATALOG")
    schema_name: str = Field(default="agents", alias="SCHEMA")
    uc_model_name: str = Field(default="neo4j_mcp_agent", alias="UC_MODEL_NAME")
    llm_endpoint_name: str = Field(
        default="databricks-claude-sonnet-4-6", alias="LLM_ENDPOINT_NAME"
    )
    model_serving_endpoint_name: str = Field(
        default="neo4j-mcp-agent", alias="MODEL_SERVING_ENDPOINT_NAME"
    )
    smoke_test_prompt: str = Field(
        default=(
            "What is the schema of the Neo4j database? "
            "Show node labels and relationship types."
        ),
        alias="SMOKE_TEST_PROMPT",
    )

    @field_validator("*", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("agentcore_credentials_path", mode="before")
    @classmethod
    def resolve_credentials_path(cls, value: object) -> object:
        if value is None or value == "":
            return PROJECT_DIR / ".mcp-credentials.json"
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            root_relative = PROJECT_DIR.parent / path
            path = root_relative if root_relative.exists() else PROJECT_DIR / path
        return path

    @property
    def full_uc_model_name(self) -> str:
        return f"{self.catalog}.{self.schema_name}.{self.uc_model_name}"

    @property
    def external_mcp_path(self) -> str:
        return f"/api/2.0/mcp/external/{self.uc_connection_name}"

    @property
    def connection_proxy_path(self) -> str:
        return (
            "/api/2.0/unity-catalog/connections/"
            f"{self.uc_connection_name}/proxy"
        )


def load_settings() -> Settings:
    return Settings.model_validate(dict(os.environ))


settings = load_settings()

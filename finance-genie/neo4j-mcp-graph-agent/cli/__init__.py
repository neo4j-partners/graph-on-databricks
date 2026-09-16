"""Neo4j MCP graph-agent CLI wired to the Databricks job runner."""

import os
from dataclasses import dataclass
from pathlib import Path

from databricks.sdk.service.compute import Environment
from databricks.sdk.service.jobs import JobEnvironment
from databricks_job_runner import ClassicCluster, Runner, Serverless
from databricks_job_runner.config import RunnerConfig

from config import settings

REMOTE_PIP_DEPENDENCIES = [
    "databricks-agents==1.10.1",
    "databricks-langchain==0.19.0",
    "databricks-mcp==0.9.0",
    "langchain-core==1.3.3",
    "langgraph==1.1.10",
    "langgraph-prebuilt==1.0.13",
    "langgraph-sdk==0.3.14",
    "mcp==1.27.0",
    "mlflow==3.12.0",
    "nest-asyncio==1.6.0",
    "requests==2.33.1",
]


@dataclass(frozen=True)
class DependencyServerless(Serverless):
    """Serverless compute with pip dependencies installed before job start."""

    dependencies: tuple[str, ...] = ()

    def environments(self, wheel_path: str | None) -> list[JobEnvironment]:
        dependencies = list(self.dependencies)
        if wheel_path:
            dependencies.append(wheel_path)
        return [
            JobEnvironment(
                environment_key="default",
                spec=Environment(
                    environment_version=self.environment_version,
                    dependencies=dependencies,
                ),
            )
        ]


class Neo4jMcpRunner(Runner):
    @property
    def config(self) -> RunnerConfig:
        """Load the shared root env, with a project-local compatibility fallback."""
        if self._config is None:
            root_env = self.project_dir.parent / ".env"
            project_env = self.project_dir / ".env"
            env_file = root_env if root_env.exists() else project_env
            if settings.databricks_workspace_dir:
                os.environ["DATABRICKS_WORKSPACE_DIR"] = (
                    settings.databricks_workspace_dir
                )
            self._config = RunnerConfig.from_env_file(env_file)
        return self._config

    def _compute(self, mode_override: str | None = None):
        mode = mode_override or self.config.databricks_compute_mode
        if mode == "serverless":
            return DependencyServerless(
                environment_version=self.config.databricks_serverless_env_version,
                dependencies=tuple(REMOTE_PIP_DEPENDENCIES),
            )
        if not self.config.databricks_cluster_id:
            from databricks_job_runner import RunnerError

            raise RunnerError(
                "DATABRICKS_CLUSTER_ID must be set in .env to use cluster compute."
            )
        return ClassicCluster(cluster_id=self.config.databricks_cluster_id)


runner = Neo4jMcpRunner(
    run_name_prefix="neo4j_mcp_graph_agent",
    project_dir=Path(__file__).resolve().parent.parent,
    scripts_dir="jobs",
    extra_files=["neo4j_mcp_graph_agent.py"],
)

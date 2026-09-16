from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import Neo4jMcpRunner
from databricks_job_runner import RunnerError


class Neo4jMcpRunnerTests(unittest.TestCase):
    def test_root_environment_is_reduced_to_job_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_dir = root / "neo4j-mcp-graph-agent"
            project_dir.mkdir()
            (root / ".env").write_text(
                "DATABRICKS_COMPUTE_MODE=cluster\n"
                "DATABRICKS_CLUSTER_ID=cluster-1\n"
                "DATABRICKS_WORKSPACE_DIR=/Workspace/Users/test/project\n"
                "CATALOG=finance\n"
                "SCHEMA=agents\n"
                "UC_CONNECTION_NAME=neo4j_mcp\n"
                "NEO4J_PASSWORD=do-not-forward\n"
                "DATABRICKS_TOKEN=do-not-forward\n"
                "UNRELATED_SETTING=do-not-forward\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                runner = Neo4jMcpRunner(
                    run_name_prefix="test",
                    project_dir=project_dir,
                )
                parameters = runner.config.env_params()

        keys = {parameter.partition("=")[0] for parameter in parameters}
        self.assertEqual(
            keys,
            {
                "CATALOG",
                "DATABRICKS_WORKSPACE_DIR",
                "SCHEMA",
                "UC_CONNECTION_NAME",
            },
        )
        self.assertNotIn("NEO4J_PASSWORD", keys)
        self.assertNotIn("DATABRICKS_TOKEN", keys)
        self.assertNotIn("UNRELATED_SETTING", keys)

    def test_secret_like_allowlist_name_fails_without_exposing_value(self) -> None:
        secret_value = "value-that-must-not-appear"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_dir = root / "neo4j-mcp-graph-agent"
            project_dir.mkdir()
            (root / ".env").write_text(
                "DATABRICKS_COMPUTE_MODE=cluster\n"
                "DATABRICKS_CLUSTER_ID=cluster-1\n"
                "DATABRICKS_WORKSPACE_DIR=/Workspace/Users/test/project\n"
                f"API_TOKEN={secret_value}\n",
                encoding="utf-8",
            )

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("cli.JOB_PARAMETER_KEYS", frozenset({"API_TOKEN"})),
                self.assertRaises(RunnerError) as raised,
            ):
                runner = Neo4jMcpRunner(
                    run_name_prefix="test",
                    project_dir=project_dir,
                )
                _ = runner.config

        self.assertNotIn(secret_value, str(raised.exception))


if __name__ == "__main__":
    unittest.main()

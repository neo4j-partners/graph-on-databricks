from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.secure_runner import SecureRunner, validate_job_parameters
from databricks_job_runner.errors import RunnerError


class SecureRunnerTests(unittest.TestCase):
    def _runner(self, project_dir: Path) -> SecureRunner:
        return SecureRunner(
            run_name_prefix="test",
            project_dir=project_dir,
            parameter_keys={"CATALOG", "NEO4J_SECRET_SCOPE", "SCHEMA"},
            secret_keys=["NEO4J_PASSWORD"],
        )

    def test_only_allowlisted_parameters_are_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            (project_dir / ".env").write_text(
                "DATABRICKS_CLUSTER_ID=cluster-1\n"
                "DATABRICKS_COMPUTE_MODE=cluster\n"
                "DATABRICKS_SECRET_SCOPE=neo4j-scope\n"
                "DATABRICKS_VOLUME_PATH=/Volumes/catalog/schema/volume\n"
                "DATABRICKS_WORKSPACE_DIR=/Workspace/Users/test/project\n"
                "CATALOG=finance\n"
                "SCHEMA=demo\n"
                "NEO4J_SECRET_SCOPE=neo4j-scope\n"
                "NEO4J_PASSWORD=do-not-forward\n"
                "OPENAI_API_KEY=do-not-forward\n"
                "UNRELATED_SETTING=do-not-forward\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                runner = self._runner(project_dir)
                parameters = runner.config.env_params(secret_keys=runner.secret_keys)

        keys = {parameter.partition("=")[0] for parameter in parameters}
        self.assertEqual(
            keys,
            {
                "CATALOG",
                "DATABRICKS_SECRET_KEYS",
                "DATABRICKS_SECRET_SCOPE",
                "DATABRICKS_VOLUME_PATH",
                "DATABRICKS_WORKSPACE_DIR",
                "NEO4J_SECRET_SCOPE",
                "SCHEMA",
            },
        )
        self.assertNotIn("NEO4J_PASSWORD", keys)
        self.assertNotIn("OPENAI_API_KEY", keys)
        self.assertNotIn("UNRELATED_SETTING", keys)

    def test_secret_like_parameter_name_fails_closed(self) -> None:
        with self.assertRaisesRegex(RunnerError, "API_TOKEN"):
            validate_job_parameters(
                ["API_TOKEN=redacted"],
                allowed_keys=frozenset({"API_TOKEN"}),
            )

    def test_error_does_not_include_parameter_value(self) -> None:
        secret_value = "value-that-must-not-appear"

        with self.assertRaises(RunnerError) as raised:
            validate_job_parameters(
                [f"PASSWORD={secret_value}"],
                allowed_keys=frozenset({"PASSWORD"}),
            )

        self.assertNotIn(secret_value, str(raised.exception))


if __name__ == "__main__":
    unittest.main()

"""Fail-closed parameter handling for Databricks submit runs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from databricks_job_runner import Runner
from databricks_job_runner.config import RunnerConfig
from databricks_job_runner.errors import RunnerError
from pydantic import Field

_RUNNER_METADATA_KEYS = frozenset(
    {
        "DATABRICKS_SECRET_KEYS",
        "DATABRICKS_SECRET_SCOPE",
        "DATABRICKS_VOLUME_PATH",
        "DATABRICKS_WORKSPACE_DIR",
    }
)
_SENSITIVE_NAME_MARKERS = (
    "API_KEY",
    "CLIENT_SECRET",
    "CREDENTIAL",
    "PASSWORD",
    "PRIVATE_KEY",
    "TOKEN",
)


def _parameter_key(parameter: str) -> str:
    """Return the key from one ``KEY=VALUE`` task parameter."""
    key, separator, _ = parameter.partition("=")
    if not separator or not key:
        raise RunnerError("Job parameters must use non-empty KEY=VALUE syntax.")
    return key


def validate_job_parameters(
    parameters: Iterable[str],
    *,
    allowed_keys: frozenset[str],
) -> None:
    """Reject unexpected or secret-like task parameters without logging values."""
    keys = {_parameter_key(parameter) for parameter in parameters}
    unexpected = sorted(keys - allowed_keys - _RUNNER_METADATA_KEYS)
    sensitive = sorted(
        key
        for key in keys
        if key not in {"DATABRICKS_SECRET_KEYS", "DATABRICKS_SECRET_SCOPE"}
        and any(marker in key.upper() for marker in _SENSITIVE_NAME_MARKERS)
    )

    problems: list[str] = []
    if unexpected:
        problems.append(f"not allowlisted: {', '.join(unexpected)}")
    if sensitive:
        problems.append(f"secret-like names: {', '.join(sensitive)}")
    if problems:
        raise RunnerError(
            "Refusing to submit unsafe Databricks task parameters ("
            + "; ".join(problems)
            + ")."
        )


class SecureRunnerConfig(RunnerConfig):
    """Runner configuration that forwards only explicitly approved extras."""

    allowed_parameter_keys: frozenset[str] = Field(default_factory=frozenset)

    def env_params(self, secret_keys: list[str] | None = None) -> list[str]:
        """Build and validate the final Spark Python task parameters."""
        filtered = self.model_copy(
            update={
                "extras": {
                    key: value
                    for key, value in self.extras.items()
                    if key in self.allowed_parameter_keys
                }
            }
        )
        parameters = RunnerConfig.env_params(filtered, secret_keys=secret_keys)
        validate_job_parameters(
            parameters,
            allowed_keys=self.allowed_parameter_keys,
        )
        return parameters


class SecureRunner(Runner):
    """Databricks runner with an explicit task-parameter allowlist."""

    def __init__(
        self,
        *args: Any,
        parameter_keys: Iterable[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.parameter_keys = frozenset(parameter_keys)
        self._secure_config: SecureRunnerConfig | None = None

    @property
    def config(self) -> SecureRunnerConfig:
        """Return the base configuration with allowlisted parameter handling."""
        if self._secure_config is None:
            base_config = super().config
            self._secure_config = SecureRunnerConfig.model_validate(
                {
                    **base_config.model_dump(),
                    "allowed_parameter_keys": self.parameter_keys,
                }
            )
        return self._secure_config

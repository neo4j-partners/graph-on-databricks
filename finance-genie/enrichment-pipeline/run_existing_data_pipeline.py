#!/usr/bin/env python3
"""Run the enrichment pipeline with existing data.

This runner intentionally skips setup/generate_data.py. It is for repeatable
end-to-end tests when finance-genie/data already contains the expected CSV files
and ground_truth.json.
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ROOT_DIR = Path(__file__).resolve().parent
REPO_ENV = ROOT_DIR.parent / ".env"
VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python"
STEP_TIMEOUT_SECONDS = int(os.environ.get("PIPELINE_STEP_TIMEOUT_SECONDS", "7200"))
HEARTBEAT_SECONDS = int(os.environ.get("PIPELINE_HEARTBEAT_SECONDS", "30"))
START_STEP = int(os.environ.get("PIPELINE_START_STEP", "1"))
STOP_STEP = int(os.environ.get("PIPELINE_STOP_STEP", "0"))

REQUIRED_DATA_FILES = (
    "accounts.csv",
    "account_labels.csv",
    "account_links.csv",
    "merchants.csv",
    "transactions.csv",
    "ground_truth.json",
)


@dataclass(frozen=True)
class Step:
    name: str
    command: Sequence[str]
    timeout_seconds: int = STEP_TIMEOUT_SECONDS


def emit(message: str = "", *, file=sys.stdout) -> None:
    print(message, file=file, flush=True)


def python_cmd(*args: str) -> list[str]:
    if VENV_PYTHON.is_file():
        return [str(VENV_PYTHON), *args]
    return ["uv", "run", "python", *args]


def require_existing_data() -> None:
    missing = []
    empty = []
    for file_name in REQUIRED_DATA_FILES:
        path = ROOT_DIR.parent / "data" / file_name
        if not path.is_file():
            missing.append(str(path))
        elif path.stat().st_size == 0:
            empty.append(str(path))

    if missing or empty:
        if missing:
            emit("Missing required existing data files:", file=sys.stderr)
            for path in missing:
                emit(f"  - {path}", file=sys.stderr)
        if empty:
            emit("Required existing data files are empty:", file=sys.stderr)
            for path in empty:
                emit(f"  - {path}", file=sys.stderr)
        sys.exit(1)

    emit("OK existing finance-genie/data files are present")


def run_step(index: int, total: int, step: Step) -> None:
    started = time.monotonic()
    last_heartbeat = started
    emit()
    emit("=" * 80)
    emit(f"[{index}/{total}] {step.name}")
    emit("$ " + " ".join(step.command))
    emit("=" * 80)

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    proc = subprocess.Popen(
        list(step.command),
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert proc.stdout is not None
    output_fd = proc.stdout.fileno()

    while True:
        now = time.monotonic()
        if now - started > step.timeout_seconds:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=15)
            raise RuntimeError(
                f"{step.name} timed out after {step.timeout_seconds} seconds"
            )

        ready, _, _ = select.select([output_fd], [], [], 1)
        if ready:
            line = proc.stdout.readline()
            if line:
                print(line, end="", flush=True)

        return_code = proc.poll()
        if return_code is not None:
            remaining = proc.stdout.read()
            if remaining:
                print(remaining, end="", flush=True)
            elapsed = int(time.monotonic() - started)
            if return_code != 0:
                raise RuntimeError(
                    f"{step.name} failed with exit code {return_code} "
                    f"after {elapsed} seconds"
                )
            emit(f"PASS {step.name} ({elapsed}s)")
            return

        if now - last_heartbeat >= HEARTBEAT_SECONDS:
            elapsed = int(now - started)
            emit(f"... {step.name} still running ({elapsed}s elapsed)")
            last_heartbeat = now


def main() -> None:
    if not REPO_ENV.is_file():
        emit(
            f"Missing root env file: {REPO_ENV}. Copy .env.sample to .env first.",
            file=sys.stderr,
        )
        sys.exit(1)

    require_existing_data()

    steps = [
        Step("shell syntax check", ["bash", "-n", "upload_and_create_tables.sh", "setup_secrets.sh"], 120),
        Step("validate Databricks cluster", python_cmd("validation/validate_cluster.py"), 900),
        Step("validate Neo4j connectivity", python_cmd("validation/validate_neo4j.py"), 300),
        Step("verify fraud patterns in existing data", python_cmd("diagnostics/verify_fraud_patterns.py"), 900),
        Step("upload existing data and create base tables", ["./upload_and_create_tables.sh"], 3600),
        Step("write Databricks secrets from root .env", ["./setup_secrets.sh"], 900),
        Step("provision Genie spaces", python_cmd("setup/provision_genie_spaces.py"), 1800),
        Step("upload Databricks job scripts", python_cmd("-m", "cli", "upload", "--all"), 900),
        Step("run BEFORE Genie baseline", python_cmd("-m", "cli", "submit", "01_genie_run_before.py"), 3600),
        Step("run Neo4j ingest job", python_cmd("-m", "cli", "submit", "02_neo4j_ingest.py"), 7200),
        Step("run GDS locally against Neo4j", python_cmd("validation/run_gds.py"), 7200),
        Step("verify GDS outputs", python_cmd("validation/verify_gds.py"), 1800),
        Step("pull gold tables job", python_cmd("-m", "cli", "submit", "03_pull_gold_tables.py"), 7200),
        Step("validate gold tables job", python_cmd("-m", "cli", "submit", "04_validate_gold_tables.py"), 3600),
        Step("run AFTER Genie evaluation", python_cmd("-m", "cli", "submit", "05_genie_run_after.py"), 3600),
        Step("collect latest job logs", python_cmd("-m", "cli", "logs"), 900),
    ]

    stop_step = STOP_STEP or len(steps)
    if START_STEP < 1 or START_STEP > len(steps):
        emit(f"PIPELINE_START_STEP must be between 1 and {len(steps)}", file=sys.stderr)
        sys.exit(1)
    if stop_step < START_STEP or stop_step > len(steps):
        emit(
            f"PIPELINE_STOP_STEP must be between {START_STEP} and {len(steps)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if START_STEP > 1 or stop_step < len(steps):
        emit(f"Running selected steps: {START_STEP} through {stop_step}")

    for index, step in enumerate(steps, start=1):
        if index < START_STEP or index > stop_step:
            continue
        run_step(index, len(steps), step)

    emit()
    emit("PASS enrichment-pipeline existing-data run completed successfully")


if __name__ == "__main__":
    main()

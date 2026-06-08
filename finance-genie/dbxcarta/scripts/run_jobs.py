#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deploy the consumer bundle and run the ingest then client jobs.

Automates the "Run the jobs in finance-genie/dbxcarta" sequence from the
README: it deploys the Databricks Asset Bundle and then runs
`finance_genie_dbxcarta_ingest` followed by `finance_genie_dbxcarta_client`.

The dbxcarta config is single-sourced from dbxcarta-overlay.env. databricks.yml
carries none of it; the jobs declare no parameters. This script reads the
overlay, appends DATABRICKS_WAREHOUSE_ID, and forwards every KEY=VALUE pair to
the job at run time as task parameters (`databricks bundle run <job> -- KEY=VALUE
...`), the same way dbxcarta-submit forwards an overlay. Editing the overlay is
therefore the only place a run's config changes, so the bundle and the overlay
can never diverge.

`databricks bundle run` blocks until the job finishes, so client only starts
after ingest succeeds. Run from the project root (the directory holding
databricks.yml):

    uv run scripts/run_jobs.py --cluster-id <id> --warehouse-id <id>

Useful flags: `--target prod`, `--no-deploy` to skip deploy and reuse the last
deployment, and `--no-client` to stop after ingest.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

INGEST_JOB = "finance_genie_dbxcarta_ingest"
CLIENT_JOB = "finance_genie_dbxcarta_client"
OVERLAY_FILE = "dbxcarta-overlay.env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy the bundle and run the ingest then client jobs.",
    )
    parser.add_argument(
        "--cluster-id",
        required=True,
        help="ID of the preprovisioned classic SINGLE_USER cluster.",
    )
    parser.add_argument(
        "--warehouse-id",
        required=True,
        help="SQL warehouse ID for metadata reads and client queries.",
    )
    parser.add_argument(
        "--target",
        help="Bundle target to deploy and run against (defaults to the bundle default).",
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Skip the deploy step and reuse the last deployment.",
    )
    parser.add_argument(
        "--no-client",
        action="store_true",
        help="Stop after the ingest job; do not run the client job.",
    )
    return parser.parse_args()


def databricks_cli() -> str:
    cli = shutil.which("databricks")
    if cli is None:
        sys.exit("error: the 'databricks' CLI is not on PATH; install it first.")
    return cli


def load_overlay_params(overlay_path: Path) -> list[str]:
    """Read dbxcarta-overlay.env into a list of "KEY=VALUE" strings.

    Skips blank lines and comments and strips an optional leading `export `, so
    the result is exactly the dbxcarta config the jobs need, forwarded verbatim.
    """
    if not overlay_path.is_file():
        sys.exit(f"error: {overlay_path} not found; cannot forward the dbxcarta config.")
    params: list[str] = []
    for raw in overlay_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        params.append(f"{key.strip()}={value.strip()}")
    if not params:
        sys.exit(f"error: {overlay_path} has no KEY=VALUE entries to forward.")
    return params


def run_step(cli: str, command: list[str], label: str) -> None:
    full = [cli, *command]
    print(f"\n==> {label}: {' '.join(full)}", flush=True)
    result = subprocess.run(full)
    if result.returncode != 0:
        sys.exit(f"error: {label} failed (exit code {result.returncode}).")


def main() -> None:
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    if not (project_root / "databricks.yml").is_file():
        sys.exit(f"error: databricks.yml not found in {project_root}.")

    cli = databricks_cli()

    # cluster_id resolves existing_cluster_id at both deploy and run time.
    cluster_var = [f"--var=cluster_id={args.cluster_id}"]
    target = [f"--target={args.target}"] if args.target else []

    # The forwarded run-time parameters: the whole overlay plus the warehouse
    # (infra, not in the committed overlay). Passed after `--` so each is one
    # argv element to the wheel entry point, even values containing commas.
    overlay_params = load_overlay_params(project_root / OVERLAY_FILE)
    job_params = ["--", *overlay_params, f"DATABRICKS_WAREHOUSE_ID={args.warehouse_id}"]

    # Run the databricks CLI from the project root so relative bundle paths
    # (the vendored ./dbxcarta-dist wheels) resolve.
    os.chdir(project_root)

    if not args.no_deploy:
        run_step(cli, ["bundle", "deploy", *cluster_var, *target], "deploy")

    run_step(cli, ["bundle", "run", INGEST_JOB, *cluster_var, *target, *job_params], "ingest")

    if args.no_client:
        print("\n--no-client set; stopping after ingest.", flush=True)
        return

    run_step(cli, ["bundle", "run", CLIENT_JOB, *cluster_var, *target, *job_params], "client")
    print("\nDone: ingest and client completed.", flush=True)


if __name__ == "__main__":
    main()

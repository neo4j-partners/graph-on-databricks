#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deploy the consumer bundle and run the ingest then client jobs.

Automates the "Run the jobs in finance-genie/dbxcarta" sequence from the
README: it deploys the Databricks Asset Bundle and then runs
`finance_genie_dbxcarta_ingest` followed by `finance_genie_dbxcarta_client`,
passing the preprovisioned cluster and warehouse to each step. The vendored
`dbxcarta-dist/` wheels ship as bundle `whl:` libraries, so there is no staging
step.

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


def run_step(cli: str, command: list[str], common: list[str], label: str) -> None:
    full = [cli, *command, *common]
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

    common = [
        f"--var=cluster_id={args.cluster_id}",
        f"--var=warehouse_id={args.warehouse_id}",
    ]
    if args.target:
        common.append(f"--target={args.target}")

    # Run the databricks CLI from the project root so relative bundle paths
    # (the vendored ./dbxcarta-dist wheels) resolve.
    os.chdir(project_root)

    if not args.no_deploy:
        run_step(cli, ["bundle", "deploy"], common, "deploy")

    run_step(cli, ["bundle", "run", INGEST_JOB], common, "ingest")

    if args.no_client:
        print("\n--no-client set; stopping after ingest.", flush=True)
        return

    run_step(cli, ["bundle", "run", CLIENT_JOB], common, "client")
    print("\nDone: ingest and client completed.", flush=True)


if __name__ == "__main__":
    main()

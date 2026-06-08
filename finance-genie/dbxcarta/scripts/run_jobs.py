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

    uv run scripts/run_jobs.py

Cluster id, warehouse id, and the Databricks profile default to
DATABRICKS_CLUSTER_ID / DATABRICKS_WAREHOUSE_ID / DATABRICKS_PROFILE in .env (the
same file the local demo reads), falling back to the process environment;
`--cluster-id` / `--warehouse-id` / `--profile` override them. Other flags:
`--target prod`, `--no-deploy` to skip deploy and reuse the last deployment,
`--no-client` to stop after ingest, and `--env-file` to read a different env file.
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
ENV_FILE = ".env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy the bundle and run the ingest then client jobs.",
    )
    parser.add_argument(
        "--cluster-id",
        help="ID of the preprovisioned classic SINGLE_USER cluster. "
        "Defaults to DATABRICKS_CLUSTER_ID from the env file.",
    )
    parser.add_argument(
        "--warehouse-id",
        help="SQL warehouse ID for metadata reads and client queries. "
        "Defaults to DATABRICKS_WAREHOUSE_ID from the env file.",
    )
    parser.add_argument(
        "--profile",
        help="Databricks CLI profile for auth. "
        "Defaults to DATABRICKS_PROFILE from the env file.",
    )
    parser.add_argument(
        "--env-file",
        default=ENV_FILE,
        help=f"Env file to read cluster/warehouse/profile defaults from (default: {ENV_FILE}).",
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


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE env file into a dict.

    Skips blank lines and comments, strips an optional leading `export ` and
    surrounding quotes. Returns an empty dict if the file is absent (the caller
    can still resolve values from flags or the process environment).
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


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

    # Resolve infra (cluster, warehouse, profile) from the flag, else the env
    # file, else the process environment. The env file is the same .env the
    # local demo reads, so a configured project needs no flags at all.
    env = read_env_file(project_root / args.env_file)

    def resolve(flag: str | None, key: str) -> str | None:
        return flag or env.get(key) or os.environ.get(key)

    cluster_id = resolve(args.cluster_id, "DATABRICKS_CLUSTER_ID")
    warehouse_id = resolve(args.warehouse_id, "DATABRICKS_WAREHOUSE_ID")
    profile = resolve(args.profile, "DATABRICKS_PROFILE")

    if not cluster_id:
        sys.exit(
            "error: cluster id not set; pass --cluster-id or set "
            f"DATABRICKS_CLUSTER_ID in {args.env_file}."
        )
    if not warehouse_id:
        sys.exit(
            "error: warehouse id not set; pass --warehouse-id or set "
            f"DATABRICKS_WAREHOUSE_ID in {args.env_file}."
        )

    # cluster_id resolves existing_cluster_id at both deploy and run time.
    cluster_var = [f"--var=cluster_id={cluster_id}"]
    target = [f"--target={args.target}"] if args.target else []
    # --profile only when resolved; otherwise let the CLI use its own default
    # (e.g. host/token env auth).
    profile_flag = [f"--profile={profile}"] if profile else []
    common = [*cluster_var, *target, *profile_flag]

    # The forwarded run-time parameters: the whole overlay plus the warehouse
    # (infra, not in the committed overlay). Passed after `--` so each is one
    # argv element to the wheel entry point, even values containing commas.
    overlay_params = load_overlay_params(project_root / OVERLAY_FILE)
    job_params = ["--", *overlay_params, f"DATABRICKS_WAREHOUSE_ID={warehouse_id}"]

    # Run the databricks CLI from the project root so relative bundle paths
    # (the vendored ./dbxcarta-dist wheels) resolve.
    os.chdir(project_root)

    if not args.no_deploy:
        run_step(cli, ["bundle", "deploy", *common], "deploy")

    run_step(cli, ["bundle", "run", INGEST_JOB, *common, *job_params], "ingest")

    if args.no_client:
        print("\n--no-client set; stopping after ingest.", flush=True)
        return

    run_step(cli, ["bundle", "run", CLIENT_JOB, *common, *job_params], "client")
    print("\nDone: ingest and client completed.", flush=True)


if __name__ == "__main__":
    main()

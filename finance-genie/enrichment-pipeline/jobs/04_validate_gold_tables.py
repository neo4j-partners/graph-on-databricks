"""Direct-SQL data-correctness gate for the gold tables.

Runs as a Databricks Python task. Reads the three gold tables written by
03_pull_gold_tables.py, joins them against ground_truth.json from the UC Volume,
and verifies that the fraud labels, ring aggregates, and demo backend fields
align with the simulated ground truth.

Usage (from finance-genie/enrichment-pipeline/ with .env in place):
    python -m cli upload --all
    python -m cli submit 04_validate_gold_tables.py
    python -m cli logs
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _cluster_bootstrap import inject_params, resolve_here

inject_params()
_HERE = resolve_here()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pyspark.sql import SparkSession  # noqa: E402

from _gold_table_checks import run_gold_table_checks  # noqa: E402


def main() -> None:
    # Validates the three gold tables; gold catalog falls back to the legacy
    # single CATALOG when GOLD_CATALOG is unset.
    catalog = os.environ.get("GOLD_CATALOG") or os.environ["CATALOG"]
    schema = os.environ["SCHEMA"]
    ground_truth_path = os.environ["GROUND_TRUTH_PATH"]
    results_volume_dir = os.environ["RESULTS_VOLUME_DIR"].rstrip("/")

    spark = SparkSession.builder.getOrCreate()
    try:
        checks = run_gold_table_checks(
            spark,
            catalog,
            schema,
            ground_truth_path,
            emit=True,
        )
    except FileNotFoundError:
        print(f"FAIL  ground_truth not found at {ground_truth_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"FAIL  ground_truth at {ground_truth_path} is not valid JSON: {e}")
        sys.exit(1)

    problems = [problem for check in checks for problem in check.problems]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    artifact_path = f"{results_volume_dir}/validate_gold_tables_{timestamp}.json"
    artifact = {
        "timestamp": timestamp,
        "catalog": catalog,
        "schema": schema,
        "problems": problems,
        "results": [check.to_dict() for check in checks],
    }
    try:
        Path(artifact_path).parent.mkdir(parents=True, exist_ok=True)
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)
        print(f"\nArtifact: {artifact_path}")
    except OSError as e:
        print(f"\nWARN  failed to write artifact to {artifact_path}: {e}")

    passed = sum(1 for check in checks if check.passed)
    total = len(checks)

    print()
    print("=" * 62)
    if problems:
        print(f"FAIL  {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print(f"PASS  gold tables match ground truth ({passed}/{total}).")


if __name__ == "__main__":
    main()

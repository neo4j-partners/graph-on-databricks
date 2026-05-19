"""Upload the Finance Genie dbxcarta question set to the configured UC Volume.

Runs in two modes:

- Local CLI: `uv run python -m sql_semantics.upload_questions` loads `.env`
  for `DBXCARTA_CLIENT_QUESTIONS` and the Databricks credentials, then asks
  the preset to upload its bundled `questions.json`.
- Databricks Job: `python_wheel_task` with entry point
  `sql-semantics-upload-questions`. The preset is imported directly (this
  package owns it) and its `env()` overlay is applied so the upload helper
  reads `DBXCARTA_CLIENT_QUESTIONS` from a single source of truth.

Both modes ultimately delegate to `FinanceGeniePreset.upload_questions(ws)`
so the script does not duplicate validation or upload logic.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv

from sql_semantics.finance_genie import preset


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload sql_semantics/questions.json to DBXCARTA_CLIENT_QUESTIONS "
            "via the Finance Genie preset."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help=(
            "Local .env file to load before running. Defaults to .env. "
            "Missing file is silently ignored so cluster runs do not fail."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=False)

    for key, value in preset.env().items():
        os.environ.setdefault(key, value)

    profile = os.environ.get("DATABRICKS_PROFILE") or None
    ws = WorkspaceClient(profile=profile)
    preset.upload_questions(ws)
    print(f"uploaded sql_semantics/questions.json -> {os.environ['DBXCARTA_CLIENT_QUESTIONS']}")


if __name__ == "__main__":
    main()

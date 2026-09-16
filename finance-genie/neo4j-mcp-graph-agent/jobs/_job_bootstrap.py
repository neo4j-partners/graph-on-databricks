"""Helpers for Databricks job scripts submitted by databricks_job_runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def inject_params() -> None:
    remaining: list[str] = []
    for arg in sys.argv[1:]:
        if "=" in arg and not arg.startswith("-"):
            key, _, value = arg.partition("=")
            os.environ.setdefault(key, value)
        else:
            remaining.append(arg)
    sys.argv[1:] = remaining


def add_here_to_path() -> None:
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))


def setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"missing required setting: {name}")
    return value

"""Shared local validation helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_settings  # noqa: E402


def fail(message: str) -> NoReturn:
    print(f"FAIL  {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"OK    {message}")

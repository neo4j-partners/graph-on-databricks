"""Shared connection helpers for the Finance Genie Virtual Graph demos.

Every script here (``cli.py`` and the support scripts) reads the same Aura
credentials from the parent ``finance-genie/.env``. Set ``PROBE_ENV`` to point at a
different dotenv; ``probe.py`` and ``viz_check.py`` use that for ad-hoc targets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PARENT_ENV = Path(__file__).resolve().parents[2] / ".env"


def load_connection(env_file: Path | None = None) -> tuple[str, tuple[str, str]]:
    """Read Neo4j credentials from a dotenv and return ``(uri, auth)``.

    Resolves the dotenv in this order: the explicit ``env_file`` argument, then the
    ``PROBE_ENV`` environment variable, then the parent ``finance-genie/.env``. Exits
    with a clear message if the file is missing or any credential is unset.
    """
    if env_file is None:
        override = os.environ.get("PROBE_ENV")
        env_file = Path(override).expanduser() if override else PARENT_ENV
    if not env_file.is_file():
        sys.exit(f"Could not find env file at {env_file}")
    load_dotenv(env_file, override=True)

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    missing = [
        name
        for name, value in (
            ("NEO4J_URI", uri),
            ("NEO4J_USERNAME", username),
            ("NEO4J_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Missing required variables in {env_file}: {', '.join(missing)}")
    return uri, (username, password)

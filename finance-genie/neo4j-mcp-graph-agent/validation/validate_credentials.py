"""Validate the local AgentCore credentials file without Databricks access."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from _common import fail, load_settings, ok

REQUIRED = ("gateway_url", "client_id", "client_secret", "token_url", "scope")


def main() -> None:
    settings = load_settings()
    path = settings.agentcore_credentials_path
    if not path.is_file():
        fail(f"credentials file not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"credentials file is not valid JSON: {exc}")

    missing = [key for key in REQUIRED if not str(data.get(key, "")).strip()]
    if missing:
        fail(f"missing or empty fields: {', '.join(missing)}")

    parsed = urlparse(data["gateway_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail("gateway_url must be an absolute http(s) URL")
    parsed = urlparse(data["token_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail("token_url must be an absolute http(s) URL")

    ok(f"credentials file valid: {path}")


if __name__ == "__main__":
    main()

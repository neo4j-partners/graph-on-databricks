"""Validate the AgentCore MCP gateway directly from the local machine."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import requests

from _common import fail, load_settings, ok


def gateway_mcp_url(gateway_url: str) -> str:
    parsed = urlparse(gateway_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail("gateway_url must be an absolute http(s) URL")
    if parsed.path in {"", "/"}:
        return f"{parsed.scheme}://{parsed.netloc}/mcp"
    return gateway_url.rstrip("/")


def parse_mcp_response(response: requests.Response) -> dict:
    content_type = response.headers.get("Content-Type", "")
    if "event-stream" not in content_type:
        return response.json()
    data_lines = [
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    if not data_lines:
        fail(f"SSE response did not include data lines: {response.text[:300]}")
    return json.loads(data_lines[-1])


def load_credentials(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"credentials file not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"credentials file is not valid JSON: {exc}")

    required = ("gateway_url", "client_id", "client_secret", "token_url", "scope")
    missing = [key for key in required if not str(data.get(key, "")).strip()]
    if missing:
        fail(f"missing or empty fields: {', '.join(missing)}")
    return {key: str(data[key]).strip() for key in required}


def main() -> None:
    settings = load_settings()
    credentials_path = settings.agentcore_credentials_path
    credentials = load_credentials(credentials_path)
    mcp_url = gateway_mcp_url(credentials["gateway_url"])
    ok(f"credentials file valid: {credentials_path}")

    token_response = requests.post(
        credentials["token_url"],
        data={
            "grant_type": "client_credentials",
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "scope": credentials["scope"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if token_response.status_code != 200:
        host = urlparse(credentials["token_url"]).hostname
        fail(
            f"OAuth token exchange failed for {host}: "
            f"HTTP {token_response.status_code} {token_response.text[:300]}"
        )
    access_token = token_response.json().get("access_token")
    if not access_token:
        fail("OAuth response did not include access_token")
    ok("OAuth client_credentials flow returned an access token")

    response = requests.post(
        mcp_url,
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=30,
    )
    if response.status_code != 200:
        fail(
            "direct gateway tools/list failed: "
            f"HTTP {response.status_code} {response.text[:300]}"
        )

    payload = parse_mcp_response(response)
    tools = payload.get("result", {}).get("tools", [])
    if not tools:
        fail(f"direct gateway returned zero tools: {json.dumps(payload)[:500]}")
    ok(f"direct gateway returned {len(tools)} tools")
    for tool in tools:
        print(f"      - {tool.get('name')}")


if __name__ == "__main__":
    main()

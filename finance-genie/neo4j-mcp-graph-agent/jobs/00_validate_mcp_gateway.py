"""Databricks-side validation for AgentCore gateway and UC MCP proxy."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import requests
from databricks.sdk import WorkspaceClient

from _job_bootstrap import inject_params, setting

inject_params()


REQUIRED_SECRET_KEYS = (
    "gateway_host",
    "client_id",
    "client_secret",
    "token_endpoint",
    "oauth_scope",
)

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
        raise RuntimeError(f"SSE response did not include data lines: {response.text[:300]}")
    return json.loads(data_lines[-1])


def assert_tools(payload: dict, label: str) -> list[dict]:
    tools = payload.get("result", {}).get("tools", [])
    if not tools:
        raise RuntimeError(f"{label} returned zero tools: {json.dumps(payload)[:500]}")
    print(f"OK    {label} returned {len(tools)} tools")
    for tool in tools:
        print(f"      - {tool.get('name')}")
    return tools


def main() -> None:
    ws = WorkspaceClient()
    secret_scope = setting("MCP_SECRET_SCOPE")
    connection_name = setting("UC_CONNECTION_NAME")

    secrets = {
        key: ws.dbutils.secrets.get(scope=secret_scope, key=key)
        for key in REQUIRED_SECRET_KEYS
    }
    print(f"OK    loaded {len(secrets)} secrets from {secret_scope}")

    gateway_host = secrets["gateway_host"].rstrip("/")
    gateway_url = f"{gateway_host}/mcp"
    response = requests.get(gateway_url, timeout=10)
    if response.status_code >= 500:
        raise RuntimeError(
            f"gateway returned HTTP {response.status_code}: {response.text[:300]}"
        )
    print(f"OK    gateway reachable: HTTP {response.status_code}")

    token_response = requests.post(
        secrets["token_endpoint"],
        data={
            "grant_type": "client_credentials",
            "client_id": secrets["client_id"],
            "client_secret": secrets["client_secret"],
            "scope": secrets["oauth_scope"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if token_response.status_code != 200:
        host = urlparse(secrets["token_endpoint"]).hostname
        raise RuntimeError(
            f"OAuth token exchange failed for {host}: "
            f"HTTP {token_response.status_code} {token_response.text[:300]}"
        )
    access_token = token_response.json().get("access_token")
    if not access_token:
        raise RuntimeError("OAuth response did not include access_token")
    print("OK    OAuth client_credentials flow returned an access token")

    direct_response = requests.post(
        gateway_url,
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if direct_response.status_code != 200:
        raise RuntimeError(
            "direct gateway tools/list failed: "
            f"HTTP {direct_response.status_code} {direct_response.text[:300]}"
        )
    assert_tools(parse_mcp_response(direct_response), "direct gateway")

    host = ws.config.host.rstrip("/")
    proxy_url = f"{host}/api/2.0/mcp/external/{connection_name}"
    proxy_headers = ws.config.authenticate()
    proxy_headers["Content-Type"] = "application/json"
    proxy_response = requests.post(
        proxy_url,
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers=proxy_headers,
        timeout=30,
    )
    if proxy_response.status_code != 200:
        raise RuntimeError(
            "Databricks MCP proxy tools/list failed: "
            f"HTTP {proxy_response.status_code} {proxy_response.text[:300]}"
        )
    tools = assert_tools(parse_mcp_response(proxy_response), "UC MCP proxy")
    if not tools:
        raise RuntimeError(f"Databricks MCP proxy returned zero tools: {proxy_url}")


if __name__ == "__main__":
    main()

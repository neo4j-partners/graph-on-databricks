"""Smoke test the deployed Neo4j MCP agent endpoint."""

from __future__ import annotations

import json

import requests
from databricks.sdk import WorkspaceClient

from _job_bootstrap import inject_params, setting

inject_params()


def contains_tool_output(value: object) -> bool:
    if isinstance(value, dict):
        item_type = str(value.get("type", "")).lower()
        if "tool" in item_type or item_type in {"function_call", "function_call_output"}:
            return True
        if value.get("tool_call_id") or value.get("tool_name"):
            return True
        return any(contains_tool_output(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_tool_output(item) for item in value)
    return False


def main() -> None:
    ws = WorkspaceClient()
    endpoint_name = setting("MODEL_SERVING_ENDPOINT_NAME", "neo4j-mcp-agent")
    prompt = setting(
        "SMOKE_TEST_PROMPT",
        "What is the schema of the Neo4j database? Show node labels.",
    )
    headers: dict[str, str] = ws.config.authenticate()
    headers["Content-Type"] = "application/json"
    url = f"{ws.config.host.rstrip('/')}/serving-endpoints/{endpoint_name}/invocations"
    response = requests.post(
        url,
        headers=headers,
        json={"input": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2)[:4000])
    if not contains_tool_output(payload):
        raise RuntimeError("endpoint response did not contain a tool call result")
    print("OK    endpoint response contained a tool call result")


if __name__ == "__main__":
    main()

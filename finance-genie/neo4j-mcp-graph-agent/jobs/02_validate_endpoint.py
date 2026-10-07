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


def final_assistant_text(payload: dict) -> str:
    """Return the text of the last assistant message in a Responses payload."""
    for item in reversed(payload.get("output") or []):
        if item.get("type") == "message" and item.get("role") == "assistant":
            parts = item.get("content") or []
            text = "".join(
                part.get("text", "") for part in parts if isinstance(part, dict)
            )
            if text.strip():
                return text.strip()
    return ""


def tool_call_names(payload: dict) -> list[str]:
    return [
        str(item.get("name", ""))
        for item in payload.get("output") or []
        if item.get("type") == "function_call"
    ]


def has_error_item(payload: dict) -> bool:
    return bool(payload.get("error")) or any(
        item.get("type") == "error" for item in payload.get("output") or []
    )


def main() -> None:
    ws = WorkspaceClient()
    endpoint_name = setting("MODEL_SERVING_ENDPOINT_NAME", "neo4j-mcp-agent")
    prompt = setting(
        "SMOKE_TEST_PROMPT",
        "What is the schema of the Neo4j database? Show node labels.",
    )
    timeout = int(setting("SMOKE_TEST_TIMEOUT_SECONDS", "120"))
    headers: dict[str, str] = ws.config.authenticate()
    headers["Content-Type"] = "application/json"
    url = f"{ws.config.host.rstrip('/')}/serving-endpoints/{endpoint_name}/invocations"
    response = requests.post(
        url,
        headers=headers,
        json={"input": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2)[:4000])
    if not contains_tool_output(payload):
        raise RuntimeError("endpoint response did not contain a tool call result")
    print("OK    endpoint response contained a tool call result")

    if has_error_item(payload):
        raise RuntimeError("endpoint response contained an error item")
    print("OK    no error item in endpoint response")

    names = tool_call_names(payload)
    if not any("schema" in name.lower() or "cypher" in name.lower() for name in names):
        raise RuntimeError(f"no schema or cypher tool was called; calls: {names}")
    print(f"OK    schema/cypher tool called: {names}")

    if not final_assistant_text(payload):
        raise RuntimeError("final assistant message text was empty")
    print("OK    final assistant message was non-empty")


if __name__ == "__main__":
    main()

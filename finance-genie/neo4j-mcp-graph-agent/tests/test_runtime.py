import asyncio
import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agent.guardrails import (
    allowed_tool_filter,
    apply_mcp_guardrails,
    read_only_cypher_guardrail,
    truncate_result_guardrail,
)
from databricks_agentkit import DurableAgentServer
from databricks_agentkit.runtime.auth import InvocationAuthPolicy
from databricks_agentkit.runtime.store import RUNTIME_STORE_LOCAL_ENV, InMemoryRuntimeStore
from runtime import adapter
from runtime.adapter import _messages, _normalize_item, _tool_args
from runtime.identity import MEMORY_USER_FIELD, TRUSTED_CALLERS_ENV, MemoryIdentityMiddleware


def test_apply_mcp_guardrails_sets_all_controls():
    server = SimpleNamespace()
    apply_mcp_guardrails(server)
    assert server.tool_filter is allowed_tool_filter
    assert server.tool_input_guardrails == [read_only_cypher_guardrail]
    assert server.tool_output_guardrails == [truncate_result_guardrail]


def test_messages_accepts_list_or_object():
    messages = [{"role": "user", "content": "hi"}]
    assert _messages(messages) == messages
    assert _messages({"messages": messages}) == messages


@pytest.mark.parametrize("value", [None, {}, "text", {"messages": "x"}])
def test_messages_rejects_bad_input(value):
    with pytest.raises(ValueError):
        _messages(value)


def test_tool_args_parses_json_and_falls_back():
    assert _tool_args(SimpleNamespace(raw_item={"arguments": '{"query": "x"}'})) == {"query": "x"}
    assert _tool_args(SimpleNamespace(raw_item={"arguments": "not json"})) == {
        "arguments": "not json"
    }


def test_normalize_ignores_unknown_items():
    assert _normalize_item(object()) is None


def test_tool_result_carries_the_tool_name_from_its_call():
    from unittest.mock import MagicMock

    from agents.items import ToolCallItem, ToolCallOutputItem

    from runtime.adapter import _normalize_item

    call = MagicMock(spec=ToolCallItem)
    call.tool_name = "svc___read_neo4j_cypher"
    call.raw_item = {"call_id": "c1", "arguments": "{}"}
    result = MagicMock(spec=ToolCallOutputItem)
    result.raw_item = {"call_id": "c1"}
    result.output = "rows"

    names: dict[str, str] = {}
    _normalize_item(call, names)
    assert _normalize_item(result, names)["name"] == "svc___read_neo4j_cypher"


# Memory identity binding (runtime/identity.py)

SP_ID = "92051bdf-0000-0000-0000-000000000000"
ANALYST = "analyst-a@example.com"
MESSAGES = [{"role": "user", "content": "Which accounts act as hubs?"}]


@pytest.fixture
def deployed(monkeypatch):
    monkeypatch.setenv("DATABRICKS_APP_NAME", "neo4j-graph-agent")
    monkeypatch.delenv(RUNTIME_STORE_LOCAL_ENV, raising=False)
    monkeypatch.setenv(TRUSTED_CALLERS_ENV, f"other-sp, {SP_ID}")


@pytest.fixture
def local(monkeypatch):
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv(RUNTIME_STORE_LOCAL_ENV, raising=False)
    monkeypatch.setenv(TRUSTED_CALLERS_ENV, SP_ID)


def _scope(headers: dict[str, str], path: str = "/api/invocations", method: str = "POST") -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }


async def _call(
    headers: dict[str, str],
    body: dict | bytes,
    *,
    path: str = "/api/invocations",
    method: str = "POST",
    chunks: int = 1,
) -> tuple[dict | None, bytes | None, list[dict]]:
    """Run the middleware over a fake app. Returns (scope seen, body seen, messages sent)."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    size = -(-len(raw) // chunks)
    pending = [
        {"type": "http.request", "body": raw[i : i + size], "more_body": i + size < len(raw)}
        for i in range(0, len(raw), size)
    ]
    seen: dict = {}
    sent: list[dict] = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        parts = []
        while True:
            message = await receive()
            parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        seen["scope"], seen["body"] = scope, b"".join(parts)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    await MemoryIdentityMiddleware(app)(_scope(headers, path, method), receive, send)
    return seen.get("scope"), seen.get("body"), sent


def _bound_input(body: bytes) -> dict:
    return json.loads(body)["input"]


def _request(user_id: str | None = None, **extra) -> dict:
    payload = {"messages": MESSAGES, **extra}
    if user_id is not None:
        payload["user_id"] = user_id
    return {"id": str(uuid.uuid4()), "session_id": "s-1", "input": payload}


async def test_untrusted_caller_cannot_spoof_user_id(deployed):
    body = _request("analyst-b@example.com", memory_user_id="analyst-b@example.com")
    scope, seen, _ = await _call({"X-Forwarded-Email": ANALYST}, body)
    assert _bound_input(seen)[MEMORY_USER_FIELD] == ANALYST
    assert dict(scope["headers"])[b"content-length"] == str(len(seen)).encode()


async def test_allowlisted_caller_user_id_is_honored(deployed):
    _, seen, _ = await _call({"X-Forwarded-Email": SP_ID}, _request("nams-load-user-0001"))
    assert _bound_input(seen)[MEMORY_USER_FIELD] == "nams-load-user-0001"


async def test_allowlisted_caller_without_user_id_binds_its_principal(deployed):
    _, seen, _ = await _call({"X-Forwarded-Email": SP_ID}, _request())
    assert _bound_input(seen)[MEMORY_USER_FIELD] == SP_ID


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Forwarded-Email": ANALYST, "X-Forwarded-User": f"  {SP_ID} "},
        {"X-Forwarded-Email": ANALYST, "X-Forwarded-Preferred-Username": SP_ID},
    ],
)
async def test_allowlist_matches_any_identity_header_after_strip(deployed, headers):
    _, seen, _ = await _call(headers, _request("nams-load-user-0002"))
    assert _bound_input(seen)[MEMORY_USER_FIELD] == "nams-load-user-0002"


async def test_allowlist_is_an_exact_match(deployed, monkeypatch):
    monkeypatch.setenv(TRUSTED_CALLERS_ENV, "sp-id")
    for principal in ("sp-id-extra", "sp-i", "xsp-id"):
        _, seen, _ = await _call({"X-Forwarded-Email": principal}, _request("victim"))
        assert _bound_input(seen)[MEMORY_USER_FIELD] == principal


async def test_principal_falls_back_to_forwarded_user(deployed):
    _, seen, _ = await _call({"X-Forwarded-User": "12345@6789"}, _request("victim"))
    assert _bound_input(seen)[MEMORY_USER_FIELD] == "12345@6789"


async def test_missing_identity_fails_closed(deployed):
    scope, _, sent = await _call({"X-Forwarded-Email": "  "}, _request("victim"))
    assert scope is None
    assert sent[0]["status"] == 401
    error = json.loads(sent[1]["body"])["error"]
    assert error["code"] == "MEMORY_USER_IDENTITY_MISSING"
    assert error["message"]


async def test_local_uses_body_user_id_and_ignores_headers(local):
    body = _request("analyst-7", memory_user_id="someone-else")
    _, seen, _ = await _call({"X-Forwarded-Email": ANALYST}, body)
    assert _bound_input(seen)[MEMORY_USER_FIELD] == "analyst-7"


async def test_local_without_user_id_leaves_identity_unset(local):
    _, seen, _ = await _call({}, _request(memory_user_id="someone-else"))
    assert MEMORY_USER_FIELD not in _bound_input(seen)


async def test_list_input_is_wrapped_without_changing_messages(deployed):
    body = {"id": str(uuid.uuid4()), "session_id": "s-1", "input": MESSAGES}
    _, seen, _ = await _call({"X-Forwarded-Email": ANALYST}, body)
    wrapped = _bound_input(seen)
    assert wrapped[MEMORY_USER_FIELD] == ANALYST
    assert adapter._messages(wrapped) == adapter._messages(MESSAGES) == MESSAGES


async def test_missing_input_binds_the_callers_own_identity(deployed):
    body = {"id": str(uuid.uuid4()), "session_id": "analyst-b@example.com"}
    _, seen, _ = await _call({"X-Forwarded-Email": ANALYST}, body)
    assert _bound_input(seen) == {"messages": [], MEMORY_USER_FIELD: ANALYST}


async def test_body_split_across_chunks_is_reassembled(deployed):
    body = _request("victim")
    _, seen, _ = await _call({"X-Forwarded-Email": ANALYST}, body, chunks=2)
    bound = _bound_input(seen)
    assert bound[MEMORY_USER_FIELD] == ANALYST
    assert bound["messages"] == MESSAGES


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/invocations/abc"), ("POST", "/api/other"), ("GET", "/api/invocations")],
)
async def test_other_routes_are_untouched(deployed, method, path):
    body = json.dumps(_request("victim")).encode()
    scope, seen, sent = await _call({}, body, path=path, method=method)
    assert seen == body
    assert scope["headers"] == []
    assert sent[0]["status"] == 200


async def test_unparseable_body_passes_through(deployed):
    _, seen, _ = await _call({"X-Forwarded-Email": ANALYST}, b"not json")
    assert seen == b"not json"


async def test_bound_identity_is_logged_without_the_token(deployed, caplog):
    headers = {"X-Forwarded-Email": ANALYST, "X-Forwarded-Access-Token": "secret-token"}
    with caplog.at_level(logging.INFO, logger="runtime.identity"):
        await _call(headers, _request("victim"))
    [record] = [r for r in caplog.records if r.name == "runtime.identity"]
    assert ANALYST in record.getMessage()
    assert "x-forwarded-email" in record.getMessage()
    assert "secret-token" not in caplog.text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"memory_user_id": "analyst-7", "user_id": "spoofed"}, "analyst-7"),
        ({"user_id": "spoofed"}, "s-1"),
        ({"memory_user_id": "bad id!\n"}, "badid"),
        (MESSAGES, "s-1"),
    ],
)
def test_adapter_reads_only_the_bound_identity(value, expected):
    assert adapter._user_id(value, "s-1") == expected


def test_recovery_keeps_the_identity_bound_at_request_time(deployed, monkeypatch):
    store = InMemoryRuntimeStore()
    server = DurableAgentServer(runtime_store=store, auth_policy=InvocationAuthPolicy())
    server.add_middleware(MemoryIdentityMiddleware)

    @server.invoke
    async def _invoke(value, context):
        return {"output": [], "status": "completed"}

    body = _request("analyst-b@example.com")
    with TestClient(server) as client:
        response = client.post(
            "/api/invocations", json=body, headers={"X-Forwarded-Email": ANALYST}
        )
        assert response.status_code == 200
        # The same id from another principal is a different request, so the store refuses it.
        retry = client.post("/api/invocations", json=body, headers={"X-Forwarded-Email": SP_ID})
        assert retry.status_code == 409

    persisted = store.states[body["id"]].request["input"]
    assert persisted[MEMORY_USER_FIELD] == ANALYST

    bound: list[str] = []

    async def capture(messages, context, user_id):
        bound.append(user_id)
        return {"output": [], "status": "completed"}

    monkeypatch.setattr(adapter, "_invoke_agent", capture)
    # A recovery attempt has no live request, so only the persisted input can carry the identity.
    monkeypatch.delenv("DATABRICKS_APP_NAME")
    context = SimpleNamespace(session_id="s-1", is_recovery=True)
    asyncio.run(adapter.recover(persisted, context))
    assert bound == ["analyst-a@example.com"]

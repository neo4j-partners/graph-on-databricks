import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ontology" / "replay_transcripts.py"
_spec = importlib.util.spec_from_file_location("replay_transcripts", SCRIPT)
rt = importlib.util.module_from_spec(_spec)
sys.modules["replay_transcripts"] = rt
_spec.loader.exec_module(rt)

SECRET = "nams_secret_key_value"


class FakeNams:
    """A tiny in-memory NAMS that records every request and serves the routes used."""

    def __init__(self, conversations=None, messages=None, traces=None, statuses=None):
        self.requests: list[tuple[str, str, dict | None]] = []
        self.conversations = conversations or []
        self.messages = messages or {}  # id -> list newest first
        self.traces = traces or {}
        self.statuses = statuses or {}  # id -> list of lists of statuses, popped per poll
        self.created = 0
        self.fail = {}  # (method, path) -> status

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.requests.append((request.method, path, body))
        if (request.method, path) in self.fail:
            return httpx.Response(self.fail[(request.method, path)], json={})
        if request.method == "GET" and path == "/v1/conversations":
            cursor = request.url.params.get("cursor")
            if cursor == "p2":
                return httpx.Response(200, json={"conversations": self.conversations[1:]})
            if len(self.conversations) > 1 and not cursor:
                return httpx.Response(
                    200, json={"conversations": self.conversations[:1], "next_cursor": "p2"}
                )
            return httpx.Response(200, json={"conversations": self.conversations})
        if request.method == "GET" and path.endswith("/messages"):
            cid = path.split("/")[3]
            return httpx.Response(200, json={"messages": self.messages.get(cid, [])})
        if request.method == "GET" and path.startswith("/v1/reasoning/trace/"):
            cid = path.rsplit("/", 1)[1]
            return httpx.Response(
                200, json=self.traces.get(cid, {"conversationId": cid, "steps": [], "toolCalls": []})
            )
        if request.method == "GET" and path.endswith("/extraction-status"):
            cid = path.split("/")[3]
            queue = self.statuses.get(cid, [["done"]])
            current = queue.pop(0) if len(queue) > 1 else queue[0]
            return httpx.Response(200, json={"messages": [{"status": s} for s in current]})
        if request.method == "POST":
            self.created += 1
            return httpx.Response(201, json={"id": f"new-{self.created}"})
        raise AssertionError(f"unexpected {request.method} {path}")

    def methods(self):
        return {m for m, _, _ in self.requests}


def seeded_server() -> FakeNams:
    convs = [
        {
            "id": "c2",
            "userId": "nams-load-r1-user-0001",
            "createdAt": "2026-01-02T00:00:00Z",
            "messageCount": 2,
            "metadata": {
                "client_session_id": "nams-load-r1-u0001-s001",
                "user_id": "nams-load-r1-user-0001",
                "source": "neo4j-mcp-graph-agent",
            },
        },
        {
            "id": "c1",
            "userId": "other",
            "createdAt": "2026-01-01T00:00:00Z",
            "messageCount": 1,
            "metadata": {"client_session_id": "different-run"},
        },
    ]
    messages = {
        "c2": [
            {"role": "assistant", "content": "Account 7890 is a hub.", "metadata": {}},
            {"role": "user", "content": "who is a hub?", "metadata": {}},
        ],
        "c1": [{"role": "user", "content": "hi", "metadata": {}}],
    }
    traces = {
        "c2": {
            "conversationId": "c2",
            "steps": [
                {"id": "s2", "reasoning": "queried", "actionTaken": "read_neo4j_cypher",
                 "createdAt": "2026-01-02T00:00:02Z"},
                {"id": "s1", "reasoning": "schema", "actionTaken": "get_neo4j_schema",
                 "createdAt": "2026-01-02T00:00:01Z"},
            ],
            "toolCalls": [
                {"id": "t1", "stepId": "s1", "toolName": "get_neo4j_schema", "input": "{}",
                 "status": "success", "createdAt": "2026-01-02T00:00:01Z"},
                {"id": "t2", "stepId": "s2", "toolName": "read_neo4j_cypher",
                 "input": "{\"query\": \"RETURN 1\"}", "output": "[1]", "status": "success",
                 "durationMs": 12, "createdAt": "2026-01-02T00:00:02Z"},
                {"id": "t3", "toolName": "orphan", "input": "{}", "createdAt": "2026-01-02T00:00:03Z"},
            ],
        }
    }
    return FakeNams(convs, messages, traces)


def client_for(server: FakeNams) -> httpx.Client:
    return rt.make_client(SECRET, "https://nams.test", server.transport())


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_API_KEY", SECRET)
    monkeypatch.setenv("MEMORY_ENDPOINT", "https://nams.test")
    monkeypatch.setattr(rt, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(rt.time, "sleep", lambda _s: None)


@pytest.fixture
def server(env, monkeypatch):
    srv = seeded_server()
    real = rt.make_client
    monkeypatch.setattr(
        rt, "make_client", lambda key, endpoint, transport=None: real(key, endpoint, srv.transport())
    )
    return srv


def exported(server: FakeNams, **kwargs) -> dict:
    with client_for(server) as client:
        return rt.export_transcripts(client, "https://nams.test", kwargs.get("prefix"), kwargs.get("expect"))


# ---- export ----


def test_export_orders_messages_steps_and_groups_tool_calls():
    doc = exported(seeded_server())
    assert doc["format"] == rt.FORMAT
    assert [c["source_conversation_id"] for c in doc["conversations"]] == ["c1", "c2"]
    conv = doc["conversations"][1]
    assert [(m["role"], m["content"]) for m in conv["messages"]] == [
        ("user", "who is a hub?"),
        ("assistant", "Account 7890 is a hub."),
    ]
    steps = conv["trace"]["steps"]
    assert [s["action"] for s in steps] == ["get_neo4j_schema", "read_neo4j_cypher"]
    assert steps[1]["tool_calls"] == [
        {"tool_name": "read_neo4j_cypher", "input": "{\"query\": \"RETURN 1\"}",
         "output": "[1]", "status": "success", "duration_ms": 12}
    ]
    assert [c["tool_name"] for c in conv["trace"]["unlinked_tool_calls"]] == ["orphan"]
    assert conv["session_id"] == "nams-load-r1-u0001-s001"
    assert conv["user_id"] == "nams-load-r1-user-0001"


def test_export_is_get_only_and_follows_cursor():
    server = seeded_server()
    exported(server)
    assert server.methods() == {"GET"}
    assert ("GET", "/v1/conversations", None) in server.requests
    assert sum(1 for _, p, _ in server.requests if p == "/v1/conversations") == 2


def test_export_prefix_filters_conversations():
    doc = exported(seeded_server(), prefix="nams-load-r1")
    assert [c["source_conversation_id"] for c in doc["conversations"]] == ["c2"]


def test_export_expect_turns_mismatch_fails():
    with pytest.raises(rt.ReplayError, match="expected 5 turn"):
        exported(seeded_server(), expect=5)
    assert len(exported(seeded_server(), expect=2)["conversations"]) == 2


def test_export_refuses_truncated_conversation():
    server = seeded_server()
    server.conversations[0]["messageCount"] = 500
    with pytest.raises(rt.ReplayError, match="at most 200"):
        exported(server)


def test_export_http_error_names_status_not_key():
    server = seeded_server()
    server.fail[("GET", "/v1/conversations")] = 401
    with pytest.raises(rt.ReplayError) as info:
        exported(server)
    assert "401" in str(info.value) and SECRET not in str(info.value)


def test_cmd_export_writes_file_and_prints_counts(server, tmp_path, capsys):
    out = tmp_path / "t.json"
    assert rt.main(["export", "--out", str(out)]) == 0
    stdout = capsys.readouterr().out
    assert "exported 2 conversation(s), 3 message(s), 2 step(s), 3 tool call(s)" in stdout
    assert SECRET not in stdout and SECRET not in out.read_text()
    assert json.loads(out.read_text())["format"] == rt.FORMAT


# ---- replay ----


def write_export(server, tmp_path) -> Path:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(exported(server)))
    return path


def test_dry_run_makes_no_network_call_and_prints_counts_only(monkeypatch, tmp_path, capsys):
    path = write_export(seeded_server(), tmp_path)
    monkeypatch.delenv("MEMORY_API_KEY", raising=False)
    monkeypatch.setattr(rt, "ENV_FILE", tmp_path / "none.env")

    def boom(*_a, **_k):
        raise AssertionError("network used")

    monkeypatch.setattr(rt.httpx, "Client", boom)
    assert rt.main(["replay", str(path)]) == 0
    out = capsys.readouterr().out
    assert "2 conversation(s), 3 message(s), 2 step(s), 3 tool call(s)" in out
    assert "7890" not in out and "who is a hub" not in out


def test_execute_writes_same_text_in_trace_order_with_suffix(server, tmp_path):
    path = write_export(server, tmp_path)
    server.requests.clear()
    server.conversations, server.messages, server.traces = [], {}, {}
    assert rt.main(["replay", str(path), "--execute", "--label", "v2", "--session-suffix=-r7"]) == 0
    writes = [(m, p, b) for m, p, b in server.requests if m == "POST"]
    paths = [p for _, p, _ in writes]
    # Conversation c1: create, 1 user message. Conversation c2: create, user, 2 steps with
    # tool calls (plus one unlinked), then the assistant message.
    assert paths == [
        "/v1/conversations",
        "/v1/conversations/new-1/messages",
        "/v1/conversations",
        "/v1/conversations/new-3/messages",
        "/v1/reasoning/steps",
        "/v1/reasoning/tool-calls",
        "/v1/reasoning/steps",
        "/v1/reasoning/tool-calls",
        "/v1/reasoning/tool-calls",
        "/v1/conversations/new-3/messages",
    ]
    create = writes[2][2]
    assert create["userId"] == "nams-load-r1-user-0001-r7"
    assert create["metadata"]["client_session_id"] == "nams-load-r1-u0001-s001-r7"
    assert create["metadata"]["user_id"] == "nams-load-r1-user-0001-r7"
    assert create["metadata"]["replay_label"] == "v2"
    assert create["metadata"]["replay_source_conversation_id"] == "c2"
    assert writes[3][2] == {"role": "user", "content": "who is a hub?"}
    assert writes[9][2] == {"role": "assistant", "content": "Account 7890 is a hub."}
    step = writes[4][2]
    assert step == {"conversationId": "new-3", "reasoning": "schema", "actionTaken": "get_neo4j_schema"}
    call = writes[7][2]
    assert call == {"toolName": "read_neo4j_cypher", "input": "{\"query\": \"RETURN 1\"}",
                    "stepId": "new-7", "status": "success", "output": "[1]", "durationMs": 12}
    assert "stepId" not in writes[8][2]


def test_keep_user_id_leaves_user_untouched(server, tmp_path):
    path = write_export(server, tmp_path)
    server.conversations, server.messages, server.traces = [], {}, {}
    server.requests.clear()
    assert rt.main(["replay", str(path), "--execute", "--keep-user-id"]) == 0
    create = next(b for m, p, b in server.requests if m == "POST" and p == "/v1/conversations" and b.get("userId") != "other")
    assert create["userId"] == "nams-load-r1-user-0001"
    assert create["metadata"]["user_id"] == "nams-load-r1-user-0001"
    assert create["metadata"]["client_session_id"].endswith("-r1")


def test_second_replay_with_same_suffix_is_refused(server, tmp_path, capsys):
    path = write_export(server, tmp_path)
    server.conversations = [
        {"id": "x", "metadata": {"client_session_id": "different-run-r1"}},
    ]
    server.requests.clear()
    assert rt.main(["replay", str(path), "--execute"]) == 1
    assert "choose a different --session-suffix" in capsys.readouterr().err
    assert "POST" not in server.methods()


def test_execute_reports_partial_progress_on_failure(server, tmp_path, capsys):
    path = write_export(server, tmp_path)
    server.conversations, server.messages, server.traces = [], {}, {}
    server.fail[("POST", "/v1/reasoning/steps")] = 500
    assert rt.main(["replay", str(path), "--execute"]) == 1
    err = capsys.readouterr().err
    assert "wrote before failing: 2 conversation(s), 2 message(s), 0 step(s)" in err
    assert SECRET not in err


def test_post_retries_only_429():
    server = FakeNams()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429 if len(calls) == 1 else 201, json={"id": "ok"})

    with rt.make_client(SECRET, "https://nams.test", httpx.MockTransport(handler)) as client:
        assert rt.api_post(client, "/v1/conversations", {}, sleep=lambda _s: None) == {"id": "ok"}
    assert len(calls) == 2

    def failing(request):
        calls.append("x")
        return httpx.Response(500, json={})

    calls.clear()
    with rt.make_client(SECRET, "https://nams.test", httpx.MockTransport(failing)) as client:
        with pytest.raises(rt.ReplayError):
            rt.api_post(client, "/v1/conversations", {}, sleep=lambda _s: None)
    assert len(calls) == 1
    assert server.requests == []


def test_dry_run_and_execute_together_is_an_error(tmp_path, capsys):
    path = write_export(seeded_server(), tmp_path) if False else tmp_path / "t.json"
    path.write_text(json.dumps({"format": rt.FORMAT, "conversations": []}))
    assert rt.main(["replay", str(path), "--dry-run", "--execute"]) == 1
    assert "mutually exclusive" in capsys.readouterr().err


def test_bad_transcript_file_is_rejected(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"conversations": []}))
    assert rt.main(["replay", str(path)]) == 1
    assert "not a nams-transcripts/1" in capsys.readouterr().err


def test_empty_suffix_is_rejected(tmp_path, capsys):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"format": rt.FORMAT, "conversations": []}))
    assert rt.main(["replay", str(path), "--session-suffix="]) == 1


# ---- wait ----


def test_wait_polls_only_replayed_conversations_until_settled():
    server = FakeNams(statuses={"a": [["pending", "done"], ["done", "failed"]], "b": [["done"]]})
    clock = iter(range(0, 1000, 1))
    with client_for(server) as client:
        summary = rt.wait_for_extraction(
            client, ["a", "b"], 100, 1, sleep=lambda _s: None,
            clock=lambda: float(next(clock)), log=lambda _m: None,
        )
    assert summary == {"conversations": 2, "failed_messages": 1}
    polled = [p for _, p, _ in server.requests]
    assert polled.count("/v1/conversations/a/extraction-status") == 2
    assert polled.count("/v1/conversations/b/extraction-status") == 1


def test_wait_times_out():
    server = FakeNams(statuses={"a": [["processing"]]})
    ticks = iter([0.0, 5.0, 50.0, 500.0])
    with client_for(server) as client:
        with pytest.raises(rt.ExtractionTimeout):
            rt.wait_for_extraction(
                client, ["a"], 10, 1, sleep=lambda _s: None,
                clock=lambda: next(ticks), log=lambda _m: None,
            )


def test_execute_with_wait_prints_extraction_summary(server, tmp_path, capsys):
    path = write_export(server, tmp_path)
    server.conversations, server.messages, server.traces = [], {}, {}
    assert rt.main(["replay", str(path), "--execute", "--wait", "--poll-interval", "0"]) == 0
    out = capsys.readouterr().out
    assert "replayed 2 conversation(s), 3 message(s), 2 step(s), 3 tool call(s)" in out
    assert "extraction finished for 2 conversation(s), 0 failed message(s)" in out


def test_missing_key_on_execute_fails_clearly(monkeypatch, tmp_path, capsys):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"format": rt.FORMAT, "conversations": []}))
    monkeypatch.delenv("MEMORY_API_KEY", raising=False)
    monkeypatch.setattr(rt, "ENV_FILE", tmp_path / "none.env")
    assert rt.main(["replay", str(path), "--execute"]) == 1
    assert "MEMORY_API_KEY is not set" in capsys.readouterr().err

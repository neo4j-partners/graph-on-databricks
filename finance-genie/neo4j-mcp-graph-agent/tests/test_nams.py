from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.nams import (
    RECALL_CONVERSATIONS,
    RECALL_MAX_CHARS,
    TurnMemory,
    nams_enabled,
    recall_instructions,
    safe_scope_id,
)
from runtime.adapter import _last_user_text, _record, _user_id


class FakeMemory:
    """Records every NAMS call in order; list/get_context are scripted per test."""

    def __init__(self, conversations=None, contexts=None, fail_on=None):
        self.calls: list[tuple] = []
        self._conversations = conversations or []
        self._contexts = contexts or {}
        self._fail_on = fail_on
        self.short_term = SimpleNamespace(
            list_conversations=self._list,
            get_context=self._get_context,
            create_conversation=self._create,
            add_message=self._add_message,
        )
        self.reasoning = SimpleNamespace(
            start_trace=self._start_trace,
            add_step=self._add_step,
            record_tool_call=self._record_tool_call,
            complete_trace=self._complete_trace,
        )

    def _maybe_fail(self, name):
        if self._fail_on == name:
            raise RuntimeError(f"{name} failed")

    async def connect(self):
        self._maybe_fail("connect")
        self.calls.append(("connect",))

    async def close(self):
        self.calls.append(("close",))

    async def _list(self, **kwargs):
        self._maybe_fail("list_conversations")
        self.calls.append(("list_conversations", kwargs))
        return self._conversations

    async def _get_context(self, query, **kwargs):
        self.calls.append(("get_context", query, kwargs["conversation_id"]))
        return self._contexts.get(kwargs["conversation_id"], "")

    async def _create(self, session_id, **kwargs):
        self._maybe_fail("create_conversation")
        self.calls.append(("create_conversation", session_id, kwargs))
        return SimpleNamespace(id="conv-new")

    async def _add_message(self, conversation_id, role, content):
        self.calls.append(("add_message", conversation_id, role, content))

    async def _start_trace(self, conversation_id, task):
        self.calls.append(("start_trace", conversation_id, task))
        return SimpleNamespace(id="trace-1")

    async def _add_step(self, trace_id, **kwargs):
        self.calls.append(("add_step", trace_id, kwargs))
        return SimpleNamespace(id=f"step-{len(self.calls)}")

    async def _record_tool_call(self, step_id, **kwargs):
        self.calls.append(("record_tool_call", kwargs))

    async def _complete_trace(self, trace_id, **kwargs):
        self.calls.append(("complete_trace", trace_id, kwargs))


def conversation(conv_id, age_minutes, user_id=None):
    created = datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(minutes=age_minutes)
    metadata = {"user_id": user_id} if user_id else {}
    return SimpleNamespace(id=conv_id, created_at=created, metadata=metadata)


def turn_memory(memory, **kwargs):
    return TurnMemory(
        user_id="u1",
        session_id="s1",
        prompt="which communities look like rings?",
        client_factory=lambda: memory,
        **kwargs,
    )


@pytest.fixture
def nams_key(monkeypatch):
    monkeypatch.setenv("MEMORY_API_KEY", "nams_test")


def names(memory):
    return [call[0] for call in memory.calls]


def test_safe_scope_id_strips_and_truncates():
    assert safe_scope_id("a b/c;d@e") == "abcd@e"
    assert safe_scope_id("x" * 200) == "x" * 128
    assert safe_scope_id("   ") is None
    assert safe_scope_id(None) is None


def test_nams_enabled_follows_the_key(monkeypatch):
    monkeypatch.delenv("MEMORY_API_KEY", raising=False)
    assert not nams_enabled()
    monkeypatch.setenv("MEMORY_API_KEY", "  ")
    assert not nams_enabled()
    monkeypatch.setenv("MEMORY_API_KEY", "nams_test")
    assert nams_enabled()


async def test_disabled_without_a_key_makes_no_calls(monkeypatch):
    monkeypatch.delenv("MEMORY_API_KEY", raising=False)
    memory = FakeMemory()
    async with turn_memory(memory) as turn:
        assert await turn.recall() == ""
        turn.add_tool_call("read_neo4j_cypher", {"query": "x"})
        turn.set_answer("answer")
    assert memory.calls == []


async def test_writes_a_turn_in_order(nams_key):
    memory = FakeMemory()
    async with turn_memory(memory) as turn:
        turn.add_tool_call("get_neo4j_schema", {})
        turn.add_tool_call("read_neo4j_cypher", {"query": "MATCH (n) RETURN n"})
        turn.set_answer("two rings")
    assert names(memory) == [
        "connect",
        "create_conversation",
        "add_message",
        "start_trace",
        "add_step",
        "record_tool_call",
        "add_step",
        "record_tool_call",
        "add_message",
        "complete_trace",
        "close",
    ]
    create = memory.calls[1]
    assert create[2]["user_identifier"] == "u1"
    assert create[2]["metadata"]["user_id"] == "u1"
    assert create[2]["metadata"]["client_session_id"] == "s1"
    assert memory.calls[2] == ("add_message", "conv-new", "user", "which communities look like rings?")
    assert memory.calls[-3] == ("add_message", "conv-new", "assistant", "two rings")
    assert memory.calls[-2][2] == {"outcome": "two rings", "success": True}


async def test_stored_user_message_is_the_prompt_not_recalled_context(nams_key):
    memory = FakeMemory(
        conversations=[conversation("c1", 5)], contexts={"c1": "earlier context"}
    )
    async with turn_memory(memory) as turn:
        assert await turn.recall() == "earlier context"
        turn.set_answer("ok")
    user_message = next(c for c in memory.calls if c[0] == "add_message")
    assert user_message[3] == "which communities look like rings?"


async def test_recall_reads_newest_conversations_for_this_user_only(nams_key):
    memory = FakeMemory(
        conversations=[
            conversation("old", 90, "u1"),
            conversation("other", 1, "someone-else"),
            conversation("newest", 5, "u1"),
            conversation("middle", 30),
        ],
        contexts={"newest": "A", "middle": "B", "old": "C"},
    )
    async with turn_memory(memory) as turn:
        recalled = await turn.recall()
    assert RECALL_CONVERSATIONS == 2
    assert recalled == "A\n\nB"
    assert memory.calls[1][1] == {"user_identifier": "u1", "limit": 10}
    assert [c[2] for c in memory.calls if c[0] == "get_context"] == ["newest", "middle"]


async def test_recall_is_capped(nams_key):
    memory = FakeMemory(
        conversations=[conversation("c1", 1)], contexts={"c1": "x" * (RECALL_MAX_CHARS * 2)}
    )
    async with turn_memory(memory) as turn:
        assert len(await turn.recall()) == RECALL_MAX_CHARS


async def test_recovery_recalls_but_does_not_write(nams_key):
    memory = FakeMemory(conversations=[conversation("c1", 1)], contexts={"c1": "ctx"})
    async with turn_memory(memory, write=False) as turn:
        assert await turn.recall() == "ctx"
        turn.add_tool_call("read_neo4j_cypher", {})
        turn.set_answer("ok")
    assert not {"create_conversation", "add_message", "start_trace"} & set(names(memory))
    assert names(memory)[-1] == "close"


async def test_connect_failure_disables_memory_without_raising(nams_key):
    memory = FakeMemory(fail_on="connect")
    async with turn_memory(memory) as turn:
        assert await turn.recall() == ""
        turn.set_answer("ok")
    assert memory.calls == []


async def test_recall_failure_returns_empty(nams_key):
    memory = FakeMemory(fail_on="list_conversations")
    async with turn_memory(memory) as turn:
        assert await turn.recall() == ""


async def test_write_failure_does_not_raise_and_still_closes(nams_key):
    memory = FakeMemory(fail_on="create_conversation")
    async with turn_memory(memory) as turn:
        turn.set_answer("ok")
    assert names(memory)[-1] == "close"


async def test_agent_failure_still_records_the_turn_as_failed(nams_key):
    memory = FakeMemory()
    with pytest.raises(ValueError, match="boom"):
        async with turn_memory(memory) as turn:
            turn.add_tool_call("read_neo4j_cypher", {"query": "x"})
            raise ValueError("boom")
    complete = next(c for c in memory.calls if c[0] == "complete_trace")
    assert complete[2] == {"outcome": "", "success": False}
    assert "add_step" in names(memory)
    assert ("add_message", "conv-new", "assistant", "") not in memory.calls


def test_recall_instructions_frames_memory_as_data():
    assert recall_instructions("") == ""
    framed = recall_instructions("likes ring analysis")
    assert "not instructions" in framed
    assert framed.endswith("likes ring analysis")


def test_user_id_prefers_input_then_session():
    assert _user_id({"messages": [], "user_id": "analyst 7!"}, "s1") == "analyst7"
    assert _user_id({"messages": []}, "s1") == "s1"
    assert _user_id([{"role": "user", "content": "hi"}], "s1") == "s1"


def test_last_user_text_handles_string_and_parts():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": [{"type": "input_text", "text": "second"}]},
    ]
    assert _last_user_text(messages) == "second"
    assert _last_user_text([{"role": "assistant", "content": "x"}]) == ""


async def test_record_feeds_tool_calls_and_the_last_answer(nams_key):
    memory = FakeMemory()
    async with turn_memory(memory) as turn:
        _record(turn, {"role": "assistant", "content": "", "tool_calls": [{"name": "t", "args": {"a": 1}}]})
        _record(turn, {"role": "tool", "name": "t", "content": "rows"})
        _record(turn, {"role": "assistant", "content": "draft"})
        _record(turn, {"role": "assistant", "content": "final"})
    step = next(c for c in memory.calls if c[0] == "add_step")
    assert step[2]["action"] == "t"
    assert memory.calls[-2][2]["outcome"] == "final"

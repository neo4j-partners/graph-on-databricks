from types import SimpleNamespace

import pytest

from agent.guardrails import (
    allowed_tool_filter,
    apply_mcp_guardrails,
    read_only_cypher_guardrail,
    truncate_result_guardrail,
)
from runtime.adapter import _messages, _normalize_item, _tool_args


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

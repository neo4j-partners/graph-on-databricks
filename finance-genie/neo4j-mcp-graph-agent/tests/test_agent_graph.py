from __future__ import annotations

from collections.abc import Iterator

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError

from neo4j_mcp_graph_agent import GuardrailMiddleware, build_agent

CALLS: list[tuple[str, str]] = []


class ScriptedChat(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@tool("read-cypher")
def read_cypher(query: str) -> str:
    """Run a read-only Cypher query."""
    CALLS.append(("read-cypher", query))
    return "[{'n': 42}]"


@tool("get-schema")
def get_schema() -> str:
    """Return the graph schema."""
    CALLS.append(("get-schema", ""))
    return "Account"


@tool("write-cypher")
def write_cypher(query: str) -> str:
    """Run a write Cypher query."""
    CALLS.append(("write-cypher", query))
    return "written"


TOOLS = [read_cypher, get_schema, write_cypher]


@pytest.fixture(autouse=True)
def _clear_calls() -> None:
    CALLS.clear()


def tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def run(messages: Iterator[AIMessage], limit: int = 25) -> dict:
    agent = build_agent(TOOLS, llm=ScriptedChat(messages=messages))
    return agent.invoke(
        {"messages": [HumanMessage("question")]},
        config={"recursion_limit": limit},
    )


def tool_messages(result: dict) -> list[ToolMessage]:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


def test_read_cypher_runs_and_answers() -> None:
    result = run(
        iter(
            [
                tool_call("read-cypher", {"query": "MATCH (n) RETURN count(n)"}),
                AIMessage(content="There are 42 nodes."),
            ]
        )
    )
    assert CALLS == [("read-cypher", "MATCH (n) RETURN count(n)")]
    assert result["messages"][-1].content == "There are 42 nodes."


def test_disallowed_write_tool_rejected_without_executing() -> None:
    result = run(
        iter(
            [
                tool_call("write-cypher", {"query": "MATCH (n) DETACH DELETE n"}),
                AIMessage(content="I cannot modify the database."),
            ]
        )
    )
    assert CALLS == []
    assert tool_messages(result)
    assert result["messages"][-1].content == "I cannot modify the database."


def test_guardrail_rejects_disallowed_tool_at_call_time() -> None:
    executed: list[str] = []

    def handler(request: ToolCallRequest) -> ToolMessage:
        executed.append(request.tool_call["name"])
        return ToolMessage(content="ran", tool_call_id=request.tool_call["id"])

    request = ToolCallRequest(
        tool_call={
            "name": "write-cypher",
            "args": {"query": "MATCH (n) DETACH DELETE n"},
            "id": "w1",
        },
        tool=None,
        state={},
        runtime=None,
    )
    rejected = GuardrailMiddleware().wrap_tool_call(request, handler)

    assert executed == []
    assert rejected.status == "error"
    assert "not permitted" in rejected.content


def test_write_cypher_via_read_tool_rejected_without_executing() -> None:
    result = run(
        iter(
            [
                tool_call("read-cypher", {"query": "MATCH (n) DETACH DELETE n"}),
                AIMessage(content="That was rejected."),
            ]
        )
    )
    assert CALLS == []
    rejected = tool_messages(result)
    assert rejected
    assert rejected[0].status == "error"


def endless_tool_calls() -> Iterator[AIMessage]:
    index = 0
    while True:
        index += 1
        yield tool_call("get-schema", {}, call_id=f"c{index}")


def test_endless_tool_loop_ends_at_limit() -> None:
    try:
        result = run(endless_tool_calls(), limit=10)
    except GraphRecursionError:
        return
    # A limit middleware may instead end the run with a final message.
    assert len(result["messages"]) < 100
    assert len(CALLS) < 100

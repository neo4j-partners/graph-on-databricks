"""Translate between Agent Bricks invocations and the framework-native agent entrypoint."""

import json
from collections.abc import AsyncGenerator
from typing import Any

from agents import ItemHelpers, RunResultStreaming
from agents.exceptions import MaxTurnsExceeded
from agents.items import MessageOutputItem, ToolCallItem, ToolCallOutputItem
from openai.types.responses import ResponseTextDeltaEvent

from agent.agent import run_agent
from databricks_agentkit import InvocationContext

MAX_TURNS_MESSAGE = (
    "I reached the step limit before finishing. Try a narrower question or add more detail."
)
_RECOVERY_INSTRUCTION = (
    "This is a recovery attempt after a previous worker stopped before completing this invocation. "
    "Continue the same task. All tools here are read-only, so repeating a query is safe."
)


def _messages(value: Any) -> list[Any]:
    messages = value.get("messages") if isinstance(value, dict) else value
    if not isinstance(messages, list):
        raise ValueError("input must be a message list or an object with a messages list")
    return messages


def _session_id(context: InvocationContext) -> str:
    value = context.session_id
    if not isinstance(value, str) or not value:
        raise ValueError("session_id must be provided as a top-level invocation field")
    return value


async def invoke(value: Any, context: InvocationContext) -> dict:
    return await _invoke_agent(_messages(value), context)


async def recover(value: Any, context: InvocationContext) -> dict:
    messages = [{"role": "developer", "content": _RECOVERY_INSTRUCTION}, *_messages(value)]
    return await _invoke_agent(messages, context)


async def _invoke_agent(messages: list[Any], context: InvocationContext) -> dict:
    outputs: list[dict] = []
    try:
        async with run_agent(messages, session_id=_session_id(context)) as result:
            async for event in _serialize_events(result):
                await context.emit(event)
                if event["type"] == "message":
                    outputs.append(event["message"])
    except MaxTurnsExceeded:
        message = {"role": "assistant", "content": MAX_TURNS_MESSAGE}
        await context.emit({"type": "message", "message": message})
        outputs.append(message)
    return {"output": outputs, "status": "completed"}


async def _serialize_events(result: RunResultStreaming) -> AsyncGenerator[dict, None]:
    tool_names: dict[str, str] = {}
    async for event in result.stream_events():
        if event.type == "raw_response_event":
            if isinstance(event.data, ResponseTextDeltaEvent) and event.data.delta:
                yield {"type": "delta", "content": event.data.delta, "id": event.data.item_id}
        elif event.type == "run_item_stream_event":
            if message := _normalize_item(event.item, tool_names):
                yield {"type": "message", "message": message}


def _raw_field(item: Any, field: str) -> Any:
    raw = item.raw_item
    return raw.get(field) if isinstance(raw, dict) else getattr(raw, field, None)


def _tool_args(item: Any) -> Any:
    args = _raw_field(item, "arguments")
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {"arguments": args}
    return args or {}


def _normalize_item(item: Any, tool_names: dict[str, str] | None = None) -> dict | None:
    tool_names = {} if tool_names is None else tool_names
    if isinstance(item, MessageOutputItem):
        return {"role": "assistant", "content": ItemHelpers.text_message_output(item)}
    if isinstance(item, ToolCallItem):
        if call_id := _raw_field(item, "call_id"):
            tool_names[call_id] = item.tool_name
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": item.tool_name, "args": _tool_args(item)}],
        }
    if isinstance(item, ToolCallOutputItem):
        name = tool_names.get(_raw_field(item, "call_id"))
        return {"role": "tool", "name": name, "content": str(item.output)}
    return None

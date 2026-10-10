#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Export agent transcripts from NAMS and replay them to separate extraction from agent variance.

The agent writes one conversation per turn: a user message, a reasoning trace (one step and
one tool call per MCP call) and an assistant message. Entity extraction runs over the messages.
Replaying the same stored text into a workspace under a different ontology shows how much of a
before/after difference comes from extraction rather than from the agent answering differently.

    uv run ontology/replay_transcripts.py export --out run1.json
    uv run ontology/replay_transcripts.py export --out run1.json \
        --run-id-prefix nams-load-abc --expect-turns 40
    uv run ontology/replay_transcripts.py replay run1.json                  # dry run
    uv run ontology/replay_transcripts.py replay run1.json --execute \
        --label ontology-v2 --session-suffix=-r1 --wait

`export` only issues GET requests. `replay` makes no network call unless --execute is given.
MEMORY_API_KEY (and optional MEMORY_ENDPOINT) come from the environment or from
neo4j-mcp-graph-agent/.env. The key is never printed.

Endpoints (the same REST routes the neo4j-agent-memory NAMS client maps TurnMemory's calls to):

    export  GET  /v1/conversations                       list, paged by next_cursor
            GET  /v1/conversations/{id}/messages         newest first, max 200
            GET  /v1/reasoning/trace/{conversationId}    steps and tool calls
    replay  GET  /v1/conversations                       collision guard on --execute
            POST /v1/conversations                       {userId, metadata}
            POST /v1/conversations/{id}/messages         {role, content[, metadata]}
            POST /v1/reasoning/steps                     {conversationId, reasoning,
                                                          actionTaken[, result]}
            POST /v1/reasoning/tool-calls                {toolName, input, stepId[, status,
                                                          output, durationMs]}
            GET  /v1/conversations/{id}/extraction-status    only with --wait

Replay order per conversation matches TurnMemory: the messages up to the first assistant
message, then the steps and their tool calls, then the remaining messages.

What a replay cannot reproduce (NAMS limits, not script choices):
  * Conversation ids and message ids are server-assigned and timestamps are the write time.
    Order is preserved by write order.
  * TurnMemory's trace task, outcome and success flag are kept client side by the SDK and are
    never sent to NAMS, so they are neither exported nor replayed.
  * GET messages returns only the newest 200 messages and has no offset. A conversation with
    more messages than that cannot be exported and the export fails rather than truncating.

Replayed conversations get the original text unchanged. Their userId and the client_session_id
and user_id metadata values get the --session-suffix appended (default -r1; write
a value that starts with a dash as --session-suffix=-r2) so a second replay
into the same workspace does not collide, and so extraction scoped by userId is kept apart from
the original run. Pass --keep-user-id to leave userId and metadata user_id as exported. Each
replayed conversation also gets replay_label, replay_suffix and replay_source_conversation_id
in its metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_ENDPOINT = "https://memory.neo4jlabs.com"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
FORMAT = "nams-transcripts/1"
PAGE_LIMIT = 200
MESSAGE_LIMIT = 200
HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_SUFFIX = "-r1"
DEFAULT_LABEL = "replay"


class ReplayError(Exception):
    """A user-facing failure: bad input, a failed NAMS request, or a failed check."""


class ExtractionTimeout(ReplayError):
    """Extraction was still running when --wait-timeout expired."""


@dataclass
class Counts:
    conversations: int = 0
    messages: int = 0
    steps: int = 0
    tool_calls: int = 0

    def as_line(self) -> str:
        return (
            f"{self.conversations} conversation(s), {self.messages} message(s), "
            f"{self.steps} step(s), {self.tool_calls} tool call(s)"
        )


@dataclass
class Replayed:
    counts: Counts = field(default_factory=Counts)
    conversation_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Settings and HTTP
# ---------------------------------------------------------------------------


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        values[key] = value.strip().strip("'\"")
    return values


def resolve_settings(
    env: dict[str, str], env_file: Path | None = None
) -> tuple[str, str]:
    """Return (api_key, endpoint). The process environment wins over the .env file."""
    merged = {**read_env_file(env_file or ENV_FILE), **env}
    key = merged.get("MEMORY_API_KEY", "")
    if not key:
        raise ReplayError("MEMORY_API_KEY is not set (environment or .env).")
    return key, (merged.get("MEMORY_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


def make_client(
    api_key: str, endpoint: str, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    return httpx.Client(
        base_url=endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=HTTP_TIMEOUT_SECONDS,
        transport=transport,
    )


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    retry_on: frozenset[int],
    params: dict | None = None,
    body: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    for attempt in range(4):
        resp = client.request(method, path, params=params, json=body)
        if resp.status_code in retry_on and attempt < 3:
            sleep(2.0 * (attempt + 1))
            continue
        if resp.is_error:
            # Status and route only: never echo headers or bodies.
            raise ReplayError(f"{method} {path} failed with HTTP {resp.status_code}")
        return resp.json() if resp.content else {}
    raise ReplayError(f"{method} {path} failed after retries")


def api_get(
    client: httpx.Client,
    path: str,
    params: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET JSON, retrying 429 and 5xx. Reads are safe to repeat."""
    return _request(
        client,
        "GET",
        path,
        retry_on=frozenset({429, 500, 502, 503, 504}),
        params=params,
        sleep=sleep,
    )


def api_post(
    client: httpx.Client,
    path: str,
    body: dict,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """POST JSON, retrying only 429, which means nothing was written."""
    return _request(
        client, "POST", path, retry_on=frozenset({429}), body=body, sleep=sleep
    )


def fetch_conversations(client: httpx.Client) -> list[dict]:
    items: list[dict] = []
    cursor = ""
    seen: set[str] = set()
    while True:
        params: dict = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        page = api_get(client, "/v1/conversations", params)
        items.extend(page.get("conversations") or [])
        cursor = page.get("next_cursor") or ""
        if not cursor or cursor in seen:
            return items
        seen.add(cursor)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def session_id_of(conversation: dict) -> str:
    """The caller's session id, from metadata, else the user id, else the NAMS id."""
    metadata = conversation.get("metadata") or {}
    return (
        metadata.get("client_session_id")
        or conversation.get("userId")
        or conversation.get("id")
        or ""
    )


def matches_prefix(conversation: dict, prefix: str | None) -> bool:
    if not prefix:
        return True
    metadata = conversation.get("metadata") or {}
    candidates = (metadata.get("client_session_id"), conversation.get("userId"))
    return any(isinstance(c, str) and c.startswith(prefix) for c in candidates)


def _tool_call_record(raw: dict) -> dict:
    return {
        "tool_name": raw.get("toolName"),
        "input": raw.get("input"),
        "output": raw.get("output"),
        "status": raw.get("status"),
        "duration_ms": raw.get("durationMs"),
    }


def build_trace(envelope: dict) -> dict:
    """Group a GET trace envelope into ordered steps with their tool calls."""
    steps = sorted(envelope.get("steps") or [], key=lambda s: s.get("createdAt") or "")
    by_step: dict[str, list[dict]] = {}
    unlinked: list[dict] = []
    for call in sorted(
        envelope.get("toolCalls") or [], key=lambda c: c.get("createdAt") or ""
    ):
        record = _tool_call_record(call)
        if call.get("stepId"):
            by_step.setdefault(call["stepId"], []).append(record)
        else:
            unlinked.append(record)
    return {
        "steps": [
            {
                "thought": step.get("reasoning"),
                "action": step.get("actionTaken"),
                "result": step.get("result"),
                "created_at": step.get("createdAt"),
                "tool_calls": by_step.get(step.get("id"), []),
            }
            for step in steps
        ],
        "unlinked_tool_calls": unlinked,
    }


def export_conversation(client: httpx.Client, conversation: dict) -> dict:
    cid = conversation["id"]
    page = api_get(client, f"/v1/conversations/{cid}/messages", {"limit": MESSAGE_LIMIT})
    raw_messages = page.get("messages") or []
    expected = conversation.get("messageCount")
    if isinstance(expected, int) and expected > len(raw_messages):
        raise ReplayError(
            f"conversation has {expected} messages but NAMS returns at most "
            f"{MESSAGE_LIMIT}; cannot export it completely"
        )
    # The API returns newest first.
    messages = [
        {
            "role": m.get("role"),
            "content": m.get("content", ""),
            "metadata": m.get("metadata") or {},
            "created_at": m.get("createdAt"),
        }
        for m in reversed(raw_messages)
    ]
    trace = build_trace(api_get(client, f"/v1/reasoning/trace/{cid}"))
    return {
        "source_conversation_id": cid,
        "session_id": session_id_of(conversation),
        "user_id": conversation.get("userId") or None,
        "metadata": conversation.get("metadata") or {},
        "created_at": conversation.get("createdAt"),
        "messages": messages,
        "trace": trace,
    }


def count_transcripts(conversations: list[dict]) -> Counts:
    counts = Counts(conversations=len(conversations))
    for conv in conversations:
        trace = conv.get("trace") or {}
        steps = trace.get("steps") or []
        counts.messages += len(conv.get("messages") or [])
        counts.steps += len(steps)
        counts.tool_calls += sum(len(s.get("tool_calls") or []) for s in steps)
        counts.tool_calls += len(trace.get("unlinked_tool_calls") or [])
    return counts


def export_transcripts(
    client: httpx.Client,
    endpoint: str,
    run_id_prefix: str | None,
    expect_turns: int | None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    selected = [
        c for c in fetch_conversations(client) if matches_prefix(c, run_id_prefix)
    ]
    if expect_turns is not None and len(selected) != expect_turns:
        raise ReplayError(
            f"expected {expect_turns} turn(s) but found {len(selected)} "
            "conversation(s); nothing was written"
        )
    selected.sort(key=lambda c: (c.get("createdAt") or "", c.get("id") or ""))
    conversations = [export_conversation(client, c) for c in selected]
    return {
        "format": FORMAT,
        "exported_at": now().isoformat(),
        "endpoint": endpoint,
        "filters": {"run_id_prefix": run_id_prefix, "expect_turns": expect_turns},
        "conversations": conversations,
    }


def cmd_export(args: argparse.Namespace) -> int:
    key, endpoint = resolve_settings(dict(os.environ))
    with make_client(key, endpoint) as client:
        doc = export_transcripts(
            client, endpoint, args.run_id_prefix, args.expect_turns
        )
    out = Path(args.out)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"exported {count_transcripts(doc['conversations']).as_line()}")
    print(f"saved {out}")
    return 0


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def load_transcripts(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReplayError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReplayError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ReplayError(f"{path} is not a {FORMAT} transcript file")
    conversations = doc.get("conversations")
    if not isinstance(conversations, list):
        raise ReplayError(f"{path} has no conversations list")
    for index, conv in enumerate(conversations):
        for message in conv.get("messages") or []:
            if message.get("role") not in ("user", "assistant", "system"):
                raise ReplayError(f"conversation {index} has a message with a bad role")
    return conversations


def target_session_id(conv: dict, suffix: str) -> str:
    return f"{conv.get('session_id') or conv['source_conversation_id']}{suffix}"


def target_user_id(conv: dict, suffix: str, keep_user_id: bool) -> str | None:
    user_id = conv.get("user_id")
    if not user_id or keep_user_id:
        return user_id
    return f"{user_id}{suffix}"


def target_metadata(
    conv: dict, suffix: str, label: str, keep_user_id: bool
) -> dict[str, Any]:
    metadata = dict(conv.get("metadata") or {})
    metadata["client_session_id"] = target_session_id(conv, suffix)
    if "user_id" in metadata and not keep_user_id:
        metadata["user_id"] = f"{metadata['user_id']}{suffix}"
    metadata["replay_label"] = label
    metadata["replay_suffix"] = suffix
    metadata["replay_source_conversation_id"] = conv["source_conversation_id"]
    return metadata


def _message_body(message: dict) -> dict:
    body = {"role": message["role"], "content": message.get("content", "")}
    if message.get("metadata"):
        body["metadata"] = message["metadata"]
    return body


def _step_body(conversation_id: str, step: dict) -> dict:
    # " " mirrors the NAMS client, which sends a blank for an empty required field.
    body = {
        "conversationId": conversation_id,
        "reasoning": step.get("thought") or " ",
        "actionTaken": step.get("action") or " ",
    }
    if step.get("result") is not None:
        body["result"] = step["result"]
    return body


def _tool_call_body(call: dict, step_id: str | None) -> dict:
    body: dict[str, Any] = {
        "toolName": call.get("tool_name") or "unknown",
        "input": call.get("input") if call.get("input") is not None else "{}",
    }
    if step_id:
        body["stepId"] = step_id
    if call.get("status") is not None:
        body["status"] = call["status"]
    if call.get("output") is not None:
        body["output"] = call["output"]
    if call.get("duration_ms") is not None:
        body["durationMs"] = call["duration_ms"]
    return body


def replay_conversation(
    client: httpx.Client,
    conv: dict,
    suffix: str,
    label: str,
    keep_user_id: bool,
    result: Replayed,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    create_body: dict[str, Any] = {
        "metadata": target_metadata(conv, suffix, label, keep_user_id)
    }
    if user_id := target_user_id(conv, suffix, keep_user_id):
        create_body["userId"] = user_id
    created = api_post(client, "/v1/conversations", create_body, sleep)
    new_id = created["id"]
    result.conversation_ids.append(new_id)
    result.counts.conversations += 1

    messages = conv.get("messages") or []
    first_assistant = next(
        (i for i, m in enumerate(messages) if m["role"] == "assistant"), len(messages)
    )

    def write_messages(batch: list[dict]) -> None:
        for message in batch:
            api_post(
                client, f"/v1/conversations/{new_id}/messages", _message_body(message), sleep
            )
            result.counts.messages += 1

    write_messages(messages[:first_assistant])
    trace = conv.get("trace") or {}
    for step in trace.get("steps") or []:
        created_step = api_post(client, "/v1/reasoning/steps", _step_body(new_id, step), sleep)
        result.counts.steps += 1
        for call in step.get("tool_calls") or []:
            api_post(
                client, "/v1/reasoning/tool-calls", _tool_call_body(call, created_step["id"]), sleep
            )
            result.counts.tool_calls += 1
    for call in trace.get("unlinked_tool_calls") or []:
        api_post(client, "/v1/reasoning/tool-calls", _tool_call_body(call, None), sleep)
        result.counts.tool_calls += 1
    write_messages(messages[first_assistant:])


def check_no_collision(
    client: httpx.Client, conversations: list[dict], suffix: str
) -> None:
    wanted = {target_session_id(c, suffix) for c in conversations}
    existing = {session_id_of(c) for c in fetch_conversations(client)}
    clash = wanted & existing
    if clash:
        raise ReplayError(
            f"{len(clash)} replayed session id(s) already exist in this workspace with "
            f"suffix {suffix!r}; choose a different --session-suffix"
        )


def wait_for_extraction(
    client: httpx.Client,
    conversation_ids: list[str],
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> dict:
    """Poll extraction-status for the replayed conversations until none is open."""
    open_ids = list(conversation_ids)
    failed: dict[str, int] = {}
    deadline = clock() + timeout_s
    while True:
        still_open: list[str] = []
        pending = 0
        for cid in open_ids:
            payload = api_get(client, f"/v1/conversations/{cid}/extraction-status")
            statuses = [m.get("status") for m in payload.get("messages", [])]
            n_open = sum(1 for s in statuses if s in ("pending", "processing"))
            if n_open:
                still_open.append(cid)
                pending += n_open
            else:
                failed[cid] = Counter(statuses)["failed"]
        open_ids = still_open
        log(f"extraction: {pending} message(s) open, {sum(failed.values())} failed")
        if not open_ids:
            return {"conversations": len(conversation_ids), "failed_messages": sum(failed.values())}
        if clock() >= deadline:
            raise ExtractionTimeout(
                f"extraction still running after {timeout_s:.0f}s "
                f"({pending} message(s) open); rerun with a larger --wait-timeout"
            )
        sleep(interval_s)


def cmd_replay(args: argparse.Namespace) -> int:
    if args.dry_run and args.execute:
        raise ReplayError("--dry-run and --execute are mutually exclusive")
    if not args.session_suffix:
        raise ReplayError("--session-suffix must not be empty")
    conversations = load_transcripts(Path(args.file))
    planned = count_transcripts(conversations)
    suffix, label = args.session_suffix, args.label

    if not args.execute:
        print(f"dry run (no network call). Would write {planned.as_line()}")
        print(f"label={label!r} session suffix={suffix!r} keep_user_id={args.keep_user_id}")
        print("pass --execute to write")
        return 0

    key, endpoint = resolve_settings(dict(os.environ))
    result = Replayed()
    with make_client(key, endpoint) as client:
        check_no_collision(client, conversations, suffix)
        try:
            for conv in conversations:
                replay_conversation(client, conv, suffix, label, args.keep_user_id, result)
        except ReplayError as exc:
            print(f"wrote before failing: {result.counts.as_line()}", file=sys.stderr)
            raise exc
        print(f"replayed {result.counts.as_line()} (planned {planned.as_line()})")
        if args.wait:
            summary = wait_for_extraction(
                client, result.conversation_ids, args.wait_timeout, args.poll_interval
            )
            print(
                f"extraction finished for {summary['conversations']} conversation(s), "
                f"{summary['failed_messages']} failed message(s)"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export and replay NAMS transcripts.")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="read conversations and traces (GET only)")
    exp.add_argument("--out", required=True, help="transcript JSON file to write")
    exp.add_argument(
        "--run-id-prefix",
        help="only conversations whose client_session_id or userId starts with this",
    )
    exp.add_argument(
        "--expect-turns",
        type=int,
        help="fail without writing unless exactly this many conversations match",
    )
    exp.set_defaults(func=cmd_export)

    rep = sub.add_parser("replay", help="write stored transcripts into the workspace")
    rep.add_argument("file", help="transcript JSON file from export")
    rep.add_argument("--dry-run", action="store_true", help="the default; no network call")
    rep.add_argument("--execute", action="store_true", help="actually write to NAMS")
    rep.add_argument("--label", default=DEFAULT_LABEL, help="recorded in replay metadata")
    rep.add_argument(
        "--session-suffix",
        default=DEFAULT_SUFFIX,
        help=f"appended to session and user ids (default {DEFAULT_SUFFIX})",
    )
    rep.add_argument(
        "--keep-user-id",
        action="store_true",
        help="do not suffix userId and metadata user_id",
    )
    rep.add_argument("--wait", action="store_true", help="wait for extraction to finish")
    rep.add_argument("--wait-timeout", type=float, default=900.0, help="seconds")
    rep.add_argument("--poll-interval", type=float, default=10.0, help="seconds")
    rep.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ExtractionTimeout as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ReplayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

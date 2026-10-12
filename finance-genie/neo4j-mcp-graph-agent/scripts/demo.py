#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "databricks-sdk>=0.40"]
# ///
"""Run the demo questions against the agent and print each answer and its route.

    uv run scripts/demo.py                  # all five steps, local server on :8000
    uv run scripts/demo.py --cloud          # all five steps, deployed app
    uv run scripts/demo.py --step 2 3       # only steps 2 and 3
    uv run scripts/demo.py --step ring      # the optional ring question
    uv run scripts/demo.py --ask "..."      # one free-form question

For each question the script prints the route: which source the agent called, Graph
(Neo4j) or Lakehouse (Genie), in order, read from the tool calls in the response. It
compares the route with the expected one and ends with a routing summary. MLflow shows
the same calls as spans. Answers vary from run to run, so the evidence is the ids and
the route.

--cloud reads DATABRICKS_CONFIG_PROFILE from the environment or from
neo4j-mcp-graph-agent/.env, finds the app URL, and signs in with that profile. The
local server takes the user from the request, so the script sends the user
"demo-analyst" there. The deployed app takes the user from your login, so the script
sends none.

With MEMORY_API_KEY set, the script also prints where NAMS stored each question: the NAMS
user and the conversation id to open at https://memory.neo4jlabs.com/.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import textwrap
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
LOCAL_URL = "http://localhost:8000"
LOCAL_USER = "demo-analyst"
APP_NAME = "agent-bricks-neo4j-graph-agent"
TURN_TIMEOUT = 300.0
NAMS_URL = "https://memory.neo4jlabs.com"
# Recent conversations to scan for the one a question was just stored in.
NAMS_LOOKBACK = 50
NAMS_WAIT_SECONDS = 15.0
NAMS_POLL_SECONDS = 2.0
RULE = "=" * 72
DETAIL_WIDTH = 100

GRAPH = "Graph"
LAKEHOUSE = "Lakehouse"
SOURCES = (
    (
        GRAPH,
        "Neo4j, through the MCP service. For connections: shared phones, hubs, communities.",
    ),
    (LAKEHOUSE, "Delta tables, through Genie. For numbers: balances, counts, averages."),
)


@dataclass(frozen=True)
class Step:
    """One demo step: the questions to ask, the route to expect, and the evidence to look for.

    ``route`` is the expected order of sources. None means the step checks something other
    than routing, such as memory recall, so its route is shown but not compared.
    """

    key: str
    title: str
    kind: str
    why: str
    questions: tuple[str, ...]
    expect: tuple[str, ...]
    route: tuple[str, ...] | None
    new_session: bool = False


@dataclass(frozen=True)
class ToolCall:
    """One tool call from the response, labeled with the source it reached."""

    source: str
    name: str
    detail: str


@dataclass(frozen=True)
class Turn:
    """The answer to one question and the tool calls the agent made for it."""

    answer: str
    calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class Stored:
    """Where NAMS stored one question: the memory user and the NAMS conversation id."""

    user: str
    conversation: str


STEPS = (
    Step(
        key="1",
        title="Shared phone",
        kind="Connections",
        why="Who shares a phone, and which community they form, are connections. "
        "Connections live in the graph.",
        questions=(
            "Which customers share phone 312-555-0142, and which accounts do they own?",
            "Which community are those accounts in?",
        ),
        expect=(
            "The first answer names Accounts 368, 927, 1033, and 1696.",
            "The second answer names Community 8174.",
        ),
        route=(GRAPH,),
        new_session=True,
    ),
    Step(
        key="2",
        title="Hub",
        kind="Connections",
        why="Hubs and communities come from graph algorithms. They live in the graph.",
        questions=(
            "I focus on hub accounts. Is Account 15940 a hub, "
            "and which community is it in?",
        ),
        expect=("The answer names Community 19766.",),
        route=(GRAPH,),
    ),
    Step(
        key="3",
        title="Recall",
        kind="Memory",
        why="This step tests memory, not routing. The app reads this analyst's earlier "
        "conversations from NAMS before the agent runs. The agent may still check the graph.",
        questions=("What was I looking at last time?",),
        expect=(
            "The answer names Account 15940, although this session never did.",
            "Recall reads only your two latest conversations, so run step 2 first.",
        ),
        route=None,
        new_session=True,
    ),
    Step(
        key="4",
        title="Numbers question",
        kind="Numbers",
        why="An average balance is a number computed over table rows. Values live in the "
        "lakehouse, so the agent asks Genie.",
        questions=("What is the average account balance by region and account type?",),
        expect=("The Genie question in the route asks for average balances.",),
        route=(LAKEHOUSE,),
    ),
    Step(
        key="5",
        title="Graph, then lakehouse",
        kind="Connections and numbers",
        why="The question needs both. The graph finds which accounts share phones. Then "
        "Genie looks up the balances and transaction counts of those accounts.",
        questions=(
            "Which phone numbers are shared by more than one customer, and what are "
            "the balances and 30-day transaction counts of the accounts those "
            "customers own?",
        ),
        expect=(
            "The Genie question in the route names the account ids that the graph found.",
        ),
        route=(GRAPH, LAKEHOUSE),
    ),
    Step(
        key="ring",
        title="Optional ring question",
        kind="Connections",
        why="Fraud ring candidates are communities in the graph.",
        questions=("Is Community 3040 a fraud ring candidate?",),
        expect=("The answer names Community 3040.",),
        route=(GRAPH,),
    ),
)
DEFAULT_KEYS = tuple(step.key for step in STEPS if step.key != "ring")


def load_env() -> None:
    """Fill missing process env vars from .env, the same file the quick start uses."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def select_steps(keys: list[str] | None) -> list[Step]:
    """Return the steps for the requested keys, in the order given."""
    by_key = {step.key: step for step in STEPS}
    wanted = keys or list(DEFAULT_KEYS)
    unknown = [key for key in wanted if key not in by_key]
    if unknown:
        raise ValueError(f"unknown step {unknown[0]!r}; choose from {sorted(by_key)}")
    return [by_key[key] for key in wanted]


def build_body(
    prompt: str, session_id: str, user_id: str | None, invocation_id: str | None = None
) -> dict[str, Any]:
    """Build the request body for POST /api/invocations."""
    request: dict[str, Any] = {"messages": [{"role": "user", "content": prompt}]}
    if user_id:
        request["user_id"] = user_id
    return {
        "id": invocation_id or str(uuid.uuid4()),
        "session_id": session_id,
        "input": request,
    }


def _outputs(result: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = result.get("output") or {}
    if isinstance(outputs, dict):  # a deployed app wraps the payload one level deeper
        outputs = outputs.get("output") or []
    return [message for message in outputs if isinstance(message, dict)]


def extract_answer(result: dict[str, Any]) -> str:
    """Return the last assistant message with text, or the start of the raw payload."""
    texts = [
        message.get("content", "")
        for message in _outputs(result)
        if message.get("role") == "assistant" and message.get("content")
    ]
    return texts[-1] if texts else str(result)[:500]


def source_of(name: str) -> str:
    """Name the source a tool reaches.

    The MCP tools are ``<server>___read_neo4j_cypher`` and ``<server>___get_neo4j_schema``.
    The Genie tools are ``genie_ask``, ``genie_poll``, and ``genie_query_result``, named after
    the ``genie`` tool id in agent.toml.
    """
    if "neo4j" in name:
        return GRAPH
    if name.startswith("genie_"):
        return LAKEHOUSE
    return "Other"


def _one_line(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= DETAIL_WIDTH else text[: DETAIL_WIDTH - 3] + "..."


def describe(name: str, args: dict[str, Any]) -> str:
    """Say in a few words what one tool call asked."""
    if name.endswith("read_neo4j_cypher"):
        return _one_line(args.get("query", ""))
    if name.endswith("get_neo4j_schema"):
        return "read the graph schema"
    if name.endswith("_ask"):
        return _one_line(f'"{args.get("question", "")}"')
    if name.endswith("_poll"):
        return "wait for the Genie answer"
    if name.endswith("_query_result"):
        return "read the result rows"
    return ""


def extract_tool_calls(result: dict[str, Any]) -> tuple[ToolCall, ...]:
    """Return every tool call in the response, in the order the agent made them."""
    calls = []
    for message in _outputs(result):
        for call in message.get("tool_calls") or []:
            name = call.get("name") or ""
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            short = name.rpartition("___")[2]
            calls.append(ToolCall(source_of(name), short, describe(short, args)))
    return tuple(calls)


def route_of(calls: tuple[ToolCall, ...] | list[ToolCall]) -> tuple[str, ...]:
    """Collapse the calls into the order of sources, such as (Graph, Lakehouse)."""
    route: list[str] = []
    for call in calls:
        if not route or route[-1] != call.source:
            route.append(call.source)
    return tuple(route)


def format_route(route: tuple[str, ...] | None) -> str:
    if route is None:
        return "any"
    return " -> ".join(route) if route else "no tools"


def route_result(step: Step, took: tuple[str, ...]) -> str:
    """Compare the route with the expected one: same sources, starting with the same one."""
    if step.route is None:
        return "not checked"
    if took and set(took) == set(step.route) and took[0] == step.route[0]:
        return "as expected"
    return "different"


def ask(
    http: httpx.Client,
    auth: dict[str, str],
    prompt: str,
    session_id: str,
    user_id: str | None,
) -> Turn:
    """Send one turn and return the answer text and the tool calls."""
    response = http.post(
        "/api/invocations",
        json=build_body(prompt, session_id, user_id),
        headers={**auth, "X-Routing-Key": session_id},
    )
    response.raise_for_status()
    result = response.json()
    return Turn(extract_answer(result), extract_tool_calls(result))


def cloud_connection(profile: str, app_url: str | None) -> tuple[str, dict[str, str]]:
    """Return the deployed app URL and a fresh auth header."""
    from databricks.sdk import WorkspaceClient  # only needed for the deployed app

    workspace = WorkspaceClient(profile=profile)
    url = app_url or workspace.apps.get(APP_NAME).url
    return url, workspace.config.authenticate()


def nams_client(api_key: str) -> contextlib.AbstractContextManager[httpx.Client | None]:
    """Return a NAMS client, or a stand-in for None when no key is set."""
    if not api_key:
        return contextlib.nullcontext()
    return httpx.Client(
        base_url=(os.environ.get("MEMORY_ENDPOINT") or NAMS_URL).rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )


def find_stored(
    nams: httpx.Client,
    session_id: str,
    seen: set[str],
    *,
    wait_seconds: float = NAMS_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Stored | None:
    """Return the NAMS conversation of this session that no earlier question claimed.

    The app stores each question as its own conversation and keeps the session id in its
    ``client_session_id`` metadata. ``seen`` holds the ids already claimed, so the second
    question of a session finds its own conversation. Polls briefly in case the write lags.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        response = nams.get("/v1/conversations", params={"limit": NAMS_LOOKBACK})
        response.raise_for_status()
        for conversation in response.json().get("conversations") or []:
            metadata = conversation.get("metadata") or {}
            conversation_id = conversation.get("id")
            if (
                conversation_id
                and conversation_id not in seen
                and metadata.get("client_session_id") == session_id
            ):
                seen.add(conversation_id)
                user = metadata.get("user_id") or conversation.get("userId") or "unknown"
                return Stored(user, conversation_id)
        if time.monotonic() >= deadline:
            return None
        sleep(NAMS_POLL_SECONDS)


def print_stored(nams: httpx.Client | None, session_id: str, seen: set[str]) -> None:
    """Print the NAMS user and conversation id for the question just asked."""
    if nams is None:
        return
    try:
        stored = find_stored(nams, session_id, seen)
    except httpx.HTTPError as error:
        print(f"\nIn NAMS: could not check ({error})")
        return
    if stored is None:
        print(
            f"\nIn NAMS: no conversation for session {session_id} yet. Memory is best "
            "effort, so check the app logs for a NAMS warning."
        )
        return
    print(f"\nIn NAMS: user {stored.user}, conversation {stored.conversation}")


def _wrap(label: str, text: str) -> str:
    indent = " " * (len(label) + 1)
    return textwrap.fill(
        text, width=88, initial_indent=f"{label} ", subsequent_indent=indent
    )


def print_sources() -> None:
    print("\nThe agent sends each question to one or both sources:")
    for name, text in SOURCES:
        print(f"  {name:<10} {text}")


def print_step_header(step: Step, session_id: str) -> None:
    print(f"\n{RULE}\nStep {step.key}: {step.title}\n{RULE}")
    print(f"Question type:  {step.kind}")
    print(f"Expected route: {format_route(step.route)}")
    if step.why:
        print(_wrap("Why:           ", step.why))
    print(f"Session:        {session_id}")


def print_turn(question: str, turn: Turn) -> None:
    print(f"\nQ: {question}")
    print("\nRoute taken:")
    if not turn.calls:
        print("  (no tools: the agent answered from the conversation and memory)")
    width = max((len(call.source) for call in turn.calls), default=0)
    for number, call in enumerate(turn.calls, start=1):
        line = f"  {number}. {call.source:<{width}}  {call.name}"
        print(f"{line}: {call.detail}" if call.detail else line)
    print(f"\nA: {turn.answer}")


def print_step_footer(step: Step, took: tuple[str, ...]) -> None:
    print(
        f"\nRoute check: expected {format_route(step.route)}, took {format_route(took)}. "
        f"Result: {route_result(step, took)}."
    )
    if step.expect:
        print("\nYou should see:")
        for line in step.expect:
            print(f"  - {line}")


def print_summary(rows: list[tuple[Step, tuple[str, ...]]]) -> None:
    """Print one line per step: the expected route, the route taken, and whether they match."""
    table = [("Step", "Type", "Expected", "Took", "Result")]
    table += [
        (
            step.key,
            step.kind,
            format_route(step.route),
            format_route(took),
            route_result(step, took),
        )
        for step, took in rows
    ]
    widths = [max(len(row[col]) for row in table) for col in range(len(table[0]))]
    print(f"\n{RULE}\nRouting summary\n{RULE}")
    for row in table:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())
    if any(route_result(step, took) == "different" for step, took in rows):
        print(
            "\nThe agent picks its route each run. A different route is worth a look in "
            "MLflow, but it is not always wrong."
        )


def run_steps(
    steps: list[Step],
    http: httpx.Client,
    auth: dict[str, str],
    user_id: str | None,
    nams: httpx.Client | None = None,
) -> list[tuple[Step, tuple[str, ...]]]:
    """Ask every question in order and return each step's route.

    A step with new_session starts a new session. With a NAMS client, each question also
    prints where NAMS stored it.
    """
    rows = []
    seen: set[str] = set()
    session_id = f"demo-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    for index, step in enumerate(steps):
        if step.new_session and index > 0:
            session_id = f"demo-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
        print_step_header(step, session_id)
        calls: list[ToolCall] = []
        for question in step.questions:
            turn = ask(http, auth, question, session_id, user_id)
            print_turn(question, turn)
            print_stored(nams, session_id, seen)
            calls.extend(turn.calls)
        took = route_of(calls)
        print_step_footer(step, took)
        rows.append((step, took))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cloud", action="store_true", help="use the deployed app")
    parser.add_argument("--app-url", help="override the app URL (implies --cloud)")
    parser.add_argument("--profile", help="Databricks profile; default from .env")
    parser.add_argument("--step", nargs="+", metavar="KEY", help="steps 1-5 or ring")
    parser.add_argument("--ask", metavar="QUESTION", help="ask one free-form question")
    args = parser.parse_args()

    load_env()
    cloud = args.cloud or bool(args.app_url)
    try:
        steps = (
            [Step("ask", "Your question", "Your question", "", (args.ask,), (), None)]
            if args.ask
            else select_steps(args.step)
        )
    except ValueError as error:
        parser.error(str(error))

    if cloud:
        profile = args.profile or os.environ.get("DATABRICKS_CONFIG_PROFILE", "")
        if not profile:
            sys.exit("Set DATABRICKS_CONFIG_PROFILE in .env or pass --profile.")
        base_url, auth = cloud_connection(profile, args.app_url)
        user_id = None
    else:
        base_url, auth, user_id = LOCAL_URL, {}, LOCAL_USER

    print(f"Agent: {base_url}")
    print_sources()
    api_key = os.environ.get("MEMORY_API_KEY", "").strip()
    if not api_key:
        print("\nSet MEMORY_API_KEY to print where NAMS stores each question.")
    try:
        with (
            httpx.Client(base_url=base_url.rstrip("/"), timeout=TURN_TIMEOUT) as http,
            nams_client(api_key) as nams,
        ):
            rows = run_steps(steps, http, auth, user_id, nams)
    except httpx.ConnectError:
        sys.exit(f"Cannot reach {base_url}. Start the server with `make dev`.")
    except httpx.HTTPStatusError as error:
        sys.exit(f"{error.response.status_code} from the agent: {error.response.text[:300]}")

    print_summary(rows)
    if not args.ask:
        print(
            "\nNext: open MLflow to see the same calls as spans, and open NAMS at "
            "https://memory.neo4jlabs.com/ to see each question as a conversation. "
            "The \"In NAMS\" line under each answer names the user and conversation id."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

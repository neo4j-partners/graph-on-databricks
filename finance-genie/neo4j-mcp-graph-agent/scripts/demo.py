#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "databricks-sdk>=0.40"]
# ///
"""Run the demo questions against the agent and print each answer.

    uv run scripts/demo.py                  # all five steps, local server on :8000
    uv run scripts/demo.py --cloud          # all five steps, deployed app
    uv run scripts/demo.py --step 2 3       # only steps 2 and 3
    uv run scripts/demo.py --step ring      # the optional ring question
    uv run scripts/demo.py --ask "..."      # one free-form question

The script prints the answer text and what to look for. It cannot read MLflow, so
the span checks are yours: open the latest traces and look for the named spans.
Answers vary from run to run, so the evidence is the ids and the spans.

--cloud reads DATABRICKS_CONFIG_PROFILE from the environment or from
neo4j-mcp-graph-agent/.env, finds the app URL, and signs in with that profile. The
local server takes the user from the request, so the script sends the user
"demo-analyst" there. The deployed app takes the user from your login, so the script
sends none.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
LOCAL_URL = "http://localhost:8000"
LOCAL_USER = "demo-analyst"
APP_NAME = "agent-bricks-neo4j-graph-agent"
TURN_TIMEOUT = 300.0


@dataclass(frozen=True)
class Step:
    """One demo step: the questions to ask and the evidence to look for."""

    key: str
    title: str
    questions: tuple[str, ...]
    expect: tuple[str, ...]
    new_session: bool = False


STEPS = (
    Step(
        key="1",
        title="Shared phone",
        questions=(
            "Which customers share phone 312-555-0142, and which accounts do they own?",
            "Which community are those accounts in?",
        ),
        expect=(
            "The first answer names Accounts 368, 927, 1033, and 1696.",
            "The second answer names Community 8174.",
            "MLflow trace: a read_neo4j_cypher span.",
        ),
        new_session=True,
    ),
    Step(
        key="2",
        title="Hub",
        questions=(
            "I focus on hub accounts. Is Account 15940 a hub, "
            "and which community is it in?",
        ),
        expect=(
            "The answer names Community 19766.",
            "MLflow trace: a read_neo4j_cypher span.",
        ),
    ),
    Step(
        key="3",
        title="Recall",
        questions=("What was I looking at last time?",),
        expect=(
            "The answer names Account 15940, although this session never did.",
            "Recall reads only your two latest conversations, so run step 2 first.",
        ),
        new_session=True,
    ),
    Step(
        key="4",
        title="Genie value question",
        questions=("What is the average account balance by region and account type?",),
        expect=("MLflow trace: a genie_ask span, then a genie_query_result span.",),
    ),
    Step(
        key="5",
        title="Graph and Genie",
        questions=(
            "Which phone numbers are shared by more than one customer, and what are "
            "the balances and 30-day transaction counts of the accounts those "
            "customers own?",
        ),
        expect=(
            "MLflow trace: a read_neo4j_cypher span, then a genie_ask span.",
            "The Genie question names the account ids that the graph found.",
        ),
    ),
    Step(
        key="ring",
        title="Optional ring question",
        questions=("Is Community 3040 a fraud ring candidate?",),
        expect=(
            "The answer names Community 3040.",
            "MLflow trace: a read_neo4j_cypher span.",
        ),
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


def extract_answer(result: dict[str, Any]) -> str:
    """Return the last assistant message, or the start of the raw payload."""
    outputs = result.get("output") or {}
    if isinstance(outputs, dict):  # a deployed app wraps the payload one level deeper
        outputs = outputs.get("output") or []
    texts = [
        message.get("content", "")
        for message in outputs
        if isinstance(message, dict) and message.get("role") == "assistant"
    ]
    return texts[-1] if texts else str(result)[:500]


def ask(
    http: httpx.Client,
    auth: dict[str, str],
    prompt: str,
    session_id: str,
    user_id: str | None,
) -> str:
    """Send one turn and return the answer text."""
    response = http.post(
        "/api/invocations",
        json=build_body(prompt, session_id, user_id),
        headers={**auth, "X-Routing-Key": session_id},
    )
    response.raise_for_status()
    return extract_answer(response.json())


def cloud_connection(profile: str, app_url: str | None) -> tuple[str, dict[str, str]]:
    """Return the deployed app URL and a fresh auth header."""
    from databricks.sdk import WorkspaceClient  # only needed for the deployed app

    workspace = WorkspaceClient(profile=profile)
    url = app_url or workspace.apps.get(APP_NAME).url
    return url, workspace.config.authenticate()


def run_steps(
    steps: list[Step],
    http: httpx.Client,
    auth: dict[str, str],
    user_id: str | None,
) -> None:
    """Ask every question in order. A step with new_session starts a new session."""
    session_id = f"demo-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    for index, step in enumerate(steps):
        if step.new_session and index > 0:
            session_id = f"demo-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
        print(f"\n=== Step {step.key}: {step.title} (session {session_id}) ===")
        for question in step.questions:
            print(f"\nQ: {question}\n")
            print(f"A: {ask(http, auth, question, session_id, user_id)}")
        if step.expect:
            print("\nYou should see:")
            for line in step.expect:
                print(f"  - {line}")


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
            [Step("ask", "Your question", (args.ask,), ())]
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
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=TURN_TIMEOUT) as http:
            run_steps(steps, http, auth, user_id)
    except httpx.ConnectError:
        sys.exit(f"Cannot reach {base_url}. Start the server with `make dev`.")
    except httpx.HTTPStatusError as error:
        sys.exit(f"{error.response.status_code} from the agent: {error.response.text[:300]}")

    if not args.ask:
        print(
            "\nNext: open MLflow for the span checks, and open NAMS at "
            "https://memory.neo4jlabs.com/ to see each question as a conversation."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "databricks-sdk>=0.40"]
# ///
"""Run the long-term memory demo: one analyst's finding reaches another analyst.

Step 1 asks the app a question as analyst A. Step 2 waits until NAMS has extracted the
entities from that turn. Step 3 asks a follow-up as analyst B, a different user in a new
session. Analyst B shares no conversation history with analyst A, so anything the second
answer knows about the entity came from the long-term entity graph.

    uv run scripts/demo_longterm.py                     # local server on :8000
    uv run scripts/demo_longterm.py --app-url https://<app> --profile <profile>
    uv run scripts/demo_longterm.py --turn 1            # analyst A, then the extraction wait
    uv run scripts/demo_longterm.py --turn 2            # analyst B only

--turn splits the demo for a talk: run turn 1 before it starts and turn 2 live.

Environment (or neo4j-mcp-graph-agent/.env): MEMORY_API_KEY for the extraction wait,
which turn 1 runs, MEMORY_ENDPOINT (optional). A deployed app also needs --profile, and honors the two body
user ids only when the caller is listed in MEMORY_TRUSTED_CALLERS. Otherwise both turns
land under the caller's own identity, and the demo still works because the entity graph
is shared across users.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_ENDPOINT = "https://memory.neo4jlabs.com"
LOCAL_URL = "http://localhost:8000"
EXTRACTION_TIMEOUT = 300.0
TURN_TIMEOUT = 300.0
POLL_INTERVAL = 5.0
# Per-message extraction statuses that mean NAMS is still working on a message.
NONTERMINAL_STATUSES = frozenset({"pending", "processing", "running", "in_progress", "queued"})
# NAMS lists conversations newest first, so the turn just sent is near the top.
CONVERSATION_LOOKBACK = 20

TURN_ONE = (
    "I am investigating Community {community}. Which accounts belong to it, "
    "and what are their risk scores?"
)
TURN_TWO = "What is already known about Community {community}?"


def load_env() -> None:
    """Fill missing process env vars from .env, the same file the quick start uses."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def auth_headers(profile: str | None) -> dict[str, str]:
    """Return Databricks auth headers for a deployed app, or none for a local server."""
    if not profile:
        return {}
    from databricks.sdk import WorkspaceClient  # only needed against a deployed app

    return WorkspaceClient(profile=profile).config.authenticate()


def ask(http: httpx.Client, headers: dict[str, str], user_id: str, session_id: str, prompt: str) -> str:
    """Send one turn and return the final answer text."""
    body = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "input": {"messages": [{"role": "user", "content": prompt}], "user_id": user_id},
    }
    response = http.post(
        "/api/invocations", json=body, headers={**headers, "X-Routing-Key": session_id}
    )
    response.raise_for_status()
    result = response.json()
    outputs = result.get("output") or {}
    if isinstance(outputs, dict):  # a deployed app wraps the payload one level deeper
        outputs = outputs.get("output") or []
    texts = [m.get("content", "") for m in outputs if isinstance(m, dict) and m.get("role") == "assistant"]
    return texts[-1] if texts else json.dumps(result)[:500]


def wait_for_turn_extraction(session_id: str, api_key: str, endpoint: str) -> bool:
    """Poll NAMS until every message of the turn sent in this session is extracted.

    The app stores the caller's session id as client_session_id in the conversation
    metadata. Waiting on that conversation, not on an entity name, matters because the
    entity usually exists already from earlier traffic.
    """
    base = endpoint.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.monotonic() + EXTRACTION_TIMEOUT
    conversation_id = None
    while time.monotonic() < deadline:
        if conversation_id is None:
            response = httpx.get(
                f"{base}/v1/conversations",
                params={"limit": CONVERSATION_LOOKBACK},
                headers=headers,
                timeout=15.0,
            )
            response.raise_for_status()
            conversation_id = next(
                (
                    c["id"]
                    for c in response.json().get("conversations", [])
                    if (c.get("metadata") or {}).get("client_session_id") == session_id
                ),
                None,
            )
        if conversation_id is not None:
            response = httpx.get(
                f"{base}/v1/conversations/{conversation_id}/extraction-status",
                headers=headers,
                timeout=15.0,
            )
            response.raise_for_status()
            summary = response.json().get("summary") or {}
            if summary and not any(summary.get(s, 0) for s in NONTERMINAL_STATUSES):
                return True
        time.sleep(POLL_INTERVAL)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app-url", default=LOCAL_URL, help=f"default {LOCAL_URL}")
    parser.add_argument("--profile", help="Databricks profile; needed for a deployed app")
    parser.add_argument("--community", default="3040", help="community id from the traffic run")
    parser.add_argument("--analyst-a", default="demo-analyst-a")
    parser.add_argument("--analyst-b", default="demo-analyst-b")
    parser.add_argument(
        "--turn",
        choices=("1", "2", "both"),
        default="both",
        help="1: analyst A and the extraction wait; 2: analyst B only; default both",
    )
    args = parser.parse_args()
    run_one = args.turn in ("1", "both")
    run_two = args.turn in ("2", "both")

    load_env()
    api_key = os.environ.get("MEMORY_API_KEY", "").strip()
    if run_one and not api_key:
        sys.exit("Set MEMORY_API_KEY in the environment or .env.")
    endpoint = os.environ.get("MEMORY_ENDPOINT", DEFAULT_ENDPOINT)
    entity_name = f"Community {args.community}"
    headers = auth_headers(args.profile)

    run = time.strftime("%H%M%S")
    session_a, session_b = f"ltm-demo-a-{run}", f"ltm-demo-b-{run}"

    with httpx.Client(base_url=args.app_url.rstrip("/"), timeout=TURN_TIMEOUT) as http:
        if run_one:
            print(f"=== Turn 1: {args.analyst_a}, session {session_a} ===")
            print(TURN_ONE.format(community=args.community), "\n")
            first = ask(http, headers, args.analyst_a, session_a,
                        TURN_ONE.format(community=args.community))
            print(first, "\n")

            print(f"=== Waiting for NAMS to extract the turn from session {session_a} ===")
            if wait_for_turn_extraction(session_a, api_key, endpoint):
                print("NAMS has extracted the entities from turn 1.\n")
            elif run_two:
                print(f"Timed out after {EXTRACTION_TIMEOUT:.0f}s; asking anyway.\n")
            else:
                print(f"Timed out after {EXTRACTION_TIMEOUT:.0f}s; "
                      "wait longer before turn 2.\n")

        if not run_two:
            print("Turn 1 is done. Run --turn 2 with a fresh --analyst-b when you present.")
            return 0

        print(f"=== Turn 2: {args.analyst_b}, new session {session_b} ===")
        print(TURN_TWO.format(community=args.community), "\n")
        second = ask(http, headers, args.analyst_b, session_b,
                     TURN_TWO.format(community=args.community))
        print(second, "\n")

    print("=== What to point out ===")
    print(f"{args.analyst_b} shares no session or conversation history with {args.analyst_a}.")
    print(f"Anything the second answer knows about {entity_name} came from the")
    print("long-term entity graph that NAMS built from earlier turns.")
    print("On a re-run, pass a fresh --analyst-b, for example --analyst-b demo-analyst-b-2,")
    print("so analyst B also has no earlier demo turns of their own to recall.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Check that NAMS stored every turn the app reported as completed.

The app answers a turn even when NAMS is down, so a completed turn does not prove it was
stored. This counts the conversations NAMS holds for each session of the run.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Mapping

import httpx

DEFAULT_ENDPOINT = "https://memory.neo4jlabs.com"
PAGE_LIMIT = 100


def stored_by_session(client: httpx.Client, session_prefix: str) -> Counter[str]:
    """Count stored conversations per ``client_session_id`` that starts with the prefix."""
    counts: Counter[str] = Counter()
    cursor = ""
    seen: set[str] = set()
    while True:
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/v1/conversations", params=params)
        response.raise_for_status()
        page = response.json()
        for conversation in page.get("conversations") or []:
            session = (conversation.get("metadata") or {}).get("client_session_id")
            if isinstance(session, str) and session.startswith(session_prefix):
                counts[session] += 1
        cursor = page.get("next_cursor") or ""
        if not cursor or cursor in seen:
            return counts
        seen.add(cursor)


def missing_turns(expected: Mapping[str, int], stored: Mapping[str, int]) -> dict[str, int]:
    """Return the turns NAMS did not store, per session. Sessions that are complete are omitted."""
    return {
        session: count - stored.get(session, 0)
        for session, count in expected.items()
        if stored.get(session, 0) < count
    }


def verify_stored(
    expected: Mapping[str, int],
    session_prefix: str,
    api_key: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    wait_seconds: float = 30.0,
    poll_seconds: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Return the missing turns per session, polling briefly in case a write is still landing."""
    deadline = time.monotonic() + wait_seconds
    with httpx.Client(
        base_url=endpoint.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        while True:
            missing = missing_turns(expected, stored_by_session(client, session_prefix))
            if not missing or time.monotonic() >= deadline:
                return missing
            sleep(poll_seconds)


def wait_until_ready(
    api_key: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    wait_seconds: float = 60.0,
    poll_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until NAMS answers 200 twice in a row. A database just reset can fail at first."""
    deadline = time.monotonic() + wait_seconds
    streak = 0
    with httpx.Client(
        base_url=endpoint.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        while True:
            try:
                ok = client.get("/v1/conversations", params={"limit": 1}).status_code == 200
            except httpx.HTTPError:
                ok = False
            streak = streak + 1 if ok else 0
            if streak >= 2:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"NAMS at {endpoint} was not ready after {wait_seconds:.0f}s")
            sleep(poll_seconds)

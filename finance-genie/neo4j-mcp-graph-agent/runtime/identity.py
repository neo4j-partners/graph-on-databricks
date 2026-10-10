"""Bind the memory identity to the trusted caller before the runtime persists an invocation.

The Databricks Apps ingress sets the ``X-Forwarded-*`` identity headers, so a caller cannot choose
whose memory it recalls. The bound identity is written into the invocation input, which the
runtime persists, so a recovery attempt sees the same identity as the first attempt.
"""

import json
import logging
import os
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from databricks_agentkit.runtime.store import RUNTIME_STORE_LOCAL_ENV

logger = logging.getLogger(__name__)

MEMORY_USER_FIELD = "memory_user_id"
TRUSTED_CALLERS_ENV = "MEMORY_TRUSTED_CALLERS"
INVOCATIONS_PATH = "/api/invocations"
# The memory user is the first of these; an allowlisted caller may match any of the three.
_PRINCIPAL_HEADERS = ("x-forwarded-email", "x-forwarded-user")
_TRUSTED_CALLER_HEADERS = (*_PRINCIPAL_HEADERS, "x-forwarded-preferred-username")


def _is_local() -> bool:
    """Mirror the runtime: local development has no trusted ingress, so headers are ignored."""
    local_store = os.getenv(RUNTIME_STORE_LOCAL_ENV, "").lower() == "true"
    return local_store or not os.getenv("DATABRICKS_APP_NAME")


def _trusted_callers() -> frozenset[str]:
    raw = os.getenv(TRUSTED_CALLERS_ENV, "")
    return frozenset(value.strip() for value in raw.split(",") if value.strip())


def _caller(headers: dict[str, str]) -> tuple[str, str] | None:
    """Return the (header name, principal) of the trusted caller, or None when absent."""
    for name in _PRINCIPAL_HEADERS:
        if value := headers.get(name, "").strip():
            return name, value
    return None


def _is_trusted(headers: dict[str, str]) -> bool:
    trusted = _trusted_callers()
    return any(headers.get(name, "").strip() in trusted for name in _TRUSTED_CALLER_HEADERS)


def _bind(
    payload: dict[str, Any], headers: dict[str, str], caller: tuple[str, str] | None
) -> None:
    """Set the memory user on the invocation input and log where it came from."""
    # Mirrors the route's [] default for a missing input. Skipping the bind here would let a
    # client-chosen session_id pick the memory user.
    value = payload.get("input", [])
    # A bare message list has nowhere to carry the identity, so it becomes {"messages": [...]}.
    request = {"messages": value} if isinstance(value, list) else dict(value)
    request.pop(MEMORY_USER_FIELD, None)
    body_user = request.get("user_id")
    if caller is None:
        user, source = body_user, "body user_id (local)"
    elif body_user and _is_trusted(headers):
        user, source = body_user, f"body user_id (trusted caller {caller[0]}={caller[1]})"
    else:
        user, source = caller[1], caller[0]
    if user is not None:
        request[MEMORY_USER_FIELD] = user
    payload["input"] = request
    logger.info("memory identity bound: user=%s source=%s", user, source)


async def _read_body(receive: Receive) -> bytes | None:
    """Drain the request body across chunks. None means the client disconnected first."""
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    """Hand the rewritten body to the app once, then defer to the client for disconnects."""
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replay


def _with_content_length(scope: Scope, length: int) -> Scope:
    headers = [
        (name, value)
        for name, value in scope["headers"]
        if name.lower() not in (b"content-length", b"transfer-encoding")
    ]
    headers.append((b"content-length", str(length).encode()))
    return {**scope, "headers": headers}


class MemoryIdentityMiddleware:
    """Write the server-chosen ``memory_user_id`` into each new invocation's input.

    Only ``POST /api/invocations`` is touched, and only on the request side, so streaming and
    status responses pass through unchanged. A client-supplied ``memory_user_id`` is discarded.
    A body ``user_id`` is honored only locally or from a caller in ``MEMORY_TRUSTED_CALLERS``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != INVOCATIONS_PATH
        ):
            await self.app(scope, receive, send)
            return

        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope["headers"]
        }
        local = _is_local()
        caller = None if local else _caller(headers)
        if caller is None and not local:
            error = {
                "code": "MEMORY_USER_IDENTITY_MISSING",
                "message": "Missing trusted caller identity",
            }
            await JSONResponse({"error": error}, status_code=401)(scope, receive, send)
            return

        body = await _read_body(receive)
        if body is None:
            return
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        # Anything the route would reject anyway passes through so it returns its normal 422.
        if isinstance(payload, dict) and isinstance(payload.get("input", []), list | dict):
            _bind(payload, headers, caller)
            body = json.dumps(payload).encode()
            scope = _with_content_length(scope, len(body))
        await self.app(scope, _replay(body, receive), send)

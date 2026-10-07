"""Call the deployed Agent Bricks app as a background invocation and poll for the result."""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from databricks.sdk import WorkspaceClient

from nams_traffic.scenarios import TurnRequest

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled", "error"})


class TurnFailed(RuntimeError):
    """A turn did not complete: the app reported failure, an HTTP error, or the deadline passed."""


def service_principal_client(workspace: WorkspaceClient, scope: str) -> WorkspaceClient:
    """Build a client that signs in as the service principal stored in a secret scope.

    The scope holds ``client-id`` and ``client-secret``. The Databricks Apps proxy accepts
    OAuth tokens minted this way, but rejects the token a Job gets from its own runtime.
    """

    def read(key: str) -> str:
        return base64.b64decode(workspace.secrets.get_secret(scope, key).value).decode()

    return WorkspaceClient(
        host=workspace.config.host,
        client_id=read("client-id"),
        client_secret=read("client-secret"),
        auth_type="oauth-m2m",
    )


@dataclass
class AppClient:
    """Thin client for ``POST /api/invocations``.

    Background mode returns ``202`` straight away and the result is polled, so a slow graph
    query never holds one HTTP request open through the Databricks Apps proxy.
    """

    app_url: str
    workspace: WorkspaceClient
    timeout: float = 300.0
    poll_interval: float = 2.0

    def __post_init__(self) -> None:
        self._http = httpx.Client(base_url=self.app_url.rstrip("/"), timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def invoke(self, request: TurnRequest, stop: threading.Event) -> dict[str, Any]:
        body = {
            "id": request.invocation_id,
            "session_id": request.session_id,
            "input": {
                "messages": [{"role": "user", "content": request.prompt}],
                "user_id": request.user_id,
            },
            "background": True,
        }
        # Each request resends the routing key so a session stays on one replica.
        headers = {**self.workspace.config.authenticate(), "X-Routing-Key": request.session_id}
        try:
            response = self._http.post("/api/invocations", json=body, headers=headers)
            response.raise_for_status()
            status_url = response.json()["status_url"]
            return self._wait(status_url, stop)
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise TurnFailed(f"{type(error).__name__}: {error}") from error

    def _wait(self, status_url: str, stop: threading.Event) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if stop.is_set():
                raise TurnFailed("stopped")
            headers = self.workspace.config.authenticate()
            response = self._http.get(status_url, headers=headers)
            response.raise_for_status()
            result = response.json()
            status = result.get("status")
            if status in TERMINAL_STATUSES:
                if status != "completed":
                    raise TurnFailed(f"invocation {status}: {result.get('error', '')}")
                return result
            stop.wait(self.poll_interval)
        raise TurnFailed(f"timed out after {self.timeout:.0f}s")

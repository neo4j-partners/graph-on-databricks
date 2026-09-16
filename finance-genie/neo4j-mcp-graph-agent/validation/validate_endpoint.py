"""Validate that the configured model serving endpoint is ready."""

from __future__ import annotations

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

from _common import fail, load_settings, ok


def main() -> None:
    settings = load_settings()
    profile = settings.databricks_profile
    ws = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    try:
        endpoint = ws.serving_endpoints.get(settings.model_serving_endpoint_name)
    except NotFound:
        fail(f"serving endpoint not found: {settings.model_serving_endpoint_name}")

    state = getattr(endpoint, "state", None)
    ready = str(getattr(getattr(state, "ready", None), "value", getattr(state, "ready", "")))
    config_update = str(
        getattr(
            getattr(state, "config_update", None),
            "value",
            getattr(state, "config_update", ""),
        )
    )
    if ready.upper() != "READY":
        fail(
            f"endpoint {settings.model_serving_endpoint_name} is not READY "
            f"(ready={ready}, config_update={config_update})"
        )
    ok(f"endpoint is READY: {settings.model_serving_endpoint_name}")


if __name__ == "__main__":
    main()

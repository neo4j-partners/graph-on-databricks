"""Attach the NAMS key secret to the deployed app as the `nams-api-key` resource. Idempotent.

The app reads MEMORY_API_KEY from this resource, as app.yaml says. The resources list is written as
a whole, so the write sends every resource the app already has plus the new one.

    uv run python scripts/attach_nams_key.py --profile PROFILE --app APP [--dry-run]

Exit codes: 0 when the resource is already attached or on --dry-run, 3 when it was added, and 1
when the app is missing.
"""

import argparse
import json
import sys
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

RESOURCE_NAME = "nams-api-key"
ADDED = 3


def nams_resource(scope: str, key: str) -> dict[str, Any]:
    return {
        "name": RESOURCE_NAME,
        "secret": {"scope": scope, "key": key, "permission": "READ"},
    }


def with_nams_key(
    resources: list[dict[str, Any]], scope: str, key: str
) -> list[dict[str, Any]] | None:
    """The app's resources plus the NAMS key, or None if a resource of that name exists."""
    if any(resource.get("name") == RESOURCE_NAME for resource in resources):
        return None
    return [*resources, nams_resource(scope, key)]


def update_body(app: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
    """The create-update request. The mask keeps every other app field unchanged."""
    return {"app": {"name": app, "resources": resources}, "update_mask": "resources"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--scope", default="nams")
    parser.add_argument("--key", default="memory-api-key")
    parser.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    args = parser.parse_args(argv)

    w = WorkspaceClient(profile=args.profile)
    try:
        # Raw JSON, so resource fields this SDK version does not model are sent back unchanged.
        current = w.api_client.do("GET", f"/api/2.0/apps/{args.app}")
    except NotFound:
        print(f"App {args.app} not found. Run agentbricks deploy first.", file=sys.stderr)
        return 1

    existing = current.get("resources", [])
    resources = with_nams_key(existing, args.scope, args.key)
    if resources is None:
        print(f"{args.app} already has the {RESOURCE_NAME} resource. Nothing to do.")
        return 0

    body = update_body(args.app, resources)
    if args.dry_run:
        print(json.dumps(body, indent=2))
        return 0

    print(
        f"Adding {RESOURCE_NAME} (secret {args.scope}/{args.key}, READ) to {args.app}, "
        f"keeping its {len(existing)} existing resources."
    )
    w.api_client.do("POST", f"/api/2.0/apps/{args.app}/update", body=body)
    w.apps.wait_get_update_app_succeeded(app_name=args.app)
    print(f"Added {RESOURCE_NAME}.")
    return ADDED


if __name__ == "__main__":
    sys.exit(main())

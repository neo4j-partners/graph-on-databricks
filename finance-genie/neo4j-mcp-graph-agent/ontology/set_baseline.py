#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27",
#     "pyyaml>=6.0",
# ]
# ///
"""Put NAMS in the trial 1 baseline state for docs/ontology-experiment.md.

    uv run ontology/set_baseline.py --baseline default   # the plain NAMS Default
    uv run ontology/set_baseline.py --baseline none      # check no ontology is active

--baseline default activates the newest NAMS Default revision with no finance types.
--baseline none only checks. The API cannot unbind an active ontology, so it exits
with an error when one is active.

Before any activation the active version id is saved to
ontology/out/previous_active_<timestamp>.json, as apply_ontology.py does.
MEMORY_API_KEY (and optional MEMORY_ENDPOINT) come from the environment or from
neo4j-mcp-graph-agent/.env.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import apply_ontology as ao

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = SCRIPT_DIR / "out"
BASELINES = ("default", "none")


def activate(client: ao.NamsClient, version_id: str) -> None:
    active = (client.get_active().get("version") or {}).get("id")
    if active == version_id:
        print(f"Version {version_id} is already active. Nothing changed.")
        return
    ao.record_active_version(client, STATE_DIR, version_id)
    ao.print_version("Activated", client.activate(version_id))


def set_default(client: ao.NamsClient, finance: dict) -> None:
    labels = {e["label"] for e in finance["entity_types"]}
    activate(client, ao.find_default_version(client, labels)["id"])


def check_none(client: ao.NamsClient) -> None:
    active = client.get_active().get("version")
    if active:
        raise ao.ApiError(
            f"version {active.get('id')} is active, and the API cannot unbind it. "
            "Use --baseline default instead."
        )
    print("No ontology is active. This is the no-ontology baseline.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", choices=BASELINES, required=True)
    parser.add_argument("--yaml", type=Path, default=ao.DEFAULT_YAML)
    args = parser.parse_args(argv)
    try:
        finance = ao.load_ontology(args.yaml)
    except ao.OntologyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        with ao.NamsClient(ao.load_settings()) as client:
            if args.baseline == "default":
                set_default(client, finance)
            else:
                check_none(client)
    except ao.ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27",
#     "pyyaml>=6.0",
# ]
# ///
"""Load the finance-genie NAMS ontology.

Default behavior is a local dry run: load the YAML, validate it locally and
print a summary. Nothing is sent to NAMS unless you pass an explicit flag.

    uv run ontology/apply_ontology.py                    # dry run
    uv run ontology/apply_ontology.py --create           # POST the ontology
    uv run ontology/apply_ontology.py --create --activate
    uv run ontology/apply_ontology.py --update ont_...   # new revision via PUT
    uv run ontology/apply_ontology.py --activate --version-id ov_...
    uv run ontology/apply_ontology.py --rollback ov_...  # re-activate older

--create and --update never mutate an existing version: the hosted spec says
PUT /v1/ontologies/{id} creates a new revision, so --update posts the YAML as
a new revision of ontology ont_... and prints the new version id. After either
one the created version is read back and diffed against the YAML; anything
the service dropped is reported (never an error).

Before any activation the currently active version id (or "none" on a fresh
workspace) is printed and saved to a previous_active_<timestamp>.json file.
Restore it with --rollback <version id or that json file>. The API has no
way to unbind the active ontology, so rolling back to "none" is refused.
MEMORY_API_KEY (and optional MEMORY_ENDPOINT) come from the
environment or from neo4j-mcp-graph-agent/.env. The key is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_YAML = SCRIPT_DIR / "finance_genie.ontology.yaml"
DEFAULT_ENV_FILE = SCRIPT_DIR.parent / ".env"
DEFAULT_ENDPOINT = "https://memory.neo4jlabs.com"
VALIDATION_MODE = "permissive"
COMMIT_MESSAGE = "finance-genie fraud-analyst ontology (apply_ontology.py)"
HTTP_TIMEOUT_SECONDS = 30.0

POLE_TYPES = frozenset({"PERSON", "ORGANIZATION", "LOCATION", "EVENT", "OBJECT"})
PROPERTY_TYPES = frozenset({"string", "datetime", "date", "float", "integer"})
UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")

# Fields the hosted OpenAPI spec models. Anything else we send is documented
# by the Agent Memory docs, but the service may ignore it.
SPEC_ENTITY_FIELDS = frozenset(
    {"label", "pole_type", "subtype", "properties", "description", "color", "icon"}
)
SPEC_RELATIONSHIP_FIELDS = frozenset(
    {"type", "source", "target", "description", "properties", "cardinality"}
)


class OntologyError(Exception):
    """The ontology document cannot be loaded."""


class ApiError(Exception):
    """A NAMS request failed."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    endpoint: str

    def __repr__(self) -> str:
        return f"Settings(api_key=<redacted>, endpoint={self.endpoint!r})"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from a .env file; missing file gives {}."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        values[key] = value.strip().strip("'\"")
    return values


def load_settings(env_file: Path | None = None) -> Settings:
    """Read MEMORY_API_KEY and MEMORY_ENDPOINT; the process env wins."""
    env_file = env_file or DEFAULT_ENV_FILE
    file_values = parse_env_file(env_file)

    def lookup(name: str) -> str:
        return os.environ.get(name) or file_values.get(name, "")

    api_key = lookup("MEMORY_API_KEY")
    if not api_key:
        raise ApiError(
            f"MEMORY_API_KEY is not set (environment or {env_file}); "
            "it is required for --create, --activate and --rollback."
        )
    endpoint = (lookup("MEMORY_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
    return Settings(api_key=api_key, endpoint=endpoint)


def load_ontology(path: Path) -> dict:
    """Load the YAML document; it must be a mapping."""
    try:
        document = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise OntologyError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise OntologyError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise OntologyError(f"{path} must contain a YAML mapping at the top level")
    return document


def _validate_entity_types(entity_types: list) -> tuple[list[str], set[str]]:
    problems: list[str] = []
    labels: set[str] = set()
    for index, entity in enumerate(entity_types):
        if not isinstance(entity, dict):
            problems.append(f"entity_types[{index}] is not a mapping")
            continue
        label = entity.get("label")
        where = f"entity type {label!r}" if label else f"entity_types[{index}]"
        if not label or not isinstance(label, str):
            problems.append(f"{where}: missing label")
        elif label in labels:
            problems.append(f"duplicate entity label {label!r}")
        else:
            labels.add(label)
        pole = entity.get("pole_type")
        if pole not in POLE_TYPES:
            problems.append(
                f"{where}: pole_type {pole!r} is not one of {sorted(POLE_TYPES)}"
            )
        problems.extend(_validate_properties(where, entity.get("properties") or []))
        problems.extend(_validate_aliases(where, entity.get("aliases")))
    return problems, labels


def _validate_properties(where: str, properties: list) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for prop in properties:
        name = prop.get("name") if isinstance(prop, dict) else None
        if not name:
            problems.append(f"{where}: property without a name")
            continue
        if name in seen:
            problems.append(f"{where}: duplicate property {name!r}")
        seen.add(name)
        if prop.get("type") not in PROPERTY_TYPES:
            problems.append(
                f"{where}: property {name!r} type {prop.get('type')!r} "
                f"is not one of {sorted(PROPERTY_TYPES)}"
            )
    return problems


def _validate_aliases(where: str, aliases: object) -> list[str]:
    if aliases is None:
        return []
    if not isinstance(aliases, dict):
        return [f"{where}: aliases must map canonical name to a list of surface forms"]
    return [
        f"{where}: aliases for {canonical!r} must be a list of strings"
        for canonical, forms in aliases.items()
        if not isinstance(forms, list) or not all(isinstance(f, str) for f in forms)
    ]


def _validate_relationships(relationships: list, labels: set[str]) -> list[str]:
    problems: list[str] = []
    triples: set[tuple[str, str, str]] = set()
    valid = [r for r in relationships if isinstance(r, dict)]
    problems.extend(
        f"relationships[{i}] is not a mapping"
        for i, r in enumerate(relationships)
        if not isinstance(r, dict)
    )
    all_triples = triples_of(valid)
    for rel in valid:
        rel_type = rel.get("type")
        source, target = rel.get("source"), rel.get("target")
        where = f"relationship {rel_type} ({source} -> {target})"
        if not isinstance(rel_type, str) or not UPPER_SNAKE.match(rel_type):
            problems.append(f"{where}: type must be UPPER_SNAKE_CASE")
        for role, endpoint in (("source", source), ("target", target)):
            if endpoint not in labels:
                problems.append(
                    f"{where}: {role} {endpoint!r} is not a declared entity type"
                )
        triple = (rel_type, source, target)
        if triple in triples:
            problems.append(f"duplicate relationship triple {triple}")
        triples.add(triple)
        if rel.get("allow_self") and source != target:
            problems.append(f"{where}: allow_self is only valid when source == target")
        problems.extend(_validate_inverse(rel, where, all_triples))
    return problems


def triples_of(relationships: list[dict]) -> set[tuple[str, str, str]]:
    return {(r.get("type"), r.get("source"), r.get("target")) for r in relationships}


def _validate_inverse(
    rel: dict, where: str, all_triples: set[tuple[str, str, str]]
) -> list[str]:
    inverse = rel.get("inverse")
    if not inverse:
        return []
    mirror = (inverse, rel.get("target"), rel.get("source"))
    if mirror in all_triples:
        return []
    return [
        f"{where}: inverse {inverse!r} must exist as "
        f"{inverse} ({rel.get('target')} -> {rel.get('source')})"
    ]


def validate_ontology(document: dict) -> list[str]:
    """Local structural validation mirroring the documented NAMS checks.

    Returns a list of human-readable problems; empty means valid.
    """
    problems: list[str] = []
    domain = document.get("domain")
    if not isinstance(domain, dict) or not (domain.get("id") and domain.get("name")):
        problems.append("domain must have both id and name")
    entity_types = document.get("entity_types")
    if not isinstance(entity_types, list) or not entity_types:
        problems.append("entity_types must be a non-empty list")
        entity_types = []
    entity_problems, labels = _validate_entity_types(entity_types)
    problems.extend(entity_problems)
    relationships = document.get("relationships") or []
    if not isinstance(relationships, list):
        problems.append("relationships must be a list")
        relationships = []
    problems.extend(_validate_relationships(relationships, labels))
    return problems


def lint_ontology(document: dict) -> list[str]:
    """Non-fatal warnings: extractor guidance and fields the spec omits."""
    warnings: list[str] = []
    for entity in document.get("entity_types") or []:
        label = entity.get("label")
        description = entity.get("description") or ""
        if not description:
            warnings.append(f"{label}: no description (the extractor reads it)")
        elif "not a" not in description.lower():
            warnings.append(f"{label}: description has no negative case ('Not a ...')")
        extra = sorted(set(entity) - SPEC_ENTITY_FIELDS)
        if extra:
            warnings.append(
                f"{label}: {extra} not modeled in the hosted OpenAPI spec; "
                "the service may ignore it"
            )
    for rel in document.get("relationships") or []:
        extra = sorted(set(rel) - SPEC_RELATIONSHIP_FIELDS)
        if extra:
            warnings.append(
                f"{rel.get('type')}: {extra} not modeled in the hosted OpenAPI spec"
            )
    return warnings


def summarize(document: dict) -> str:
    """Readable summary of the entity types and relationships."""
    domain = document.get("domain") or {}
    lines = [f"Domain: {domain.get('id')} ({domain.get('name')})", "", "Entity types:"]
    for entity in document.get("entity_types") or []:
        aliases = entity.get("aliases") or {}
        suffix = f", {sum(len(v) for v in aliases.values())} aliases" if aliases else ""
        lines.append(f"  {entity['label']:<20} {entity['pole_type']}{suffix}")
    lines += ["", "Relationships:"]
    for rel in document.get("relationships") or []:
        lines.append(f"  {rel['type']:<16} {rel['source']} -> {rel['target']}")
    return "\n".join(lines)


class NamsClient:
    """Minimal NAMS ontology client. Only constructed for explicit write flags."""

    def __init__(self, settings: Settings) -> None:
        self._client = httpx.Client(
            base_url=settings.endpoint,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )

    def __enter__(self) -> NamsClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: object) -> dict:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(f"{method} {path} failed: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(
                f"{method} {path} returned {response.status_code}: "
                f"{response.text[:500]}"
            )
        return response.json()

    def get_active(self) -> dict:
        return self._request("GET", "/v1/ontologies/active")

    def create(self, document: dict) -> dict:
        body = {
            "ontology": document,
            "validation_mode": VALIDATION_MODE,
            "message": COMMIT_MESSAGE,
        }
        return self._request("POST", "/v1/ontologies", json=body)

    def update(self, ontology_id: str, document: dict) -> dict:
        """PUT creates a new immutable revision; existing versions are untouched."""
        body = {
            "ontology": document,
            "validation_mode": VALIDATION_MODE,
            "message": COMMIT_MESSAGE,
        }
        return self._request("PUT", f"/v1/ontologies/{ontology_id}", json=body)

    def get_version(self, ontology_id: str, revision: int) -> dict:
        return self._request(
            "GET", f"/v1/ontologies/{ontology_id}/versions/{revision}"
        )

    def activate(self, version_id: str) -> dict:
        return self._request(
            "POST", "/v1/ontologies/active", json={"version_id": version_id}
        )


def _normalize(text: object) -> str:
    return " ".join(str(text or "").split())


def _returned_alias_forms(label: str, entity: dict, returned: dict) -> set[str]:
    """Every alias surface form the service kept for one entity type."""
    forms: set[str] = set()
    aliases = entity.get("aliases")
    if isinstance(aliases, dict):
        for canonical, surface_forms in aliases.items():
            forms.add(canonical)
            forms.update(surface_forms or [])
    elif isinstance(aliases, list):
        forms.update(aliases)
    extraction = returned.get("extraction_aliases") or {}
    forms.update(surface for surface, target in extraction.items() if target == label)
    return forms


def diff_round_trip(sent: dict, returned: dict) -> list[str]:
    """List what the service dropped or changed relative to the YAML we sent."""
    drops: list[str] = []
    got_entities = {e.get("label"): e for e in returned.get("entity_types") or []}
    for entity in sent.get("entity_types") or []:
        label = entity["label"]
        got = got_entities.get(label)
        if got is None:
            drops.append(f"entity type {label}: missing")
            continue
        for field in ("pole_type", "description"):
            if _normalize(entity.get(field)) != _normalize(got.get(field)):
                drops.append(
                    f"entity type {label}: {field} changed "
                    f"({_normalize(entity.get(field))!r} -> "
                    f"{_normalize(got.get(field))!r})"
                )
        kept = _returned_alias_forms(label, got, returned)
        for canonical, forms in (entity.get("aliases") or {}).items():
            drops.extend(
                f"entity type {label}: alias {form!r} (for {canonical!r}) missing"
                for form in forms
                if form not in kept
            )
    got_rels: dict[tuple, dict] = {}
    for rel in returned.get("relationships") or []:
        got_rels[(rel.get("type"), rel.get("source"), rel.get("target"))] = rel
    for rel in sent.get("relationships") or []:
        triple = (rel["type"], rel["source"], rel["target"])
        name = f"relationship {rel['type']} ({rel['source']} -> {rel['target']})"
        got = got_rels.get(triple)
        if got is None:
            drops.append(f"{name}: missing")
        elif _normalize(rel.get("description")) != _normalize(got.get("description")):
            drops.append(f"{name}: description changed")
    return drops


def report_round_trip(client: NamsClient, document: dict, created: dict) -> None:
    """Read the created version back and print what the service dropped.

    Drops are reported, never raised: the version exists either way.
    """
    ontology_id, revision = created.get("ontology_id"), created.get("revision")
    if not ontology_id or revision is None:
        print("Round trip skipped: the response had no ontology_id and revision.")
        return
    try:
        record = client.get_version(ontology_id, revision)
        returned = json.loads(record.get("schema_json") or "{}")
    except (ApiError, json.JSONDecodeError) as exc:
        print(f"Round trip skipped: could not read the version back ({exc}).")
        return
    if "entity_types" not in returned and isinstance(returned.get("ontology"), dict):
        returned = returned["ontology"]
    drops = diff_round_trip(document, returned)
    if not drops:
        print("Round trip: the service returned everything we sent.")
        return
    print(f"\nDropped by the service ({len(drops)}):")
    for drop in drops:
        print(f"  - {drop}")
    print(
        "If aliases were dropped, the Team description already lists the short "
        "forms as the fallback."
    )


def record_active_version(
    client: NamsClient, state_dir: Path, target_version_id: str | None
) -> Path:
    """Print and save the active version id so activation can be rolled back.

    A fresh or reset workspace may have no active version; that is recorded
    as an explicit null.
    """
    version = client.get_active().get("version") or {}
    active_id = version.get("id")
    snapshot = {
        "version_id": active_id,
        "ontology_id": version.get("ontology_id"),
        "revision": version.get("revision"),
        "validation_mode": version.get("validation_mode"),
        "saved_at": datetime.now(UTC).isoformat(),
        "about_to_activate": target_version_id,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = state_dir / f"previous_active_{stamp}.json"
    path.write_text(json.dumps(snapshot, indent=2) + "\n")
    if active_id:
        print(
            f"Currently active version: {active_id} "
            f"(ontology {snapshot['ontology_id']}, revision {snapshot['revision']})"
        )
        print(f"Saved rollback info to {path}")
        print(f"Roll back with: --rollback {active_id}")
    else:
        print("No ontology is currently active; recording 'none' as previous state.")
        print(f"Saved rollback info to {path}")
        print("Rolling back to 'none' is not possible: the API cannot unbind.")
    return path


def resolve_rollback_target(argument: str) -> str:
    """Turn the --rollback argument (version id or snapshot file) into an id."""
    if argument.lower() == "none":
        version_id = None
    elif argument.endswith(".json"):
        try:
            version_id = json.loads(Path(argument).read_text()).get("version_id")
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError(f"cannot read rollback file {argument}: {exc}") from exc
    else:
        return argument
    if not version_id:
        raise ApiError(
            "the previous state was 'no active ontology', and the API has no "
            "endpoint to unbind the active ontology (POST /v1/ontologies/active "
            "requires a version_id). Nothing was changed; activate another "
            "version explicitly if you need to leave the current one."
        )
    return version_id


def print_version(label: str, record: dict) -> None:
    print(
        f"{label}: version_id={record.get('id')} "
        f"ontology_id={record.get('ontology_id')} "
        f"revision={record.get('revision')} "
        f"validation_mode={record.get('validation_mode')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and optionally load the finance-genie NAMS ontology. "
        "With no flags this is a local dry run that makes no network calls."
    )
    parser.add_argument("--yaml", type=Path, default=DEFAULT_YAML, help="ontology YAML")
    parser.add_argument(
        "--create", action="store_true", help="POST the ontology (permissive mode)"
    )
    parser.add_argument(
        "--update",
        metavar="ONTOLOGY_ID",
        help="PUT the YAML as a NEW revision of an existing ontology "
        "(never edits an existing version)",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="activate the created version (with --create or --update) "
        "or --version-id",
    )
    parser.add_argument(
        "--version-id", help="an already created version to activate (needs --activate)"
    )
    parser.add_argument(
        "--rollback",
        metavar="VERSION_ID",
        help="activate an older version by id, or by a previous_active_*.json file",
    )
    return parser


def check_flags(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.rollback and (
        args.create or args.update or args.activate or args.version_id
    ):
        parser.error("--rollback cannot be combined with other write flags")
    if args.update and (args.create or args.version_id):
        parser.error("--update cannot be combined with --create or --version-id")
    if args.version_id and not args.activate:
        parser.error("--version-id only makes sense with --activate")
    if args.version_id and args.create:
        parser.error("--version-id and --create are mutually exclusive")
    if args.activate and not (args.create or args.update or args.version_id):
        parser.error("--activate needs --create, --update or --version-id VERSION_ID")


def run(args: argparse.Namespace, document: dict) -> int:
    writes = args.create or args.update or args.activate or args.rollback
    if not writes:
        print("\nDry run: no network calls were made. Nothing was created.")
        print("Pass --create (and --activate) to load it into NAMS.")
        return 0
    state_dir = SCRIPT_DIR
    rollback_id = resolve_rollback_target(args.rollback) if args.rollback else None
    with NamsClient(load_settings()) as client:
        if rollback_id:
            record_active_version(client, state_dir, rollback_id)
            print_version("Activated", client.activate(rollback_id))
            return 0
        if args.activate:
            record_active_version(client, state_dir, args.version_id or "<new>")
        version_id = args.version_id
        if args.create or args.update:
            if args.create:
                created = client.create(document)
                print_version("Created", created)
            else:
                created = client.update(args.update, document)
                print_version("Created new revision", created)
            report_round_trip(client, document, created)
            version_id = created.get("id")
        if args.activate:
            print_version("Activated", client.activate(version_id))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    check_flags(parser, args)
    try:
        document = load_ontology(args.yaml)
    except OntologyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(summarize(document))
    for warning in lint_ontology(document):
        print(f"warning: {warning}")
    problems = validate_ontology(document)
    if problems:
        print("\nValidation FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\nLocal validation passed.")
    try:
        return run(args, document)
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

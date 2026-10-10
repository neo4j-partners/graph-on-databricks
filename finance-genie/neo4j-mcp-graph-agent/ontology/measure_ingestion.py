#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Measure the quality of what NAMS extracted, for before/after ontology comparisons.

READ-ONLY against NAMS: this script only issues GET requests.

Commands:
    uv run ontology/measure_ingestion.py snapshot --label baseline --out before.json \
      --expect-turns 48
    uv run ontology/measure_ingestion.py snapshot --label after --out after.json \
      --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 48
    uv run ontology/measure_ingestion.py compare before.json after.json \
      [--users 4 --sessions 4 --turns 3]
    uv run ontology/measure_ingestion.py recompute before.json --out before2.json
    uv run ontology/measure_ingestion.py gold --snapshot after.json \
      --users 4 --sessions 4 --turns 3

A snapshot stores the raw entities, the relationships (from GET /v1/entities/graph,
since NAMS has no relationship listing endpoint), the active ontology version id, and
conversation/message/trace counts. `recompute` re-derives `metrics` from a saved
snapshot with no network. `gold` scores a snapshot against what the traffic prompts
actually mention (see traffic/nams_traffic/scenarios.py); passing --users/--sessions/
--turns to `compare` adds the gold rows to the comparison.

Entities in NAMS are NOT scoped by run id. A before/after comparison therefore assumes
each run was made in an empty workspace and that the snapshot is taken after extraction
has finished. `snapshot` waits for extraction to finish by default (see --no-wait).

Environment (or neo4j-mcp-graph-agent/.env): MEMORY_API_KEY (required for network use),
MEMORY_ENDPOINT (optional, default https://memory.neo4jlabs.com).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import httpx

DEFAULT_ENDPOINT = "https://memory.neo4jlabs.com"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
PAGE_LIMIT = 200
GRAPH_NODE_LIMIT = 1000  # GET /v1/entities/graph maximum
EXAMPLE_LIMIT = 5
EXIT_INCOMPLETE = 3
DEFAULT_SCENARIOS = (
    Path(__file__).resolve().parent.parent
    / "traffic"
    / "nams_traffic"
    / "scenarios.py"
)

# NAMS built-in ontology ("nams-default") label -> pole_type. Entities from NAMS carry
# only `type`, so pole_type comes from the active ontology (stored in each snapshot as
# ontology_type_poles); this table is the fallback for old snapshots and --from-file.
DEFAULT_ONTOLOGY_ID = "nams-default"
DEFAULT_TYPE_POLES: dict[str, str] = {
    "Event": "EVENT",
    "Object": "OBJECT",
    "Person": "PERSON",
    "Organization": "ORGANIZATION",
    "Location": "LOCATION",
    "SoftwareTool": "OBJECT",
    "API": "OBJECT",
    "Concept": "OBJECT",
    "Decision": "EVENT",
    "ProgrammingLanguage": "OBJECT",
    "Database": "OBJECT",
    "Framework": "OBJECT",
    "Service": "OBJECT",
}
COMPARED_POLES = ("PERSON", "ORGANIZATION")

GENERIC_TYPES = frozenset({"Object", "Concept"})

# Normalization vocabularies (see normalize_name).
_LEADING_WORDS = frozenset({"synthetic", "the", "dr", "mr", "mrs", "ms", "prof"})
_TRAILING_WORDS = frozenset({"team", "inc", "llc", "ltd", "corp", "corporation", "co"})

# Noise patterns (see noise_entities).
_NOISE_SUBSTRINGS = ("___", "neo4j-mcp", "get_neo4j_schema")
_NOISE_SUFFIX = " relationships"
_NOISE_WORDS = frozenset(
    {"table", "column", "schema", "value", "database", "graph", "node"}
)
_SNAKE_CASE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")
_SCREAMING_SNAKE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)+$")

INSTANCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "account": re.compile(r"\baccount \d+\b", re.IGNORECASE),
    "community": re.compile(r"\bcommunity \d+\b", re.IGNORECASE),
    "identity_cluster": re.compile(r"\bidentity cluster \d+\b", re.IGNORECASE),
    "phone": re.compile(r"(?<!\d)\d{3}-\d{3}-\d{4}(?!\d)"),
    "case": re.compile(r"\bcase[- ]\d+\b", re.IGNORECASE),
}


# ---------------------------------------------------------------------------
# Pure metric functions
# ---------------------------------------------------------------------------


def _etype(entity: dict) -> str:
    return str(entity.get("type") or "(none)")


def _ename(entity: dict) -> str:
    return str(entity.get("name") or "").strip()


def normalize_name(name: str) -> str:
    """Return a conservative comparison key for an entity name.

    Steps: NFKC + casefold; hyphens, underscores and slashes become spaces; all other
    punctuation is deleted; whitespace is collapsed. Then, at most once each:
      - strip ONE leading word from {synthetic, the, dr, mr, mrs, ms, prof}, but only
        when at least two tokens would remain (so "Dr Smith" is left alone);
      - strip ONE trailing word from {team, inc, llc, ltd, corp, corporation, co},
        but only when at least one token would remain.

    Deliberately NOT done: first-name-only or initial variants ("J. Smith" vs "John
    Smith"), plural/stem folding, leading-zero folding ("0003" vs "3"), and fuzzy
    matching. False merges are worse than misses, so anything ambiguous stays apart.
    Known weakness: "Fabrikam team" and "Fabrikam" merge, which assumes the team is the
    organization; "Tailspin Card Services Investigations team" does not merge with
    "Tailspin Card Services".
    """
    text = unicodedata.normalize("NFKC", name).casefold()
    text = re.sub(r"[_\-/]+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    tokens = text.split()
    if len(tokens) > 2 and tokens[0] in _LEADING_WORDS:
        tokens = tokens[1:]
    if len(tokens) > 1 and tokens[-1] in _TRAILING_WORDS:
        tokens = tokens[:-1]
    return " ".join(tokens)


def count_by_type(entities: list[dict]) -> dict[str, int]:
    counts = Counter(_etype(e) for e in entities)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def generic_bucket_share(entities: list[dict]) -> dict:
    """Fraction of entities typed Object or Concept (the catch-all types)."""
    total = len(entities)
    generic = sum(1 for e in entities if _etype(e) in GENERIC_TYPES)
    return {
        "count": generic,
        "share": round(generic / total, 4) if total else 0.0,
    }


def pole_of(entity: dict, type_poles: dict[str, str] | None = None) -> str | None:
    """pole_type of an entity: its own field if present, else mapped from its type.

    NAMS entity payloads carry only `type`; the pole comes from the ontology's
    entity_types (type_poles, label -> pole_type), then the built-in default table.
    """
    own = entity.get("pole_type")
    if own:
        return str(own)
    etype = _etype(entity)
    return (type_poles or {}).get(etype) or DEFAULT_TYPE_POLES.get(etype)


def duplicate_surface_forms(
    entities: list[dict],
    example_limit: int = EXAMPLE_LIMIT,
    type_poles: dict[str, str] | None = None,
) -> dict:
    """Duplicate groups: entities sharing a normalized name key.

    `groups` and `excess` (entities beyond the first in each group) are totals over
    groups of the SAME type. `by_type` lists only types that have duplicates. `by_pole`
    groups by (pole_type, normalized name) instead, so the same real-world kind is
    comparable across ontologies (Person under the default ontology, Analyst and
    Customer under the custom one). It always has PERSON and ORGANIZATION slots.
    Examples show raw surface forms. Uses normalize_name, so merges are conservative.
    """
    by_type_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_pole_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in entities:
        key = normalize_name(_ename(e))
        if not key:
            continue
        by_type_groups[(_etype(e), key)].append(_ename(e))
        if pole := pole_of(e, type_poles):
            by_pole_groups[(pole, key)].append(_ename(e))

    def summarize(groups: dict, slots: dict[str, dict]) -> None:
        dup = {k: v for k, v in groups.items() if len(v) > 1}
        for (label, key), names in sorted(
            dup.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ):
            slot = slots.setdefault(label, {"groups": 0, "excess": 0, "examples": []})
            slot["groups"] += 1
            slot["excess"] += len(names) - 1
            if len(slot["examples"]) < example_limit:
                slot["examples"].append(
                    {"key": key, "count": len(names), "forms": sorted(set(names))}
                )

    by_type: dict[str, dict] = {}
    by_pole: dict[str, dict] = {
        pole: {"groups": 0, "excess": 0, "examples": []} for pole in COMPARED_POLES
    }
    summarize(by_type_groups, by_type)
    summarize(by_pole_groups, by_pole)
    dup_all = [v for v in by_type_groups.values() if len(v) > 1]
    return {
        "groups": len(dup_all),
        "excess": sum(len(v) - 1 for v in dup_all),
        "by_type": by_type,
        "by_pole": by_pole,
    }


def type_conflicts(entities: list[dict], example_limit: int = EXAMPLE_LIMIT) -> dict:
    """Normalized names that appear under more than one type."""
    types_by_key: dict[str, Counter] = defaultdict(Counter)
    for e in entities:
        key = normalize_name(_ename(e))
        if key:
            types_by_key[key][_etype(e)] += 1
    conflicts = {k: c for k, c in types_by_key.items() if len(c) > 1}
    ranked = sorted(conflicts.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    return {
        "count": len(conflicts),
        "examples": [
            {"key": k, "types": dict(sorted(c.items()))}
            for k, c in ranked[:example_limit]
        ],
    }


def noise_reason(name: str) -> str | None:
    """Return the first matching plumbing pattern for a name, else None.

    Patterns: contains "___", "neo4j-mcp" or "get_neo4j_schema"; ends with
    " relationships"; is one of Table/Column/Schema/Value/Database/Graph/Node; or is a
    bare snake_case / SCREAMING_SNAKE token (risk_score, community_id, HAS_ADDRESS).
    Known weakness: a single-word relationship type without an underscore (OWNS) and
    a property written as one word (balance) are not detected.
    """
    stripped = name.strip()
    lowered = stripped.casefold()
    for needle in _NOISE_SUBSTRINGS:
        if needle in lowered:
            return f"contains:{needle}"
    if lowered.endswith(_NOISE_SUFFIX):
        return "suffix: relationships"
    if lowered in _NOISE_WORDS:
        return "schema_word"
    if _SNAKE_CASE.match(stripped) or _SCREAMING_SNAKE.match(stripped):
        return "bare_identifier"
    return None


def noise_entities(entities: list[dict], example_limit: int = EXAMPLE_LIMIT) -> dict:
    reasons: Counter = Counter()
    examples: list[str] = []
    count = 0
    for e in entities:
        reason = noise_reason(_ename(e))
        if reason is None:
            continue
        count += 1
        reasons[reason] += 1
        if _ename(e) not in examples and len(examples) < example_limit:
            examples.append(_ename(e))
    return {
        "count": count,
        "share": round(count / len(entities), 4) if entities else 0.0,
        "by_reason": dict(sorted(reasons.items())),
        "examples": examples,
    }


def _instance_key(label: str, match: str) -> str:
    """Case-folded match; case ids fold the hyphen so CASE-4001 equals case 4001."""
    folded = match.casefold()
    return folded.replace("-", " ") if label == "case" else folded


def instance_coverage(entities: list[dict], example_limit: int = EXAMPLE_LIMIT) -> dict:
    """Entities whose name contains an instance-level identifier.

    Patterns: Account N, Community N, Identity cluster N (case-insensitive), phone
    numbers NNN-NNN-NNNN, and case N. Per pattern: `entities` (rows matching) and
    `distinct` (distinct case-folded matched strings). A match anywhere in the name
    counts, so "Account 1234 ring" counts as account 1234.
    """
    out: dict[str, dict] = {}
    for label, pattern in INSTANCE_PATTERNS.items():
        rows = 0
        found: set[str] = set()
        for e in entities:
            matches = pattern.findall(_ename(e))
            if matches:
                rows += 1
                found.update(_instance_key(label, m) for m in matches)
        out[label] = {
            "entities": rows,
            "distinct": len(found),
            "examples": sorted(found)[:example_limit],
        }
    return out


def ontology_conformance(
    entities: list[dict], declared_types: Iterable[str] | None
) -> dict | None:
    """Fraction of entities whose type exactly equals a declared type label.

    Exact, case-sensitive match: "servicetool" does not conform to "ServiceTool".
    Returns None when no declared types are supplied.
    """
    if declared_types is None:
        return None
    declared = set(declared_types)
    total = len(entities)
    conforming = sum(1 for e in entities if _etype(e) in declared)
    outside = Counter(_etype(e) for e in entities if _etype(e) not in declared)
    return {
        "declared_types": sorted(declared),
        "conforming": conforming,
        "fraction": round(conforming / total, 4) if total else 0.0,
        "top_outside_types": dict(outside.most_common(EXAMPLE_LIMIT)),
    }


def compute_metrics(
    entities: list[dict],
    declared_types: Iterable[str] | None = None,
    type_poles: dict[str, str] | None = None,
) -> dict:
    return {
        "total_entities": len(entities),
        "by_type": count_by_type(entities),
        "generic_bucket": generic_bucket_share(entities),
        "duplicates": duplicate_surface_forms(entities, type_poles=type_poles),
        "type_conflicts": type_conflicts(entities),
        "noise": noise_entities(entities),
        "instance_coverage": instance_coverage(entities),
        "ontology_conformance": ontology_conformance(entities, declared_types),
    }


def _read_entity_types(path: Path) -> list[tuple[str, str | None]] | None:
    """(label, pole_type) per entity_types item, or None if the file is absent.

    A tiny stdlib reader (no PyYAML): finds the top-level `entity_types:` key and
    collects `label:` values (and the `pole_type:` that follows each) from its
    indented block, stopping at the next top-level key. Handles `- label: X` and
    `label: X`, with optional quotes.
    """
    if not path.is_file():
        return None
    items: list[tuple[str, str | None]] = []
    in_block = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace() and not line.startswith("-"):
            in_block = line.split(":", 1)[0].strip() == "entity_types"
            continue
        if not in_block:
            continue
        if m := re.match(r"^\s*(?:-\s*)?label:\s*(.+?)\s*$", line):
            items.append((m.group(1).strip("'\""), None))
        elif items and (m := re.match(r"^\s*pole_type:\s*(.+?)\s*$", line)):
            items[-1] = (items[-1][0], m.group(1).strip("'\""))
    return items


def load_declared_types(path: Path) -> list[str] | None:
    """Read entity_types[].label values from an ontology YAML, or None if absent."""
    items = _read_entity_types(path)
    return None if items is None else [label for label, _ in items]


def load_declared_poles(path: Path) -> dict[str, str]:
    """Read entity_types[] label -> pole_type from an ontology YAML ({} if absent)."""
    return {label: pole for label, pole in _read_entity_types(path) or [] if pole}


# ---------------------------------------------------------------------------
# NAMS access (GET only)
# ---------------------------------------------------------------------------


class ExtractionTimeout(RuntimeError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        values[key] = value.strip().strip("'\"")
    return values


def resolve_settings(env: dict[str, str], env_file: Path = ENV_FILE) -> tuple[str, str]:
    """Return (api_key, endpoint). Process environment wins over the .env file."""
    merged = {**read_env_file(env_file), **env}
    key = merged.get("MEMORY_API_KEY", "")
    if not key:
        raise SystemExit("MEMORY_API_KEY is not set (environment or .env).")
    return key, merged.get("MEMORY_ENDPOINT") or DEFAULT_ENDPOINT


def make_client(api_key: str, endpoint: str) -> httpx.Client:
    return httpx.Client(
        base_url=endpoint.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )


def api_get(
    client: httpx.Client,
    path: str,
    params: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
    missing_ok: bool = False,
) -> dict:
    """GET a JSON document, retrying 429/5xx a few times. The only HTTP verb used.

    With missing_ok, a 404 returns {} instead of failing.
    """
    for attempt in range(4):
        resp = client.get(path, params=params)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            sleep(2.0 * (attempt + 1))
            continue
        if missing_ok and resp.status_code == 404:
            return {}
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SystemExit(f"GET {path} failed with HTTP {resp.status_code}") from exc
        return resp.json()
    raise SystemExit(f"GET {path} failed after retries")


def fetch_paginated(client: httpx.Client, path: str, key: str, **extra) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        params: dict = {"limit": PAGE_LIMIT, **extra}
        if cursor:
            params["cursor"] = cursor
        page = api_get(client, path, params)
        items.extend(page.get(key, []))
        cursor = page.get("next_cursor")
        if not cursor or cursor in seen:
            return items
        seen.add(cursor)


def fetch_all_entities(client: httpx.Client) -> list[dict]:
    return fetch_paginated(client, "/v1/entities", "entities")


def fetch_active_ontology(client: httpx.Client) -> dict:
    """The active ontology via GET /v1/ontologies/active.

    Returns version_id ("none" when the response has no version object), ontology_id,
    revision, name (the ontology's domain name), domain_id, and type_poles (entity
    type label -> pole_type from the ontology body).
    """
    payload = api_get(client, "/v1/ontologies/active", missing_ok=True)
    version = payload.get("version") or {}
    body = payload.get("ontology") or {}
    domain = body.get("domain") or {}
    return {
        "version_id": version.get("id") or "none",
        "ontology_id": version.get("ontology_id"),
        "revision": version.get("revision"),
        "name": domain.get("name"),
        "domain_id": domain.get("id"),
        "type_poles": {
            et["label"]: et["pole_type"]
            for et in body.get("entity_types") or []
            if et.get("label") and et.get("pole_type")
        },
    }


def fetch_relationships(client: httpx.Client) -> tuple[list[dict], str | None]:
    """All relationship edges, as (edges, note).

    NAMS has no relationship listing endpoint (POST /v1/relationships only writes), so
    this reads GET /v1/entities/graph (canonical entities as nodes, edges among them,
    capped at 1000 nodes). Edges carry sourceId, targetId, type and predicate. The
    note is set when the node cap may have truncated the graph.
    """
    graph = api_get(client, "/v1/entities/graph", {"limit": GRAPH_NODE_LIMIT})
    nodes = graph.get("nodes", [])
    note = None
    if len(nodes) >= GRAPH_NODE_LIMIT:
        note = f"graph capped at {GRAPH_NODE_LIMIT} nodes; relationships may be partial"
    return graph.get("edges", []), note


def fetch_completeness(client: httpx.Client) -> dict:
    """Conversation, user/assistant message and reasoning-trace counts.

    A trace is counted for a conversation whose GET /v1/reasoning/trace/{id} has at
    least one step or tool call. There is no trace count endpoint, and a turn that
    made no tool calls writes an empty trace, so it is not counted. Messages are read
    with limit 200, the API maximum per conversation.
    """
    conversations = fetch_paginated(client, "/v1/conversations", "conversations")
    users = assistants = traces = 0
    for conv in conversations:
        cid = conv["id"]
        msgs = api_get(
            client, f"/v1/conversations/{cid}/messages", {"limit": PAGE_LIMIT}
        ).get("messages", [])
        users += sum(1 for m in msgs if m.get("role") == "user")
        assistants += sum(1 for m in msgs if m.get("role") == "assistant")
        trace = api_get(client, f"/v1/reasoning/trace/{cid}", missing_ok=True)
        if trace.get("steps") or trace.get("toolCalls"):
            traces += 1
    return {
        "conversations": len(conversations),
        "user_messages": users,
        "assistant_messages": assistants,
        "traces": traces,
    }


def check_completeness(counts: dict, expected_turns: int | None) -> list[str]:
    """Mismatch descriptions against N expected turns; empty when complete or unset."""
    if expected_turns is None:
        return []
    return [
        f"{name}: expected {expected_turns}, found {counts.get(key)}"
        for key, name in (
            ("conversations", "conversations"),
            ("user_messages", "user messages"),
            ("assistant_messages", "assistant messages"),
            ("traces", "reasoning traces (with steps)"),
        )
        if counts.get(key) != expected_turns
    ]


def wait_for_extraction(
    client: httpx.Client,
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> dict:
    """Poll extraction-status for every conversation until none is pending/processing.

    Conversations whose messages are all settled are not polled again. Failed messages
    do not block; they are counted in the returned summary. Raises ExtractionTimeout.
    """
    conversations = fetch_paginated(client, "/v1/conversations", "conversations")
    open_ids = [c["id"] for c in conversations]
    failed = 0
    settled_failed: dict[str, int] = {}
    deadline = clock() + timeout_s
    while True:
        still_open: list[str] = []
        pending = 0
        for cid in open_ids:
            msgs = api_get(client, f"/v1/conversations/{cid}/extraction-status")
            statuses = [m.get("status") for m in msgs.get("messages", [])]
            n_open = sum(1 for s in statuses if s in ("pending", "processing"))
            if n_open:
                still_open.append(cid)
                pending += n_open
            else:
                settled_failed[cid] = sum(1 for s in statuses if s == "failed")
        open_ids = still_open
        failed = sum(settled_failed.values())
        log(f"extraction: {pending} message(s) open, {failed} failed")
        if not open_ids:
            return {
                "waited": True,
                "conversations": len(conversations),
                "failed_messages": failed,
            }
        if clock() >= deadline:
            raise ExtractionTimeout(
                f"extraction still running after {timeout_s:.0f}s "
                f"({pending} message(s) open); rerun with a larger --wait-timeout "
                "or --no-wait"
            )
        sleep(interval_s)


# ---------------------------------------------------------------------------
# Snapshot, flatten, compare, formatting
# ---------------------------------------------------------------------------


def snapshot_type_poles(snap: dict) -> dict[str, str]:
    """label -> pole_type for a snapshot: the stored ontology map over the default."""
    return {**DEFAULT_TYPE_POLES, **(snap.get("ontology_type_poles") or {})}


def build_snapshot(
    label: str,
    entities: list[dict],
    declared_types: list[str] | None,
    ontology: dict | None,
    source: str,
    extraction: dict | None,
    api_entity_count: int | None,
    *,
    relationships: list[dict] | None = None,
    relationships_note: str | None = None,
    completeness: dict | None = None,
    expected_turns: int | None = None,
    extra_type_poles: dict[str, str] | None = None,
) -> dict:
    """Assemble a snapshot. `ontology` is fetch_active_ontology's dict or None.

    The ontology is identified by `ontology_version_id` ("none" without a version
    object) plus name and revision. Raw `entities` and `relationships` are kept so
    `metrics` can be recomputed offline. `relationships` is None when unavailable, with
    the reason in `relationships_note`.
    """
    ontology = ontology or {}
    type_poles = {**(extra_type_poles or {}), **(ontology.get("type_poles") or {})}
    return {
        "label": label,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "ontology_version_id": ontology.get("version_id") or "none",
        "ontology_id": ontology.get("ontology_id"),
        "ontology_name": ontology.get("name"),
        "ontology_revision": ontology.get("revision"),
        "ontology_domain_id": ontology.get("domain_id"),
        "ontology_type_poles": type_poles,
        "declared_types": declared_types,
        "entity_count": len(entities),
        "api_entity_count": api_entity_count,
        "extraction": extraction,
        "completeness": {**(completeness or {}), "expected_turns": expected_turns},
        "relationship_count": None if relationships is None else len(relationships),
        "relationships_note": relationships_note,
        "metrics": compute_metrics(
            entities, declared_types, {**DEFAULT_TYPE_POLES, **type_poles}
        ),
        "entities": entities,
        "relationships": relationships,
    }


def recompute_snapshot(
    snap: dict,
    declared_types: list[str] | None = None,
    extra_type_poles: dict[str, str] | None = None,
) -> dict:
    """Copy of a saved snapshot with `metrics` re-derived from its raw entities.

    No network. Declared types default to the ones stored in the snapshot; poles from
    an ontology YAML (extra_type_poles) fill in labels the stored ontology lacks.
    """
    entities = snap.get("entities")
    if entities is None:
        raise SystemExit("snapshot has no raw `entities`; it cannot be recomputed.")
    declared = declared_types
    if declared is None:
        declared = snap.get("declared_types")
    if declared is None:
        declared = (snap.get("metrics", {}).get("ontology_conformance") or {}).get(
            "declared_types"
        )
    stored = snap.get("ontology_type_poles") or {}
    poles = {**(extra_type_poles or {}), **stored}
    out = dict(snap)
    out["recomputed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out["declared_types"] = declared
    out["ontology_type_poles"] = poles
    out["entity_count"] = len(entities)
    out["metrics"] = compute_metrics(
        entities, declared, {**DEFAULT_TYPE_POLES, **poles}
    )
    return out


def flatten_metrics(metrics: dict) -> dict[str, float | int | None]:
    """Scalar view of the metrics used by compare, in display order."""
    dups = metrics["duplicates"]
    flat: dict[str, float | int | None] = {
        "total entities": metrics["total_entities"],
        "generic (Object/Concept) count": metrics["generic_bucket"]["count"],
        "generic (Object/Concept) share": metrics["generic_bucket"]["share"],
        "duplicate groups (all types)": dups["groups"],
        "duplicate excess entities": dups["excess"],
    }
    # Pole-based rows are comparable across ontologies (Person vs Analyst + Customer).
    # Snapshots from before by_pole existed show "-" instead of a misleading zero.
    for pole in COMPARED_POLES:
        slot = (dups.get("by_pole") or {}).get(pole)
        flat[f"duplicate groups: pole {pole}"] = slot["groups"] if slot else None
    flat.update(
        {
            "type conflicts": metrics["type_conflicts"]["count"],
            "noise entities": metrics["noise"]["count"],
            "noise share": metrics["noise"]["share"],
        }
    )
    for label, info in metrics["instance_coverage"].items():
        flat[f"instances distinct: {label}"] = info["distinct"]
    conf = metrics.get("ontology_conformance")
    flat["ontology conformance"] = conf["fraction"] if conf else None
    for etype, n in metrics["by_type"].items():
        flat[f"type count: {etype}"] = n
    return flat


def verdict(before: float | int | None, after: float | int | None) -> str:
    if before is None or after is None:
        return "n/a"
    if abs(after - before) < 1e-9:
        return "unchanged"
    return "up" if after > before else "down"


def _fmt(value: float | int | None, signed: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and not float(value).is_integer():
        return f"{value:+.3f}" if signed else f"{value:.3f}"
    return f"{int(value):+d}" if signed else f"{int(value)}"


def ontology_id_lines(before: dict, after: dict) -> list[str]:
    """Both snapshots' ontology version ids, flagged when identical or unknown."""
    bid = before.get("ontology_version_id", "unknown")
    aid = after.get("ontology_version_id", "unknown")
    lines = [f"ontology_version_id before: {bid}", f"ontology_version_id after:  {aid}"]
    if bid == aid and bid != "unknown":
        lines.append(
            "WARNING: both snapshots have the SAME ontology_version_id; the 'after' "
            "run may not have used a different ontology."
        )
    elif "unknown" in (bid, aid):
        lines.append(
            "note: a snapshot predates ontology_version_id; ontology identity unknown."
        )
    return lines


def format_compare(
    before: dict,
    after: dict,
    gold_before: dict | None = None,
    gold_after: dict | None = None,
) -> str:
    fb = flatten_metrics(before["metrics"])
    fa = flatten_metrics(after["metrics"])
    if gold_before is not None and gold_after is not None:
        fb.update(flatten_gold(gold_before))
        fa.update(flatten_gold(gold_after))
    names = list(fb) + [n for n in fa if n not in fb]
    rows = []
    for name in names:
        b, a = fb.get(name), fa.get(name)
        delta = None if b is None or a is None else a - b
        # Missing type counts mean zero entities of that type, not "unknown".
        if name.startswith("type count: "):
            b, a = b or 0, a or 0
            delta = a - b
        rows.append((name, _fmt(b), _fmt(a), _fmt(delta, True), verdict(b, a)))
    width = max(len(r[0]) for r in rows)
    lines = [
        f"before: {before['label']} ({_ontology_text(before)})",
        f"after:  {after['label']} ({_ontology_text(after)})",
        *ontology_id_lines(before, after),
        "",
        f"{'metric':<{width}}  {'before':>9}  {'after':>9}  {'delta':>9}  verdict",
    ]
    for name, b, a, d, v in rows:
        lines.append(f"{name:<{width}}  {b:>9}  {a:>9}  {d:>9}  {v}")
    lines += ["", "verdicts (direction of change only):"]
    lines += [f"  {n}: {v}" for n, _, _, _, v in rows if not n.startswith("type count")]
    return "\n".join(lines)


def _ontology_text(snap: dict) -> str:
    vid = snap.get("ontology_version_id")
    if vid is None:
        return "ontology not recorded"
    if vid == "none":
        return "no active ontology version"
    return (
        f"ontology {snap.get('ontology_name')} rev {snap.get('ontology_revision')} "
        f"version {vid}"
    )


def format_snapshot(snap: dict) -> str:
    m = snap["metrics"]
    gb, dup, noise = m["generic_bucket"], m["duplicates"], m["noise"]
    by_pole = dup.get("by_pole") or {}
    pole_text = ", ".join(
        f"{pole} {by_pole[pole]['groups']}"
        for pole in COMPARED_POLES
        if pole in by_pole
    )
    lines = [
        f"snapshot: {snap['label']}  taken {snap['taken_at']}  source {snap['source']}",
        f"ontology: {_ontology_text(snap)}",
        f"entities: {m['total_entities']} fetched"
        + (
            f", API count {snap['api_entity_count']}"
            if snap.get("api_entity_count") is not None
            else ""
        ),
        _relationships_text(snap),
        _completeness_text(snap),
        "by type: " + ", ".join(f"{t}={n}" for t, n in m["by_type"].items()),
        f"generic (Object/Concept): {gb['count']} ({gb['share']:.1%})",
        f"duplicate groups: {dup['groups']} ({dup['excess']} excess entities); "
        f"by pole: {pole_text}",
    ]
    for etype, info in dup["by_type"].items():
        for ex in info["examples"][:3]:
            lines.append(f"  dup {etype}: {ex['forms']}")
    tc = m["type_conflicts"]
    lines.append(f"type conflicts: {tc['count']}")
    lines += [f"  {ex['key']!r}: {ex['types']}" for ex in tc["examples"][:3]]
    lines.append(f"noise: {noise['count']} ({noise['share']:.1%}) {noise['by_reason']}")
    lines.append(f"  examples: {noise['examples']}")
    lines.append("instance coverage (distinct):")
    for label, info in m["instance_coverage"].items():
        lines.append(
            f"  {label}: {info['distinct']} distinct, {info['entities']} entities"
        )
    conf = m["ontology_conformance"]
    if conf is None:
        lines.append("ontology conformance: skipped (no --ontology-yaml)")
    else:
        lines.append(
            f"ontology conformance: {conf['fraction']:.1%} "
            f"({conf['conforming']}/{m['total_entities']}); "
            f"top outside types {conf['top_outside_types']}"
        )
    return "\n".join(lines)


def _relationships_text(snap: dict) -> str:
    rels = snap.get("relationships")
    if rels is None:
        return "relationships: not available in this snapshot"
    note = f" ({snap['relationships_note']})" if snap.get("relationships_note") else ""
    return f"relationships: {len(rels)} edges{note}"


def _completeness_text(snap: dict) -> str:
    c = snap.get("completeness") or {}
    if c.get("conversations") is None:
        return "completeness: not recorded"
    expected = c.get("expected_turns")
    return (
        f"completeness: {c['conversations']} conversations, "
        f"{c['user_messages']} user / {c['assistant_messages']} assistant messages, "
        f"{c['traces']} traces"
        + (f"; expected {expected} turns" if expected is not None else "")
    )


# ---------------------------------------------------------------------------
# Gold-list scoring against the traffic ground truth
# ---------------------------------------------------------------------------

# kind -> (accepted labels under a custom ontology, accepted pole_types under the
# default one). Managers are people the analyst names; a custom ontology may type them
# as Analyst (REPORTS_TO is Analyst to Analyst) or Customer.
EXPECTED_TYPES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "Analyst": (frozenset({"Analyst"}), frozenset({"PERSON"})),
    "Manager": (frozenset({"Analyst", "Customer"}), frozenset({"PERSON"})),
    "Team": (frozenset({"Team"}), frozenset({"ORGANIZATION"})),
    "Case": (frozenset({"Case"}), frozenset({"OBJECT"})),
    "Community": (frozenset({"Community"}), frozenset({"OBJECT"})),
    "Account": (frozenset({"Account"}), frozenset({"OBJECT"})),
    "Phone": (frozenset({"PhoneNumber"}), frozenset({"OBJECT"})),
    "Merchant": (frozenset({"Merchant"}), frozenset({"ORGANIZATION"})),
}
# Kinds matched by identifier, so "Account 7321 ring" still counts as Account 7321.
_ID_KINDS = frozenset({"Case", "Community", "Account", "Phone"})
# scenarios.py keeps merchant names only in comments, so they are listed here, plus a
# suffix pattern for any other "Name LLC/PLC/Inc/Ltd" the prompts mention.
KNOWN_MERCHANTS = ("Serrano LLC", "Gutierrez PLC", "Barton Inc", "Thompson-Caldwell")
_MERCHANT_SUFFIX = re.compile(r"\b[A-Z][a-z]+(?:-[A-Z][a-z]+)? (?:LLC|PLC|Inc|Ltd)\b")
ALIAS_KINDS = ("analyst_first_name", "analyst_initial_surname", "team_abbreviation")


@dataclass
class Gold:
    """Ground truth derived from the prompts of a traffic run."""

    entities: dict[str, list[str]] = field(default_factory=dict)
    # (alias kind, canonical name, alias)
    aliases: list[tuple[str, str, str]] = field(default_factory=list)
    # (relationship type, source name, target name)
    relationships: list[tuple[str, str, str]] = field(default_factory=list)


def load_scenarios(path: Path) -> ModuleType:
    """Import scenarios.py by file path (it is not an installed package)."""
    if not path.is_file():
        raise SystemExit(f"scenarios file not found: {path}")
    name = "_nams_gold_scenarios"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _add_unique(bucket: list[str], name: str) -> None:
    key = normalize_name(name)
    if all(normalize_name(existing) != key for existing in bucket):
        bucket.append(name)


def derive_gold(prompts: list[str], scenarios: ModuleType) -> Gold:
    """Entities, aliases and relationships the prompts actually state or mention."""
    text = "\n".join(prompts)
    gold = Gold(entities={kind: [] for kind in EXPECTED_TYPES})
    ents = gold.entities
    for name in scenarios.ANALYSTS:
        if name not in text:
            continue
        _add_unique(ents["Analyst"], name)
        first, surname = name.split(" ", 1)
        rest = text.replace(name, "")
        if re.search(rf"\b{re.escape(first)}\b", rest):
            gold.aliases.append(("analyst_first_name", name, first))
        initial = f"{first[0]}. {surname}"
        if initial in rest:
            gold.aliases.append(("analyst_initial_surname", name, initial))
    for name in scenarios.MANAGERS:
        if name in text:
            _add_unique(ents["Manager"], name)
    for team, abbreviation in zip(scenarios.TEAMS, scenarios.TEAM_ABBREVIATIONS):
        if team in text:
            _add_unique(ents["Team"], team)
        if abbreviation in text:
            gold.aliases.append(("team_abbreviation", team, abbreviation))
    for kind, pattern in (
        ("Case", "case"),
        ("Community", "community"),
        ("Account", "account"),
        ("Phone", "phone"),
    ):
        for match in INSTANCE_PATTERNS[pattern].findall(text):
            _add_unique(ents[kind], match)
    for merchant in KNOWN_MERCHANTS:
        if merchant in text:
            _add_unique(ents["Merchant"], merchant)
    for merchant in _MERCHANT_SUFFIX.findall(text):
        _add_unique(ents["Merchant"], merchant)

    seen: set[tuple[str, str, str]] = set()

    def add_rel(rel: str, src: str, tgt: str) -> None:
        if (rel, src, tgt) not in seen:
            seen.add((rel, src, tgt))
            gold.relationships.append((rel, src, tgt))

    for prompt in prompts:
        analysts = [n for n in scenarios.ANALYSTS if n in prompt]
        if not analysts:
            continue
        analyst = analysts[0]
        for team in scenarios.TEAMS:
            if team in prompt:
                add_rel("MEMBER_OF", analyst, team)
        for manager in scenarios.MANAGERS:
            if f"report to {manager}" in prompt:
                add_rel("REPORTS_TO", analyst, manager)
        communities = re.findall(r"investigation of (Community \d+)", prompt)
        for case_id in re.findall(r"\bown case (CASE-\d+)", prompt, re.IGNORECASE):
            add_rel("OWNS", analyst, case_id)
            for community in communities:
                add_rel("INVESTIGATES", case_id, community)
    return gold


def is_custom_ontology(snap: dict) -> bool:
    """True when the snapshot's ontology is not the NAMS default.

    Uses the recorded domain id; without one (old snapshot, --from-file), custom means
    declared types include a label outside the default vocabulary.
    """
    domain = snap.get("ontology_domain_id")
    if domain:
        return domain != DEFAULT_ONTOLOGY_ID
    return any(
        label not in DEFAULT_TYPE_POLES for label in snap.get("declared_types") or []
    )


class _EntityIndex:
    """Normalized-name lookup over snapshot entities."""

    def __init__(self, entities: list[dict]) -> None:
        self.rows = [(e, normalize_name(_ename(e))) for e in entities]

    def find(self, name: str, kind: str) -> list[dict]:
        target = normalize_name(name)
        if kind in _ID_KINDS:
            pattern = re.compile(rf"(?<!\w){re.escape(target)}(?!\w)")
            return [e for e, norm in self.rows if pattern.search(norm)]
        return [e for e, norm in self.rows if norm == target]


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def score_gold(snap: dict, gold: Gold) -> dict:
    """Recall, type accuracy, alias resolution and relationship recall for a snapshot.

    Recall: a gold entity counts as found when any entity's normalized name matches.
    Type accuracy: among found, any matching entity has an expected type (custom
    ontology label, or pole_type under the default ontology). Alias resolution: the
    alias has no separate entity of its own (or the canonical entity lists it in
    `aliases`); aliases whose canonical entity is missing are reported separately.
    Relationships: `connected` is any edge between the two entities, `typed` also
    needs the expected relationship type (or the original name in `predicate`).
    """
    entities = snap.get("entities") or []
    index = _EntityIndex(entities)
    poles = snapshot_type_poles(snap)
    custom = is_custom_ontology(snap)

    def type_ok(kind: str, entity: dict) -> bool:
        labels, expected_poles = EXPECTED_TYPES[kind]
        if custom:
            return _etype(entity) in labels
        return pole_of(entity, poles) in expected_poles

    per_kind: dict[str, dict] = {}
    for kind, names in gold.entities.items():
        found = typed = 0
        for name in names:
            matches = index.find(name, kind)
            found += bool(matches)
            typed += any(type_ok(kind, e) for e in matches)
        per_kind[kind] = {
            "gold": len(names),
            "found": found,
            "recall": _rate(found, len(names)),
            "type_ok": typed,
            "type_accuracy": _rate(typed, found),
        }
    n_gold = sum(v["gold"] for v in per_kind.values())
    n_found = sum(v["found"] for v in per_kind.values())
    n_typed = sum(v["type_ok"] for v in per_kind.values())
    overall = {
        "gold": n_gold,
        "found": n_found,
        "recall": _rate(n_found, n_gold),
        "type_ok": n_typed,
        "type_accuracy": _rate(n_typed, n_found),
    }

    alias_stats = {
        kind: {"total": 0, "resolved": 0, "split": 0, "canonical_missing": 0}
        for kind in ALIAS_KINDS
    }
    for kind, canonical, alias in gold.aliases:
        entity_kind = "Team" if kind == "team_abbreviation" else "Analyst"
        stats = alias_stats[kind]
        stats["total"] += 1
        canonical_ents = index.find(canonical, entity_kind)
        alias_norm = normalize_name(alias)
        if not canonical_ents:
            stats["canonical_missing"] += 1
        elif any(
            alias_norm in {normalize_name(str(a)) for a in e.get("aliases") or []}
            for e in canonical_ents
        ):
            stats["resolved"] += 1
        elif any(
            norm == alias_norm and e not in canonical_ents for e, norm in index.rows
        ):
            stats["split"] += 1
        else:
            stats["resolved"] += 1
    measurable = sum(s["resolved"] + s["split"] for s in alias_stats.values())
    resolved = sum(s["resolved"] for s in alias_stats.values())
    aliases = {
        "by_kind": alias_stats,
        "resolved": resolved,
        "measurable": measurable,
        "rate": _rate(resolved, measurable),
    }
    return {
        "ontology_kind": "custom" if custom else "default",
        "entities": per_kind,
        "overall": overall,
        "aliases": aliases,
        "relationships": _score_relationships(snap, gold, index),
    }


def _score_relationships(snap: dict, gold: Gold, index: _EntityIndex) -> dict:
    edges = snap.get("relationships")
    if edges is None:
        reason = snap.get("relationships_note") or "snapshot has no relationships"
        return {"measurable": False, "reason": reason}
    if not any(e.get("id") for e, _ in index.rows):
        return {"measurable": False, "reason": "entities carry no ids to join edges"}
    kinds = {"MEMBER_OF": ("Analyst", "Team"), "REPORTS_TO": ("Analyst", "Manager")}
    kinds |= {"OWNS": ("Analyst", "Case"), "INVESTIGATES": ("Case", "Community")}
    rows: dict[str, dict] = {}
    for rel, src, tgt in gold.relationships:
        src_kind, tgt_kind = kinds[rel]
        label = f"{src_kind} {rel} {tgt_kind}"
        row = rows.setdefault(label, {"gold": 0, "connected": 0, "typed": 0})
        row["gold"] += 1
        src_ids = {e.get("id") for e in index.find(src, src_kind)}
        tgt_ids = {e.get("id") for e in index.find(tgt, tgt_kind)}
        connected = typed = False
        for edge in edges:
            s, t = edge.get("sourceId"), edge.get("targetId")
            if (s in src_ids and t in tgt_ids) or (s in tgt_ids and t in src_ids):
                connected = True
                names = {
                    str(edge.get("type", "")).upper(),
                    str(edge.get("predicate", "")).upper(),
                }
                if s in src_ids and t in tgt_ids and rel in names:
                    typed = True
        row["connected"] += connected
        row["typed"] += typed
    for row in rows.values():
        row["connected_recall"] = _rate(row["connected"], row["gold"])
        row["typed_recall"] = _rate(row["typed"], row["gold"])
    return {"measurable": True, "by_relationship": rows}


def flatten_gold(scores: dict) -> dict[str, float | None]:
    """Scalar gold rows for the compare table."""
    flat: dict[str, float | None] = {
        "gold recall: overall": scores["overall"]["recall"],
        "gold type accuracy: overall": scores["overall"]["type_accuracy"],
        "gold alias resolution": scores["aliases"]["rate"],
    }
    for kind, v in scores["entities"].items():
        flat[f"gold recall: {kind}"] = v["recall"]
    rels = scores["relationships"]
    if rels["measurable"]:
        for label, row in rels["by_relationship"].items():
            flat[f"gold rel typed: {label}"] = row["typed_recall"]
            flat[f"gold rel connected: {label}"] = row["connected_recall"]
    return flat


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def format_gold(scores: dict, header: str = "") -> str:
    lines = [header] if header else []
    lines.append(f"ontology kind: {scores['ontology_kind']}")
    lines.append(
        f"{'entity kind':<12} {'gold':>5} {'found':>5} {'recall':>7} "
        f"{'type ok':>7} {'type acc':>8}"
    )
    rows = [*scores["entities"].items(), ("OVERALL", scores["overall"])]
    for kind, v in rows:
        lines.append(
            f"{kind:<12} {v['gold']:>5} {v['found']:>5} {_pct(v['recall']):>7} "
            f"{v['type_ok']:>7} {_pct(v['type_accuracy']):>8}"
        )
    al = scores["aliases"]
    lines.append("")
    lines.append(
        f"alias resolution: {al['resolved']}/{al['measurable']} "
        f"({_pct(al['rate'])}) resolved to the canonical entity"
    )
    for kind, s in al["by_kind"].items():
        if s["total"]:
            lines.append(
                f"  {kind}: {s['resolved']} resolved, {s['split']} split into a "
                f"separate entity, {s['canonical_missing']} canonical entity missing"
            )
    rels = scores["relationships"]
    lines.append("")
    if not rels["measurable"]:
        lines.append(f"relationships: not measurable ({rels['reason']})")
    else:
        lines.append(
            f"{'relationship':<28} {'gold':>5} {'connected':>9} {'typed':>6}"
        )
        for label, r in rels["by_relationship"].items():
            lines.append(
                f"{label:<28} {r['gold']:>5} {_pct(r['connected_recall']):>9} "
                f"{_pct(r['typed_recall']):>6}"
            )
    return "\n".join(lines)


def gold_for_run(
    scenarios_path: Path, users: int, sessions: int, turns: int
) -> Gold:
    scenarios = load_scenarios(scenarios_path)
    requests = scenarios.build_requests(users, sessions, turns, run_id="gold")
    return derive_gold([r.prompt for r in requests], scenarios)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_entities_file(path: str) -> tuple[list[dict], list[dict] | None]:
    """A --from-file payload: an entity list, or {"entities", "relationships"}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("entities", []), data.get("relationships")
    return data, None


def cmd_snapshot(args: argparse.Namespace) -> int:
    declared = None
    yaml_poles: dict[str, str] = {}
    if args.ontology_yaml:
        yaml_path = Path(args.ontology_yaml)
        declared = load_declared_types(yaml_path)
        yaml_poles = load_declared_poles(yaml_path)
        if declared is None:
            print(f"note: {yaml_path} not found; skipping conformance", file=sys.stderr)

    if args.from_file:
        entities, relationships = _load_entities_file(args.from_file)
        if args.expect_turns is not None:
            print("note: --expect-turns ignored with --from-file", file=sys.stderr)
        snap = build_snapshot(
            args.label,
            entities,
            declared,
            None,
            f"file:{args.from_file}",
            None,
            None,
            relationships=relationships,
            relationships_note=(
                None if relationships is not None else "snapshot built from --from-file"
            ),
            extra_type_poles=yaml_poles,
        )
    else:
        key, endpoint = resolve_settings(dict(os.environ))
        with make_client(key, endpoint) as client:
            extraction: dict = {"waited": False}
            if not args.no_wait:
                try:
                    extraction = wait_for_extraction(
                        client, args.wait_timeout, args.poll_interval
                    )
                except ExtractionTimeout as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 2
            completeness = fetch_completeness(client)
            problems = check_completeness(completeness, args.expect_turns)
            if problems:
                label = "warning" if args.allow_incomplete else "error"
                print(
                    f"{label}: workspace does not hold {args.expect_turns} complete "
                    "turns (agent write failures are swallowed by design):",
                    file=sys.stderr,
                )
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                if not args.allow_incomplete:
                    print(
                        "snapshot not written; rerun with --allow-incomplete to "
                        "snapshot anyway.",
                        file=sys.stderr,
                    )
                    return EXIT_INCOMPLETE
            entities = fetch_all_entities(client)
            api_count = api_get(client, "/v1/entities/count").get("count")
            ontology = fetch_active_ontology(client)
            relationships, rel_note = fetch_relationships(client)
        if api_count is not None and api_count != len(entities):
            print(
                f"warning: fetched {len(entities)} entities, API count is {api_count}",
                file=sys.stderr,
            )
        snap = build_snapshot(
            args.label,
            entities,
            declared,
            ontology,
            endpoint,
            extraction,
            api_count,
            relationships=relationships,
            relationships_note=rel_note,
            completeness=completeness,
            expected_turns=args.expect_turns,
            extra_type_poles=yaml_poles,
        )

    out = Path(args.out)
    out.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    print(format_snapshot(snap))
    print(f"\nsaved {out}")
    return 0


def _read_snapshot(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_compare(args: argparse.Namespace) -> int:
    before = _read_snapshot(args.before)
    after = _read_snapshot(args.after)
    gold_before = gold_after = None
    if args.users is not None:
        gold = gold_for_run(Path(args.scenarios), args.users, args.sessions, args.turns)
        gold_before = score_gold(before, gold)
        gold_after = score_gold(after, gold)
    print(format_compare(before, after, gold_before, gold_after))
    return 0


def cmd_recompute(args: argparse.Namespace) -> int:
    snap = _read_snapshot(args.snapshot)
    declared = None
    yaml_poles: dict[str, str] = {}
    if args.ontology_yaml:
        declared = load_declared_types(Path(args.ontology_yaml))
        yaml_poles = load_declared_poles(Path(args.ontology_yaml))
    new = recompute_snapshot(snap, declared, yaml_poles)
    out = Path(args.out)
    out.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    print(format_snapshot(new))
    print(f"\nsaved {out}")
    return 0


def cmd_gold(args: argparse.Namespace) -> int:
    snap = _read_snapshot(args.snapshot)
    gold = gold_for_run(Path(args.scenarios), args.users, args.sessions, args.turns)
    header = (
        f"gold: {snap.get('label')}  users={args.users} sessions={args.sessions} "
        f"turns={args.turns}  ({_ontology_text(snap)})"
    )
    print(format_gold(score_gold(snap, gold), header))
    return 0


def _add_gold_args(parser: argparse.ArgumentParser, required: bool) -> None:
    parser.add_argument("--users", type=int, required=required)
    parser.add_argument("--sessions", type=int, required=required)
    parser.add_argument("--turns", type=int, required=required)
    parser.add_argument(
        "--scenarios",
        default=str(DEFAULT_SCENARIOS),
        help="path to traffic/nams_traffic/scenarios.py",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure NAMS extraction quality.")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="fetch entities, compute and save metrics")
    snap.add_argument("--label", required=True)
    snap.add_argument("--out", required=True, help="output JSON file")
    snap.add_argument("--ontology-yaml", help="YAML with entity_types[].label values")
    snap.add_argument("--no-wait", action="store_true", help="skip extraction wait")
    snap.add_argument("--wait-timeout", type=float, default=900.0, help="seconds")
    snap.add_argument("--poll-interval", type=float, default=10.0, help="seconds")
    snap.add_argument(
        "--expect-turns",
        type=int,
        help="require N conversations, N user and N assistant messages, N traces",
    )
    snap.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=f"with --expect-turns, warn instead of exiting {EXIT_INCOMPLETE}",
    )
    snap.add_argument(
        "--from-file",
        help="testing only: load entities from a local JSON list, no network",
    )
    snap.set_defaults(func=cmd_snapshot)

    cmp_ = sub.add_parser("compare", help="compare two snapshot files")
    cmp_.add_argument("before")
    cmp_.add_argument("after")
    _add_gold_args(cmp_, required=False)
    cmp_.set_defaults(func=cmd_compare)

    rec = sub.add_parser("recompute", help="recompute metrics from a saved snapshot")
    rec.add_argument("snapshot")
    rec.add_argument("--out", required=True, help="output JSON file")
    rec.add_argument("--ontology-yaml", help="YAML with entity_types[].label values")
    rec.set_defaults(func=cmd_recompute)

    gold = sub.add_parser("gold", help="score a snapshot against the traffic gold list")
    gold.add_argument("--snapshot", required=True)
    _add_gold_args(gold, required=True)
    gold.set_defaults(func=cmd_gold)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "compare":
        given = [v is not None for v in (args.users, args.sessions, args.turns)]
        if any(given) and not all(given):
            parser.error("compare needs --users, --sessions and --turns together")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

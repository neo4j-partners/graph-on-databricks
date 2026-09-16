"""Create or reconcile the canonical Finance Genie Genie Spaces.

The first run creates the BEFORE and AFTER spaces when their IDs are absent
from ``finance-genie/.env``. Their discovered IDs are written back to that
local, untracked file so later runs reconcile the same spaces. When an ID is
already configured, the script updates that space in place.

Usage (from finance-genie/enrichment-pipeline/ with ../.env in place):
    uv run setup/provision_genie_spaces.py

Exits 0 on success, 1 if any space fails the post-update assertion.

================================================================================
API NOTE — why this script depends on ai-dev-kit
================================================================================

The public Databricks SDK's `WorkspaceClient().genie.update_space(...)` takes
only `serialized_space` (an opaque full-payload JSON blob). Field-level
updates for `table_identifiers`, curated `sample_questions`, and instructions
live on the older `/api/2.0/data-rooms/...` REST surface (Genie was formerly
called "Data Rooms") and are not wrapped by the SDK.

The `databricks_tools_core.agent_bricks.manager.AgentBricksManager` from
ai-dev-kit already wraps every one of those REST calls:

    genie_get(space_id)                         → /api/2.0/data-rooms/{id}
    genie_update(space_id, table_identifiers)   → PATCH /api/2.0/data-rooms/{id}
    genie_list_questions(space_id)              → /api/2.0/data-rooms/{id}/curated-questions
    genie_update_sample_questions(space_id, …)  → /api/2.0/data-rooms/{id}/curated-questions/batch-actions
    genie_list_instructions(space_id)           → /api/2.0/data-rooms/{id}/instructions
    genie_add_text_instruction(space_id, …)     → POST   /api/2.0/data-rooms/{id}/instructions

The manager does *not* expose an instruction-deletion helper. We reach the
underlying `DELETE /api/2.0/data-rooms/{id}/instructions/{instruction_id}`
endpoint through the manager's private `_delete` method — localized to
`_delete_instruction()` below so the private-method dependency is visible.

References:
  - ai-dev-kit/databricks-tools-core/databricks_tools_core/agent_bricks/manager.py
  - ai-dev-kit/databricks-tools-core/databricks_tools_core/agent_bricks/models.py
    (GenieSpaceDict, InstructionDict, CuratedQuestionDict)
  - ai-dev-kit/databricks-mcp-server/databricks_mcp_server/tools/genie.py
    (the MCP server wraps the same manager with the same patterns)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

# --------------------------------------------------------------------------- #
# Contract — every run of this script enforces exactly these values.          #
# Any drift from these lists causes a diff to print and an update to fire.    #
# --------------------------------------------------------------------------- #
def table_contract(catalog_schema: str) -> tuple[list[str], list[str]]:
    """Return the BEFORE and AFTER table contracts for one UC schema."""
    base_tables = [
        f"{catalog_schema}.accounts",
        f"{catalog_schema}.merchants",
        f"{catalog_schema}.transactions",
        f"{catalog_schema}.account_links",
    ]
    gold_tables = [
        f"{catalog_schema}.gold_accounts",
        f"{catalog_schema}.gold_account_similarity_pairs",
        f"{catalog_schema}.gold_fraud_ring_communities",
    ]
    return base_tables, base_tables + gold_tables

# Sample questions — mirror the phrasings in jobs/genie_run.py so
# the Space UI surfaces the same questions that CI tests run.
BEFORE_QUESTIONS = [
    "Are there accounts that seem to be the hub of a money movement network "
    "that are potentially fraudulent?",
    "Find groups of accounts transferring money heavily among themselves.",
    "Which pairs of accounts have visited the most merchants in common?",
]
AFTER_QUESTIONS = [
    "Are there accounts that seem to be the hub of a money movement network "
    "that are potentially fraudulent?",
    "Find groups of accounts transferring money heavily among themselves.",
    "Which pairs of accounts have visited the most merchants in common?",
]

INSTRUCTION_TITLE = "Workshop instructions"
INSTRUCTIONS_FILE = Path(__file__).parent.parent / "genie_instructions.md"
BEFORE_SPACE_NAME = "Finance Genie — Before Graph Enrichment"
AFTER_SPACE_NAME = "Finance Genie — After Graph Enrichment"


# --------------------------------------------------------------------------- #
# Instruction-file parsing                                                    #
# --------------------------------------------------------------------------- #
_SECTION_RE = re.compile(
    r"<!-- BEGIN: (?P<name>[A-Z]+) -->\s*(?P<body>.*?)\s*<!-- END: (?P=name) -->",
    re.DOTALL,
)


def load_instruction_sections(path: Path) -> dict[str, str]:
    """Return {section_name: body} parsed from the markdown file."""
    if not path.is_file():
        raise FileNotFoundError(f"instructions file not found: {path}")
    text = path.read_text()
    sections = {m.group("name"): m.group("body").strip() for m in _SECTION_RE.finditer(text)}
    missing = {"BEFORE", "AFTER"} - set(sections)
    if missing:
        raise ValueError(
            f"instructions file {path} is missing sections: {sorted(missing)}"
        )
    return sections


# --------------------------------------------------------------------------- #
# Diff helpers                                                                #
# --------------------------------------------------------------------------- #
def print_list_diff(label: str, current: Iterable[str], expected: Iterable[str]) -> None:
    current_set = set(current or [])
    expected_set = set(expected)
    added = sorted(expected_set - current_set)
    removed = sorted(current_set - expected_set)
    unchanged = sorted(expected_set & current_set)
    print(f"  {label}:")
    if added:
        for x in added:
            print(f"    + {x}")
    if removed:
        for x in removed:
            print(f"    - {x}")
    if not added and not removed:
        print(f"    (no changes — {len(unchanged)} entries unchanged)")


# --------------------------------------------------------------------------- #
# Instruction replacement (delete-all then add-one)                           #
# --------------------------------------------------------------------------- #
def _delete_instruction(manager, space_id: str, instruction_id: str) -> None:
    """Delete a single instruction on a space.

    Reaches the manager's private `_delete` primitive because the public
    `genie_*` helpers do not expose an instruction-deletion method. If this
    ever breaks, the fallback is to port the three-line `requests.delete`
    call out of manager.py._delete into this module directly.
    """
    manager._delete(
        f"/api/2.0/data-rooms/{space_id}/instructions/{instruction_id}"
    )


def replace_text_instruction(manager, space_id: str, content: str) -> None:
    """Replace all existing instructions with one text instruction."""
    existing = manager.genie_list_instructions(space_id).get("instructions", [])
    for instr in existing:
        instr_id = instr.get("instruction_id")
        if instr_id:
            _delete_instruction(manager, space_id, instr_id)
    manager.genie_add_text_instruction(space_id, content, title=INSTRUCTION_TITLE)


# --------------------------------------------------------------------------- #
# Per-space provisioning                                                      #
# --------------------------------------------------------------------------- #
def provision(
    manager,
    *,
    label: str,
    space_id: str,
    expected_tables: list[str],
    expected_questions: list[str],
    instruction_content: str,
) -> list[str]:
    """Provision one space. Returns a list of problem strings (empty on success)."""
    print(f"\n── {label} space ({space_id}) " + "─" * max(0, 40 - len(label)))

    current = manager.genie_get(space_id)
    if current is None:
        return [f"{label}: space {space_id} not found"]

    current_tables = current.get("table_identifiers") or []
    current_questions_resp = manager.genie_list_questions(
        space_id, question_type="SAMPLE_QUESTION"
    )
    current_questions = [
        q.get("question_text", "")
        for q in current_questions_resp.get("curated_questions", [])
    ]

    print_list_diff("tables", current_tables, expected_tables)
    print_list_diff("sample_questions", current_questions, expected_questions)

    # Push the three updates.
    manager.genie_update(space_id, table_identifiers=expected_tables)
    manager.genie_update_sample_questions(space_id, expected_questions)
    replace_text_instruction(manager, space_id, instruction_content)

    # Post-update assertion — re-fetch and compare.
    problems: list[str] = []
    after = manager.genie_get(space_id) or {}
    after_tables = set(after.get("table_identifiers") or [])
    if after_tables != set(expected_tables):
        problems.append(
            f"{label}: table set mismatch after update. "
            f"expected={sorted(set(expected_tables))}, got={sorted(after_tables)}"
        )

    after_questions_resp = manager.genie_list_questions(
        space_id, question_type="SAMPLE_QUESTION"
    )
    after_questions = {
        q.get("question_text", "")
        for q in after_questions_resp.get("curated_questions", [])
    }
    if after_questions != set(expected_questions):
        problems.append(
            f"{label}: sample_questions mismatch after update. "
            f"expected={sorted(set(expected_questions))}, "
            f"got={sorted(after_questions)}"
        )

    after_instructions = manager.genie_list_instructions(space_id).get(
        "instructions", []
    )
    text_instructions = [
        i for i in after_instructions if i.get("instruction_type") == "TEXT_INSTRUCTION"
    ]
    if len(text_instructions) != 1:
        problems.append(
            f"{label}: expected exactly one TEXT_INSTRUCTION after update, "
            f"got {len(text_instructions)}"
        )

    if not problems:
        print(
            f"  OK — {len(expected_tables)} tables, "
            f"{len(expected_questions)} sample questions, 1 text instruction"
        )
    return problems


def ensure_space(
    manager,
    *,
    label: str,
    configured_id: str,
    display_name: str,
    warehouse_id: str,
    table_identifiers: list[str],
) -> str:
    """Return an existing space ID or create/find the canonical named space."""
    if configured_id:
        if manager.genie_get(configured_id) is None:
            raise ValueError(
                f"{label} space {configured_id} was not found. Remove its "
                f"GENIE_SPACE_ID_* entry from .env to create a replacement."
            )
        print(f"OK    using configured {label} Genie Space: {configured_id}")
        return configured_id

    found = manager.genie_find_by_name(display_name)
    if found:
        print(f"OK    found existing {label} Genie Space: {found.space_id}")
        return found.space_id

    created = manager.genie_create(
        display_name=display_name,
        warehouse_id=warehouse_id,
        table_identifiers=table_identifiers,
        description=f"Canonical Finance Genie {label.lower()} graph-enrichment demo.",
    )
    space_id = created.get("space_id")
    if not space_id:
        raise ValueError(f"{label} Genie Space creation returned no space_id: {created}")
    print(f"OK    created {label} Genie Space: {space_id}")
    return space_id


def persist_env_values(path: Path, values: dict[str, str]) -> None:
    """Upsert non-secret setup outputs into the local Finance Genie env file."""
    lines = path.read_text().splitlines()
    remaining = dict(values)
    updated: list[str] = []
    for line in lines:
        key, separator, _ = line.partition("=")
        if separator and key in remaining:
            updated.append(f"{key}={remaining.pop(key)}")
        else:
            updated.append(line)
    if remaining:
        updated.append("")
        updated.append("# Generated by make demo; do not edit these IDs by hand.")
        updated.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(updated) + "\n")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def main() -> None:
    pipeline_dir = Path(__file__).parent.parent
    root_env_path = pipeline_dir.parent / ".env"
    if not root_env_path.is_file():
        print(f"FAIL  .env not found at {root_env_path}")
        sys.exit(1)
    load_dotenv(root_env_path, override=True)

    profile = os.environ.get("DATABRICKS_PROFILE", "").strip()
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        print(f"OK    using Databricks profile: {profile}")

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    if not warehouse_id:
        print("FAIL  missing in .env: DATABRICKS_WAREHOUSE_ID")
        sys.exit(1)

    catalog = (
        os.environ.get("SILVER_CATALOG")
        or os.environ.get("CATALOG")
        or os.environ.get("DATABRICKS_CATALOG")
        or "graph-on-databricks"
    )
    schema = os.environ.get("SCHEMA") or os.environ.get("DATABRICKS_SCHEMA") or "graph-enriched-schema"
    before_tables, after_tables = table_contract(f"{catalog}.{schema}")

    try:
        sections = load_instruction_sections(INSTRUCTIONS_FILE)
    except (FileNotFoundError, ValueError) as e:
        print(f"FAIL  {e}")
        sys.exit(1)

    try:
        from databricks.sdk import WorkspaceClient
        from databricks_tools_core.agent_bricks.manager import AgentBricksManager
    except ImportError as e:
        print(f"FAIL  missing dependency: {e}")
        print(
            "      run `uv sync` in enrichment-pipeline/ — databricks-tools-core is a "
            "git dependency (see pyproject.toml [tool.uv.sources])."
        )
        sys.exit(1)

    try:
        ws = WorkspaceClient()
    except Exception as e:
        print(f"FAIL  WorkspaceClient() failed: {e}")
        sys.exit(1)

    manager = AgentBricksManager(client=ws)

    try:
        before_id = ensure_space(
            manager,
            label="BEFORE",
            configured_id=os.environ.get("GENIE_SPACE_ID_BEFORE", "").strip(),
            display_name=BEFORE_SPACE_NAME,
            warehouse_id=warehouse_id,
            table_identifiers=before_tables,
        )
        after_id = ensure_space(
            manager,
            label="AFTER",
            configured_id=os.environ.get("GENIE_SPACE_ID_AFTER", "").strip(),
            display_name=AFTER_SPACE_NAME,
            warehouse_id=warehouse_id,
            table_identifiers=after_tables,
        )
    except (ValueError, RuntimeError) as e:
        print(f"FAIL  {e}")
        sys.exit(1)

    persist_env_values(
        root_env_path,
        {
            "GENIE_SPACE_ID_BEFORE": before_id,
            "GENIE_SPACE_ID_AFTER": after_id,
            "GENIE_SPACE_ID": after_id,
        },
    )
    # The runner will write these values into the secret scope in its next
    # step. Set them in-process too so direct, stage-by-stage use is coherent.
    os.environ["GENIE_SPACE_ID_BEFORE"] = before_id
    os.environ["GENIE_SPACE_ID_AFTER"] = after_id

    problems: list[str] = []
    problems += provision(
        manager,
        label="BEFORE",
        space_id=before_id,
        expected_tables=before_tables,
        expected_questions=BEFORE_QUESTIONS,
        instruction_content=sections["BEFORE"],
    )
    problems += provision(
        manager,
        label="AFTER",
        space_id=after_id,
        expected_tables=after_tables,
        expected_questions=AFTER_QUESTIONS,
        instruction_content=sections["AFTER"],
    )

    print()
    if problems:
        print(f"FAIL  {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("PASS  BEFORE and AFTER spaces match the contract.")


if __name__ == "__main__":
    main()

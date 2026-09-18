"""Grounding panel: a set difference between retrieved and declared identifiers.

The serving endpoint declares the identifiers it used, tagged with the
retrieval tool call each came from. The app never parses the generated SQL or
Cypher to check this — it takes the set of names step 1 returned and the set
the model declared, and the difference is the panel. A declared name absent
from the retrieved set is a real finding (the model reached for something the
map did not give it), not a bug in the app.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeclaredIdentifier:
    """One identifier the model reports having used, tagged with its source tool."""

    name: str
    source_tool: str


@dataclass(frozen=True)
class GroundingRow:
    """One row of the grounding panel: a declared identifier and its status."""

    name: str
    source_tool: str
    retrieved: bool


def _bare_name(name: str) -> str:
    """Strip a table qualifier so `table.column` matches the bare retrieved name."""
    return name.rsplit(".", 1)[-1]


def ground(declared: list[DeclaredIdentifier], retrieved_names: set[str]) -> list[GroundingRow]:
    """Check each declared identifier for set membership in the retrieved names."""
    return [
        GroundingRow(
            name=item.name,
            source_tool=item.source_tool,
            retrieved=item.name in retrieved_names or _bare_name(item.name) in retrieved_names,
        )
        for item in declared
    ]

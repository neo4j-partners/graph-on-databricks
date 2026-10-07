"""Tool allowlist, read-only Cypher check, and result truncation for MCP tools."""

import json
import re
from typing import Any

from agents import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    ToolOutputGuardrailData,
    tool_input_guardrail,
    tool_output_guardrail,
)

ALLOWED_TOOLS = frozenset({"get_neo4j_schema", "read_neo4j_cypher"})
READ_CYPHER_TOOL = "read_neo4j_cypher"
MAX_AGENT_STEPS = 20
TOOL_RESULT_MAX_CHARS = 8000
TRUNCATION_MARKER = "[truncated]"

_STRING_OR_COMMENT = re.compile(
    r"""
    '(?:[^'\\]|\\.)*'      # single-quoted string
    | "(?:[^"\\]|\\.)*"    # double-quoted string
    | `[^`]*`              # backtick identifier
    | //[^\n]*             # line comment
    | /\*.*?\*/            # block comment
    """,
    re.VERBOSE | re.DOTALL,
)
_WRITE_PATTERN = re.compile(
    r"""
    (?<![\w.])(?:
        CREATE | MERGE | DELETE | DETACH | SET | REMOVE | DROP | FOREACH
        | LOAD\s+CSV
        | CALL\s*\{(?:[^{}]|\{[^{}]*\})*?\b(?:CREATE|MERGE|DELETE|DETACH|SET|REMOVE)\b
        | CALL\s+apoc\.(?:create|merge|refactor|periodic|trigger|cypher\.do|
                          cypher\.run|nodes\.delete|do)\w*
    )(?![\w])
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_read_only_cypher(query: str) -> bool:
    """Return True when the Cypher text contains no write clauses.

    String literals, backtick identifiers, and comments are ignored.
    """
    stripped = _STRING_OR_COMMENT.sub(" ", query)
    return _WRITE_PATTERN.search(stripped) is None


def truncate_text(text: str, limit: int) -> str:
    """Cut text to at most `limit` characters and append a truncation marker."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n{TRUNCATION_MARKER}"


def _matches_tool(name: str, allowed: str) -> bool:
    if name == allowed:
        return True
    return name.endswith(allowed) and not name[-len(allowed) - 1].isalnum()


def is_tool_allowed(name: str, allowed: frozenset[str] = ALLOWED_TOOLS) -> bool:
    return any(_matches_tool(name, tool) for tool in allowed)


def allowed_tool_filter(_context: Any, tool: Any) -> bool:
    """MCP `tool_filter` callable that exposes only the allowlisted tools."""
    return is_tool_allowed(tool.name)


@tool_input_guardrail
def read_only_cypher_guardrail(
    data: ToolInputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Reject read_neo4j_cypher calls that contain write clauses."""
    if not _matches_tool(data.context.tool_name, READ_CYPHER_TOOL):
        return ToolGuardrailFunctionOutput.allow()
    try:
        query = json.loads(data.context.tool_arguments or "{}").get("query", "")
    except (json.JSONDecodeError, AttributeError):
        query = None
    if not isinstance(query, str) or not is_read_only_cypher(query):
        return ToolGuardrailFunctionOutput.reject_content(
            "Error: Only read-only Cypher is permitted. Rewrite without writes."
        )
    return ToolGuardrailFunctionOutput.allow()


@tool_output_guardrail
def truncate_result_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Replace oversized tool results with a truncated copy."""
    if isinstance(data.output, str) and len(data.output) > TOOL_RESULT_MAX_CHARS:
        return ToolGuardrailFunctionOutput.reject_content(
            truncate_text(data.output, TOOL_RESULT_MAX_CHARS)
        )
    return ToolGuardrailFunctionOutput.allow()


def apply_mcp_guardrails(server: Any) -> None:
    """Attach the tool allowlist and the Cypher and result guardrails to an MCP server."""
    server.tool_filter = allowed_tool_filter
    server.tool_input_guardrails = [read_only_cypher_guardrail]
    server.tool_output_guardrails = [truncate_result_guardrail]

import json
from types import SimpleNamespace

import pytest

from agent.guardrails import (
    ALLOWED_TOOLS,
    TOOL_RESULT_MAX_CHARS,
    allowed_tool_filter,
    is_read_only_cypher,
    is_tool_allowed,
    read_only_cypher_guardrail,
    truncate_result_guardrail,
    truncate_text,
)


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (a:Account) RETURN a LIMIT 5",
        "MATCH (a:Account)-[:SIMILAR_TO]->(b) RETURN a.id, b.id",
        "OPTIONAL MATCH (a:Account) RETURN count(a) AS n",
        (
            "MATCH (a:Account) WITH a.community_id AS c, avg(a.risk_score) AS r "
            "WHERE r >= 1.0 RETURN c, r ORDER BY r DESC"
        ),
        "match (a) return a.offset",
        "MATCH (a {offset: 3}) RETURN a",
        "MATCH (a)\nWHERE a.name = 'SET and DELETE'\nRETURN a",
        'MATCH (a) WHERE a.note = "please CREATE it" RETURN a',
        "MATCH (a) RETURN a.created_at, a.settled",
    ],
)
def test_read_queries_accepted(query: str) -> None:
    assert is_read_only_cypher(query)


@pytest.mark.parametrize(
    "query",
    [
        "CREATE (n:Account {id: 1})",
        "MERGE (n:Account {id: 1})",
        "MATCH (n) DELETE n",
        "MATCH (n) DETACH DELETE n",
        "MATCH (n) SET n.risk_score = 0",
        "MATCH (n) REMOVE n.risk_score",
        "DROP INDEX my_index",
        "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        "match (n) detach delete n",
        "MaTcH (n)\nWITH n\nSeT n.x = 1\nRETURN n",
        "MATCH (n)\n  RETURN n\n  ;\nCREATE (m)",
        "MATCH (a) WHERE a.name = 'ok' SET a.x = 1",
    ],
)
def test_write_queries_rejected(query: str) -> None:
    assert not is_read_only_cypher(query)


def test_allowed_tools() -> None:
    assert ALLOWED_TOOLS == frozenset({"get_neo4j_schema", "read_neo4j_cypher"})


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("read_neo4j_cypher", True),
        ("get_neo4j_schema", True),
        ("neo4j-mcp-server-target___read_neo4j_cypher", True),
        ("write-cypher", False),
        ("myread_neo4j_cypher", False),
    ],
)
def test_tool_allowlist(name: str, allowed: bool) -> None:
    assert is_tool_allowed(name) is allowed
    assert allowed_tool_filter(None, SimpleNamespace(name=name)) is allowed


def test_truncate_text_under_and_at_limit_unchanged() -> None:
    assert truncate_text("abc", 10) == "abc"
    assert truncate_text("abcde", 5) == "abcde"


def test_truncate_text_over_limit_is_shortened() -> None:
    text = "x" * 100
    result = truncate_text(text, 10)
    assert result != text
    assert result.startswith("x" * 10)
    assert len(result) < len(text)


def _input_data(tool_name: str, arguments: str) -> SimpleNamespace:
    context = SimpleNamespace(tool_name=tool_name, tool_arguments=arguments)
    return SimpleNamespace(context=context)


def _behavior(output) -> str:
    return output.behavior["type"]


def test_input_guardrail_allows_read_query() -> None:
    args = json.dumps({"query": "MATCH (a) RETURN a LIMIT 1"})
    out = read_only_cypher_guardrail.guardrail_function(
        _input_data("read_neo4j_cypher", args)
    )
    assert _behavior(out) == "allow"


@pytest.mark.parametrize(
    "arguments",
    [json.dumps({"query": "MATCH (n) DETACH DELETE n"}), "not json", "[]"],
)
def test_input_guardrail_rejects_writes_and_malformed_args(arguments: str) -> None:
    out = read_only_cypher_guardrail.guardrail_function(
        _input_data("read_neo4j_cypher", arguments)
    )
    assert _behavior(out) == "reject_content"


def test_input_guardrail_ignores_other_tools() -> None:
    out = read_only_cypher_guardrail.guardrail_function(_input_data("get_neo4j_schema", "{}"))
    assert _behavior(out) == "allow"


def test_output_guardrail_truncates_only_oversized_results() -> None:
    small = SimpleNamespace(output="ok")
    assert _behavior(truncate_result_guardrail.guardrail_function(small)) == "allow"

    big = SimpleNamespace(output="x" * (TOOL_RESULT_MAX_CHARS * 2))
    out = truncate_result_guardrail.guardrail_function(big)
    assert _behavior(out) == "reject_content"
    assert len(out.behavior["message"]) < len(big.output)

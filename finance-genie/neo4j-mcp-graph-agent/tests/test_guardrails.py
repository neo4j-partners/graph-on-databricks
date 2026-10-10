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


@pytest.mark.parametrize(
    "query",
    [
        "CALL db.labels()",
        "CALL db.labels",
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
        "CALL db.propertyKeys()",
        "CALL db.schema.visualization()",
        "CALL db.schema.nodeTypeProperties()",
        "CALL apoc.meta.schema() YIELD value RETURN value",
        "CALL apoc.meta.data()",
        "CALL db . labels()",
        (
            "MATCH (a:Account) CALL { WITH a MATCH (a)-[:SIMILAR_TO]->(b) "
            "RETURN count(b) AS n } RETURN n"
        ),
        "MATCH (a:Account) CALL (a) { MATCH (a)-[:SIMILAR_TO]->(b) RETURN count(b) AS n } RETURN n",
    ],
)
def test_read_procedures_and_subqueries_accepted(query: str) -> None:
    assert is_read_only_cypher(query)


@pytest.mark.parametrize(
    "query",
    [
        "CALL dbms.components()",
        "CALL dbms.killQuery('query-1')",
        "CALL dbms.security.createUser('x', 'y')",
        "CALL apoc.load.json('https://example.com/x.json') YIELD value RETURN value",
        "CALL apoc.load.csv('file:///x.csv')",
        "CALL apoc.import.csv([], [], {})",
        "CALL apoc.export.csv.all('x.csv', {})",
        "CALL db.index.fulltext.queryNodes('idx', 'x')",
        "CALL `apoc.load.json`('https://example.com/x.json')",
        "CALL db.`labels`()",
        "CALL/* hidden */dbms.components()",
        "MATCH (n) WITH n CALL apoc.cypher.run('MATCH (m) RETURN m', {}) YIELD value RETURN value",
        "CALL",
    ],
)
def test_procedures_off_the_allowlist_rejected(query: str) -> None:
    assert not is_read_only_cypher(query)


@pytest.mark.parametrize(
    "query",
    [
        "ALTER USER bob SET PASSWORD 'x'",
        "ALTER DATABASE neo4j SET ACCESS READ WRITE",
        "GRANT ROLE admin TO bob",
        "DENY READ {*} ON GRAPH * TO bob",
        "REVOKE ROLE reader FROM bob",
        "RENAME USER bob TO alice",
        "RENAME ROLE analyst TO admin",
        "START DATABASE neo4j",
        "STOP DATABASE neo4j",
        "stop  database neo4j",
        "TERMINATE TRANSACTIONS 'neo4j-transaction-1'",
        "USE system SHOW USERS",
        "USE neo4j MATCH (n) RETURN n",
    ],
)
def test_admin_clauses_rejected(query: str) -> None:
    assert not is_read_only_cypher(query)


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (t:Transaction) RETURN t.set_date",
        "MATCH (t:Transaction) WHERE t.set_date > date('2024-01-01') RETURN t",
        "WITH 1 AS set_date RETURN set_date",
        "MATCH (a:Account) RETURN a.grant_id, a.use, a.start_database",
        "MATCH (a)-[:USES]->(d:Device) RETURN a, d",
        "MATCH (a) WHERE a.note = 'CREATE a node, then CALL dbms.killQuery' RETURN a",
        'MATCH (a) WHERE a.memo = "USE system; GRANT ROLE admin" RETURN a',
        "MATCH (a) // CALL apoc.load.json and CREATE here are only a comment\nRETURN a",
        "MATCH (n:`CREATE`) RETURN n",
        "MATCH (a) RETURN a.startDate, a.stopped",
    ],
)
def test_admin_and_procedure_checks_have_no_false_positives(query: str) -> None:
    assert is_read_only_cypher(query)


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

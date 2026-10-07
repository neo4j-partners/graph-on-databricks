from __future__ import annotations

import pytest

from neo4j_mcp_graph_agent import (
    ALLOWED_TOOLS,
    is_read_only_cypher,
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
    assert ALLOWED_TOOLS == frozenset({"get-schema", "read-cypher"})


def test_truncate_text_under_and_at_limit_unchanged() -> None:
    assert truncate_text("abc", 10) == "abc"
    assert truncate_text("abcde", 5) == "abcde"


def test_truncate_text_over_limit_is_shortened() -> None:
    text = "x" * 100
    result = truncate_text(text, 10)
    assert result != text
    assert result.startswith("x" * 10)
    assert len(result) < len(text)

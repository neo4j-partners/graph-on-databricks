"""Non-live tests for the read-only local demo guard and question loading."""

from __future__ import annotations

import pytest

from finance_genie_dbxcarta import local_demo


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1",
        "  select count(*) from t  ",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "EXPLAIN SELECT 1",
        "SELECT 1;",
    ],
)
def test_read_only_sql_allowed(statement: str) -> None:
    local_demo._ensure_read_only_sql(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "DROP TABLE t",
        "DELETE FROM t",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "CREATE TABLE t (a INT)",
        "MERGE INTO t USING s ON t.a = s.a",
        "SELECT 1; DROP TABLE t",
        "",
    ],
)
def test_read_only_sql_rejected(statement: str) -> None:
    with pytest.raises(ValueError):
        local_demo._ensure_read_only_sql(statement)


def test_default_questions_load() -> None:
    questions = local_demo._load_local_questions(str(local_demo.DEFAULT_QUESTIONS))
    assert len(questions) == 12
    assert questions[0].question_id == "fg_q01"


def test_resolve_question_by_id() -> None:
    row = local_demo._resolve_question(
        None, "fg_q07", str(local_demo.DEFAULT_QUESTIONS)
    )
    assert row.question_id == "fg_q07"
    assert "account_labels" in (row.reference_sql or "")


def test_resolve_question_unknown_id() -> None:
    with pytest.raises(ValueError):
        local_demo._resolve_question(
            None, "nope", str(local_demo.DEFAULT_QUESTIONS)
        )

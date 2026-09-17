"""Retrieve cross-system context for curated Finance Genie business concepts.

The module is intentionally independent of Neocarta's internal server factory. The
minimal integration point is a call to :func:`register` from ``create_mcp_server``
after the catalog tools have been registered.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, Protocol

from neo4j import RoutingControl

logger = logging.getLogger(__name__)

BUSINESS_TERM_VECTOR_INDEX = "businessterm_vector_index"
MAX_QUERY_LENGTH = 500
MAX_RESULTS = 20

VECTOR_SEARCH_CYPHER = """CYPHER 25
MATCH (concept:BusinessTerm)
SEARCH concept IN (VECTOR INDEX businessterm_vector_index FOR $embedding LIMIT $candidate_limit)
SCORE AS score
WHERE concept:BusinessConcept
RETURN concept {
  .id, .name, .definition, .description, .interpretation,
  .source_catalog, .source_schema, .databricks_mapping, .neo4j_mapping
} AS concept, score
ORDER BY score DESC, concept.id ASC
LIMIT $max_results
""".strip()

LEXICAL_SEARCH_CYPHER = """CYPHER 25
MATCH (concept:BusinessConcept)
WITH concept,
     toLower(
       coalesce(concept.id, '') + ' ' +
       coalesce(concept.name, '') + ' ' +
       coalesce(concept.definition, '') + ' ' +
       coalesce(concept.interpretation, '') + ' ' +
       coalesce(concept.search_text, '')
     ) AS searchable
WITH concept,
     reduce(
       token_score = 0,
       token IN $tokens |
       token_score + CASE WHEN searchable CONTAINS token THEN 1 ELSE 0 END
     ) AS token_score,
     CASE
       WHEN toLower(coalesce(concept.id, '')) = $normalized_text OR
            toLower(coalesce(concept.name, '')) = $normalized_text
       THEN 100
       ELSE 0
     END AS exact_score
WHERE token_score > 0 OR exact_score > 0
RETURN concept {
         .id, .name, .definition, .description, .interpretation,
         .source_catalog, .source_schema, .databricks_mapping, .neo4j_mapping
       } AS concept,
       toFloat(exact_score + token_score) / (100 + size($tokens)) AS score
ORDER BY score DESC, concept.id ASC
LIMIT $max_results
""".strip()

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
_TABLE_COLUMN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.`-])(?P<table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])"
)


class Embedder(Protocol):
    """The subset of Neocarta's embedding connector used by this module."""

    async def _create_embedding_async(self, text_content: str) -> list[float]: ...


class AsyncQueryDriver(Protocol):
    """The subset of the Neo4j async driver used by this module."""

    async def execute_query(self, query_: str, **kwargs: Any) -> list[Mapping[str, Any]]: ...


def _tokens(text_content: str) -> list[str]:
    """Return unique normalized tokens in deterministic order."""
    return sorted(set(_TOKEN_PATTERN.findall(text_content.casefold())))


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Decode one canonical mapping property from the semantic graph."""
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a JSON object")

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{field_name} is not valid JSON") from error
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to a JSON object")
    return decoded


def _strings(value: Any) -> list[str]:
    """Normalize an optional string or sequence of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise ValueError("mapping list values must be strings or lists of strings")


def _qualified_table(catalog: str, schema: str, table: str) -> str:
    """Catalog-qualify a table unless it is already qualified."""
    prefix = f"{catalog}.{schema}."
    return table if table.startswith(prefix) else f"{prefix}{table}"


def _qualified_column(catalog: str, schema: str, table: str, column: str) -> str:
    """Catalog-qualify a column reference."""
    prefix = f"{catalog}.{schema}."
    if column.startswith(prefix):
        return column
    if "." in column:
        return f"{prefix}{column}"
    return f"{prefix}{table}.{column}"


def _qualify_table_columns(expression: str, catalog: str, schema: str) -> str:
    """Qualify table-column references in a curated SQL mapping expression."""
    prefix = f"{catalog}.{schema}."
    if expression.startswith(prefix):
        return expression

    return _TABLE_COLUMN_PATTERN.sub(
        lambda match: f"{prefix}{match.group('table')}.{match.group('column')}",
        expression,
    )


def _qualify_predicate(
    predicate: str,
    *,
    catalog: str,
    schema: str,
    primary_table: str,
    columns: list[str],
) -> str:
    """Qualify mapped predicate columns without interpreting SQL or its values."""
    qualified = _qualify_table_columns(predicate, catalog, schema)
    for column in sorted({item.rsplit(".", 1)[-1] for item in columns}, key=len, reverse=True):
        qualified = re.sub(
            rf"(?<![A-Za-z0-9_.]){re.escape(column)}(?![A-Za-z0-9_])",
            f"{catalog}.{schema}.{primary_table}.{column}",
            qualified,
        )
    return qualified


def _databricks_context(concept: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Build catalog-qualified, deterministic Databricks mapping context."""
    catalog = str(concept.get("source_catalog", ""))
    schema = str(concept.get("source_schema", ""))
    if not catalog or not schema:
        raise ValueError("business concept is missing source_catalog or source_schema")

    table_names = _strings(mapping.get("table")) + _strings(mapping.get("tables"))
    table_names = sorted(set(table_names))
    if not table_names:
        raise ValueError("databricks mapping must contain a table or tables")
    primary_table = str(mapping.get("table") or table_names[0])
    raw_columns = _strings(mapping.get("columns"))

    return {
        "catalog": catalog,
        "schema": schema,
        "tables": [_qualified_table(catalog, schema, table) for table in table_names],
        "columns": sorted(
            {_qualified_column(catalog, schema, primary_table, column) for column in raw_columns}
        ),
        "join_keys": sorted(
            {
                _qualify_table_columns(join_key, catalog, schema)
                for join_key in _strings(mapping.get("join_keys"))
            }
        ),
        "predicates": sorted(
            {
                _qualify_predicate(
                    predicate,
                    catalog=catalog,
                    schema=schema,
                    primary_table=primary_table,
                    columns=raw_columns,
                )
                for predicate in _strings(mapping.get("predicate"))
                + _strings(mapping.get("predicates"))
            }
        ),
    }


def _neo4j_context(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic operational-graph schema context."""
    properties = mapping.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypeError("neo4j mapping properties must be an object")

    result: dict[str, Any] = {
        "database": str(mapping.get("database", "neo4j")),
        "node_labels": sorted(set(_strings(mapping.get("node_labels")))),
        "relationship_types": sorted(set(_strings(mapping.get("relationship_types")))),
        "properties": {
            str(owner): sorted(set(_strings(property_names)))
            for owner, property_names in sorted(properties.items())
        },
        "paths": sorted(set(_strings(mapping.get("paths")))),
    }
    if mapping.get("known_gap"):
        result["known_gap"] = str(mapping["known_gap"])
    return result


def normalize_business_concept(
    concept: Mapping[str, Any],
    *,
    score: float | None,
) -> dict[str, Any]:
    """Normalize one curated concept into the public JSON-safe contract."""
    databricks_mapping = _mapping(concept.get("databricks_mapping"), "databricks_mapping")
    neo4j_mapping = _mapping(concept.get("neo4j_mapping"), "neo4j_mapping")
    return {
        "concept_id": str(concept.get("id", "")),
        "name": str(concept.get("name", "")),
        "definition": str(concept.get("definition") or concept.get("description") or ""),
        "interpretation": str(concept.get("interpretation", "")),
        "score": None if score is None else round(float(score), 6),
        "databricks": _databricks_context(concept, databricks_mapping),
        "neo4j": _neo4j_context(neo4j_mapping),
    }


def _normalized_match(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a Neo4j result row into the public JSON-safe contract."""
    raw_concept = row.get("concept")
    if not isinstance(raw_concept, Mapping):
        try:
            concept = dict(raw_concept)
        except (TypeError, ValueError) as error:
            raise ValueError("retrieval row is missing a business concept") from error
    else:
        concept = dict(raw_concept)
    return normalize_business_concept(concept, score=float(row.get("score", 0.0)))


async def _execute(
    neo4j_driver: AsyncQueryDriver,
    neo4j_database: str,
    query: str,
    parameters: dict[str, Any],
) -> list[Mapping[str, Any]]:
    """Execute one read query through the same interface Neocarta uses."""
    return await neo4j_driver.execute_query(
        query_=query,
        parameters_=parameters,
        database_=neo4j_database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda result: result.data(),
    )


async def get_business_concept_context(
    text_content: str,
    neo4j_driver: AsyncQueryDriver,
    neo4j_database: str,
    embedder: Embedder | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    """Find curated business concepts and their lakehouse and graph mappings.

    Vector retrieval is preferred when an embedder and online vector index are
    available. Any failure at that optional integration boundary falls back to a
    parameterized lexical scan over the five metadata-only business concepts.
    Source records and operational graph entities are never queried.
    """
    if not isinstance(text_content, str) or not text_content.strip():
        raise ValueError("text_content must be a non-empty string")
    text_content = text_content.strip()
    if len(text_content) > MAX_QUERY_LENGTH:
        raise ValueError(f"text_content must be at most {MAX_QUERY_LENGTH} characters")
    if not isinstance(max_results, int) or isinstance(max_results, bool):
        raise TypeError("max_results must be an integer")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}")

    rows: list[Mapping[str, Any]] = []
    retrieval_mode = "lexical"
    if embedder is not None:
        try:
            embedding = await embedder._create_embedding_async(text_content)
            if not embedding:
                raise ValueError("embedding provider returned an empty vector")
            rows = await _execute(
                neo4j_driver,
                neo4j_database,
                VECTOR_SEARCH_CYPHER,
                {
                    "candidate_limit": max(max_results * 2, 10),
                    "embedding": embedding,
                    "max_results": max_results,
                },
            )
            retrieval_mode = "vector"
        except Exception as error:  # noqa: BLE001 - optional providers vary in error type.
            logger.warning("Business-concept vector retrieval unavailable: %s", error)
            rows = []

    if not rows:
        normalized_text = " ".join(_TOKEN_PATTERN.findall(text_content.casefold()))
        rows = await _execute(
            neo4j_driver,
            neo4j_database,
            LEXICAL_SEARCH_CYPHER,
            {
                "tokens": _tokens(text_content),
                "normalized_text": normalized_text,
                "max_results": max_results,
            },
        )
        retrieval_mode = "lexical"

    matches = [_normalized_match(row) for row in rows]
    matches.sort(key=lambda match: (-match["score"], match["concept_id"]))
    return {
        "query": text_content,
        "retrieval_mode": retrieval_mode,
        "matches": matches[:max_results],
    }


_retrieve_business_context = get_business_concept_context


def register(
    server: Any,
    neo4j_driver: AsyncQueryDriver,
    neo4j_database: str,
    embedder: Embedder | None = None,
) -> None:
    """Register ``get_business_concept_context`` on a FastMCP-compatible server."""

    @server.tool()
    async def get_business_concept_context(
        text_content: str,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Return definitions and cross-system mappings for a business phrase."""
        return await _retrieve_business_context(
            text_content=text_content,
            neo4j_driver=neo4j_driver,
            neo4j_database=neo4j_database,
            embedder=embedder,
            max_results=max_results,
        )

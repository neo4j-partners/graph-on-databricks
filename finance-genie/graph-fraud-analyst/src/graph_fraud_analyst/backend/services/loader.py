"""Load-screen service: real Cypher → Delta materialization.

The `/api/load` endpoint pulls selected communities (ring_ids) or communities
resolved from selected account ids from Neo4j via live Cypher, derives every
column the `gold_schema.sql` contract defines, then writes three Delta tables
that Screen 3's Genie Space queries:

    gold_accounts                     all :Account nodes in the loaded rings
    gold_fraud_ring_communities       per-community summary rows
    gold_account_similarity_pairs     deduped :SIMILAR_TO pairs

Schema parity with `enrichment-pipeline/sql/gold_schema.sql` is intentional:
Genie's space is tuned against that contract, so the Load output must match
column-for-column. Each Load overwrites the previous session's data (single-
presenter demo).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable

from databricks.sdk import WorkspaceClient
from neo4j import Driver

from ..core._config import AppConfig
from ..models import LoadOut, LoadStep, QualityCheck
from . import sql

# Pipeline's is_ring_candidate / is_ring_community gate (gold_schema.sql lines
# 32 and 54). A community qualifies when it has between 50 and 200 members
# AND avg_risk_score > 1.0. Keep these in sync with the pipeline.
_RING_MIN_MEMBERS = 50
_RING_MAX_MEMBERS = 200
_RING_AVG_RISK_MIN = 1.0

# A member is "high risk" when its risk_score (PageRank) exceeds this gate.
# Matches gold_schema.sql gold_fraud_ring_communities.high_risk_member_count.
_HIGH_RISK_MEMBER_GATE = 1.0

# Cap deduped similarity pairs to keep the VALUES clause within the SQL
# warehouse statement-size limit. With a 2-ring Load the deduped pair count
# is typically well under 2000.
_SIMILARITY_ROW_CAP = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_ring_ids(ring_ids: list[str]) -> list[int]:
    out: list[int] = []
    for rid in ring_ids:
        try:
            out.append(int(str(rid).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _coerce_account_ids(account_ids: list[str]) -> list[int]:
    out: list[int] = []
    for account_id in account_ids:
        try:
            out.append(int(str(account_id).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _step_labels() -> list[str]:
    return [
        "Fetch :Account members and per-account features from Neo4j",
        "Fetch community summaries and topology stats from Neo4j",
        "Fetch :SIMILAR_TO pairs from Neo4j",
        "Write gold_accounts Delta table",
        "Write gold_fraud_ring_communities Delta table",
        "Write gold_account_similarity_pairs Delta table",
        "Run quality checks",
    ]


def _sql_literal(value: Any) -> str:
    """Render a Python value as a Spark SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "NULL"
        return repr(value)
    if isinstance(value, int):
        return repr(value)
    if isinstance(value, datetime):
        return f"TIMESTAMP '{value.isoformat(sep=' ')}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    if isinstance(value, list):
        return f"ARRAY({', '.join(_sql_literal(v) for v in value)})"
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _rows_to_values_clause(
    rows: Iterable[dict[str, Any]], columns: list[str]
) -> str:
    row_tuples = []
    for r in rows:
        row_tuples.append(
            "(" + ", ".join(_sql_literal(r.get(c)) for c in columns) + ")"
        )
    if not row_tuples:
        return ""
    return "VALUES " + ", ".join(row_tuples)


def _write_table(
    ws: WorkspaceClient,
    config: AppConfig,
    table: str,
    columns_with_types: list[tuple[str, str]],
    rows: list[dict[str, Any]],
) -> int:
    columns = [c for c, _ in columns_with_types]
    qualified = f"`{config.catalog}`.`{config.schema_}`.`{table}`"
    column_decls = ", ".join(f"`{c}` {t}" for c, t in columns_with_types)

    if not rows:
        sql.execute(
            ws,
            config.warehouse_id,
            f"CREATE OR REPLACE TABLE {qualified} ({column_decls}) USING DELTA",
        )
        return 0

    values_clause = _rows_to_values_clause(rows, columns)
    column_list = ", ".join(f"`{c}`" for c in columns)
    statement = (
        f"CREATE OR REPLACE TABLE {qualified} USING DELTA AS "
        f"SELECT * FROM ({values_clause}) AS t({column_list})"
    )
    sql.execute(ws, config.warehouse_id, statement)
    return len(rows)


def _coerce_neo4j_date(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_native"):
        try:
            return value.to_native()
        except Exception:
            return None
    return value


def _normalize_accounts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in rows:
        r["opened_date"] = _coerce_neo4j_date(r.get("opened_date"))
    return rows


def _classify_topology(avg_deg: float, max_deg: float) -> str:
    """Classify a community's within-community transfer subgraph.

    Heuristic mirrors simple-finance-analyst's pickLayout: a high-degree
    central node (hub) suggests star; uniformly low degree suggests chain;
    everything else is mesh.
    """
    if max_deg >= 5 and max_deg >= avg_deg * 2.5:
        return "star"
    if avg_deg <= 2.5 and max_deg <= 3:
        return "chain"
    return "mesh"


# ---------------------------------------------------------------------------
# Cypher queries
# ---------------------------------------------------------------------------


_ACCOUNTS_CYPHER = """
MATCH ()-[t:TRANSACTED_WITH]->()
WITH max(t.txn_timestamp) AS max_ts
MATCH (a:Account) WHERE a.community_id IN $community_ids
OPTIONAL MATCH (a)-[txn:TRANSACTED_WITH]->(m:Merchant)
  WHERE txn.txn_timestamp > max_ts - duration({days: 30})
WITH a, max_ts,
     count(txn)        AS txn_count_30d,
     count(DISTINCT m) AS distinct_merchant_count_30d
OPTIONAL MATCH (src:Account)-[:TRANSFERRED_TO]->(a)
WITH a, txn_count_30d, distinct_merchant_count_30d,
     count(src) AS inbound_transfer_events
OPTIONAL MATCH (a)-[:TRANSFERRED_TO]-(cp:Account)
WITH a, txn_count_30d, distinct_merchant_count_30d, inbound_transfer_events,
     count(DISTINCT cp) AS distinct_counterparty_count
RETURN a.account_id              AS account_id,
       a.account_hash            AS account_hash,
       a.account_name            AS account_name,
       a.account_type            AS account_type,
       a.region                  AS region,
       a.balance                 AS balance,
       a.opened_date             AS opened_date,
       a.holder_age              AS holder_age,
       a.risk_score              AS risk_score,
       a.betweenness_centrality  AS betweenness_centrality,
       a.community_id            AS community_id,
       a.similarity_score        AS similarity_score,
       inbound_transfer_events,
       txn_count_30d,
       distinct_merchant_count_30d,
       distinct_counterparty_count
ORDER BY a.community_id, a.account_id
"""

_COMMUNITIES_CYPHER = """
UNWIND $community_ids AS cid
MATCH (a:Account) WHERE a.community_id = cid
WITH cid,
     count(a)                                                            AS member_count,
     avg(a.risk_score)                                                   AS avg_risk_score,
     max(a.risk_score)                                                   AS max_risk_score,
     avg(a.similarity_score)                                             AS avg_similarity_score,
     sum(CASE WHEN a.risk_score > $high_risk_gate THEN 1 ELSE 0 END)     AS high_risk_member_count,
     collect({account_id: a.account_id, similarity: a.similarity_score, risk: a.risk_score}) AS members
OPTIONAL MATCH (b:Account)-[t:TRANSACTED_WITH]->(merch:Merchant)
  WHERE b.community_id = cid
WITH cid, member_count, avg_risk_score, max_risk_score, avg_similarity_score,
     high_risk_member_count, members,
     collect(DISTINCT merch.category) AS categories,
     coalesce(sum(t.amount), 0)       AS total_volume_usd
// Within-community TRANSFERRED_TO degrees, used to classify topology.
OPTIONAL MATCH (m1:Account)-[r:TRANSFERRED_TO]-(m2:Account)
  WHERE m1.community_id = cid AND m2.community_id = cid
WITH cid, member_count, avg_risk_score, max_risk_score, avg_similarity_score,
     high_risk_member_count, members, categories, total_volume_usd,
     m1, count(r) AS deg
WITH cid, member_count, avg_risk_score, max_risk_score, avg_similarity_score,
     high_risk_member_count, members, categories, total_volume_usd,
     collect(deg) AS degs
RETURN cid                              AS community_id,
       member_count,
       avg_risk_score,
       max_risk_score,
       avg_similarity_score,
       high_risk_member_count,
       members,
       categories[0..3]                 AS anchor_merchant_categories,
       total_volume_usd,
       CASE WHEN size(degs) = 0 THEN 0.0
            ELSE reduce(s = 0.0, d IN degs | s + d) / size(degs) END   AS avg_deg,
       CASE WHEN size(degs) = 0 THEN 0
            ELSE reduce(mx = 0, d IN degs | CASE WHEN d > mx THEN d ELSE mx END) END AS max_deg
ORDER BY community_id
"""

_SIMILARITY_CYPHER = """
MATCH (a:Account)-[s:SIMILAR_TO]-(b:Account)
WHERE (a.community_id IN $community_ids OR b.community_id IN $community_ids)
  AND a.account_id < b.account_id
RETURN a.account_id        AS account_id_a,
       b.account_id        AS account_id_b,
       s.similarity_score  AS similarity_score,
       a.community_id IS NOT NULL
         AND b.community_id IS NOT NULL
         AND a.community_id = b.community_id  AS same_community
ORDER BY s.similarity_score DESC
LIMIT $row_cap
"""

_ACCOUNT_COMMUNITIES_CYPHER = """
MATCH (a:Account)
WHERE a.account_id IN $account_ids
  AND a.community_id IS NOT NULL
RETURN collect(DISTINCT a.community_id) AS community_ids
"""


# ---------------------------------------------------------------------------
# Schemas — column-for-column with enrichment-pipeline/sql/gold_schema.sql
# ---------------------------------------------------------------------------


_ACCOUNTS_SCHEMA: list[tuple[str, str]] = [
    ("account_id", "BIGINT"),
    ("account_hash", "STRING"),
    ("account_name", "STRING"),
    ("account_type", "STRING"),
    ("region", "STRING"),
    ("balance", "DOUBLE"),
    ("opened_date", "DATE"),
    ("holder_age", "INT"),
    ("risk_score", "DOUBLE"),
    ("betweenness_centrality", "DOUBLE"),
    ("community_id", "BIGINT"),
    ("similarity_score", "DOUBLE"),
    ("community_size", "BIGINT"),
    ("community_avg_risk_score", "DOUBLE"),
    ("community_risk_rank", "INT"),
    ("inbound_transfer_events", "BIGINT"),
    ("txn_count_30d", "BIGINT"),
    ("distinct_merchant_count_30d", "BIGINT"),
    ("distinct_counterparty_count", "BIGINT"),
    ("is_ring_community", "BOOLEAN"),
    ("fraud_risk_tier", "STRING"),
]

_COMMUNITIES_SCHEMA: list[tuple[str, str]] = [
    ("community_id", "BIGINT"),
    ("member_count", "BIGINT"),
    ("avg_risk_score", "DOUBLE"),
    ("max_risk_score", "DOUBLE"),
    ("avg_similarity_score", "DOUBLE"),
    ("high_risk_member_count", "BIGINT"),
    ("is_ring_candidate", "BOOLEAN"),
    ("top_account_id", "BIGINT"),
    ("total_volume_usd", "DOUBLE"),
    ("topology", "STRING"),
    ("anchor_merchant_categories", "ARRAY<STRING>"),
]

_SIMILARITY_SCHEMA: list[tuple[str, str]] = [
    ("account_id_a", "BIGINT"),
    ("account_id_b", "BIGINT"),
    ("similarity_score", "DOUBLE"),
    ("same_community", "BOOLEAN"),
]


# ---------------------------------------------------------------------------
# Python derivations
# ---------------------------------------------------------------------------


def _is_ring_candidate(member_count: int, avg_risk: float | None) -> bool:
    if avg_risk is None:
        return False
    return (
        _RING_MIN_MEMBERS <= member_count <= _RING_MAX_MEMBERS
        and avg_risk > _RING_AVG_RISK_MIN
    )


def _top_account_id(members: list[dict[str, Any]]) -> int | None:
    """Pick account with highest similarity_score, ties: risk DESC, id ASC."""
    if not members:
        return None
    sorted_members = sorted(
        members,
        key=lambda m: (
            -(float(m.get("similarity") or 0)),
            -(float(m.get("risk") or 0)),
            int(m.get("account_id") or 0),
        ),
    )
    return int(sorted_members[0].get("account_id") or 0)


def _decorate_communities(
    communities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute is_ring_candidate, top_account_id, topology; drop the
    `members`/`avg_deg`/`max_deg` working columns."""
    out: list[dict[str, Any]] = []
    for c in communities:
        member_count = int(c.get("member_count") or 0)
        avg_risk = (
            float(c["avg_risk_score"]) if c.get("avg_risk_score") is not None else None
        )
        members = c.get("members") or []
        avg_deg = float(c.get("avg_deg") or 0)
        max_deg = float(c.get("max_deg") or 0)
        out.append(
            {
                "community_id": int(c.get("community_id") or 0),
                "member_count": member_count,
                "avg_risk_score": avg_risk,
                "max_risk_score": (
                    float(c["max_risk_score"])
                    if c.get("max_risk_score") is not None
                    else None
                ),
                "avg_similarity_score": (
                    float(c["avg_similarity_score"])
                    if c.get("avg_similarity_score") is not None
                    else None
                ),
                "high_risk_member_count": int(c.get("high_risk_member_count") or 0),
                "is_ring_candidate": _is_ring_candidate(member_count, avg_risk),
                "top_account_id": _top_account_id(members),
                "total_volume_usd": float(c.get("total_volume_usd") or 0),
                "topology": _classify_topology(avg_deg, max_deg),
                "anchor_merchant_categories": c.get("anchor_merchant_categories") or [],
            }
        )
    return out


def _decorate_accounts(
    accounts: list[dict[str, Any]],
    communities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add community_size, community_avg_risk_score, community_risk_rank,
    is_ring_community, fraud_risk_tier per gold_schema.sql."""
    community_lookup = {c["community_id"]: c for c in communities}

    # community_risk_rank: within each community, rank by similarity_score DESC,
    # then risk_score DESC, then account_id ASC.
    by_community: dict[int, list[dict[str, Any]]] = {}
    for a in accounts:
        cid = a.get("community_id")
        if cid is None:
            continue
        by_community.setdefault(int(cid), []).append(a)

    rank_lookup: dict[tuple[int, int], int] = {}
    for cid, members in by_community.items():
        ordered = sorted(
            members,
            key=lambda m: (
                -(float(m.get("similarity_score") or 0)),
                -(float(m.get("risk_score") or 0)),
                int(m.get("account_id") or 0),
            ),
        )
        for i, m in enumerate(ordered, start=1):
            rank_lookup[(cid, int(m.get("account_id") or 0))] = i

    out: list[dict[str, Any]] = []
    for a in accounts:
        cid_raw = a.get("community_id")
        cid = int(cid_raw) if cid_raw is not None else None
        comm = community_lookup.get(cid, {}) if cid is not None else {}
        is_ring = bool(comm.get("is_ring_candidate", False))
        out.append(
            {
                "account_id": int(a.get("account_id") or 0),
                "account_hash": a.get("account_hash"),
                "account_name": a.get("account_name"),
                "account_type": a.get("account_type"),
                "region": a.get("region"),
                "balance": (
                    float(a["balance"]) if a.get("balance") is not None else None
                ),
                "opened_date": a.get("opened_date"),
                "holder_age": (
                    int(a["holder_age"]) if a.get("holder_age") is not None else None
                ),
                "risk_score": (
                    float(a["risk_score"]) if a.get("risk_score") is not None else None
                ),
                "betweenness_centrality": (
                    float(a["betweenness_centrality"])
                    if a.get("betweenness_centrality") is not None
                    else None
                ),
                "community_id": cid,
                "similarity_score": (
                    float(a["similarity_score"])
                    if a.get("similarity_score") is not None
                    else None
                ),
                "community_size": (
                    int(comm.get("member_count") or 0) if comm else None
                ),
                "community_avg_risk_score": comm.get("avg_risk_score") if comm else None,
                "community_risk_rank": (
                    rank_lookup.get((cid, int(a.get("account_id") or 0)))
                    if cid is not None
                    else None
                ),
                "inbound_transfer_events": int(a.get("inbound_transfer_events") or 0),
                "txn_count_30d": int(a.get("txn_count_30d") or 0),
                "distinct_merchant_count_30d": int(
                    a.get("distinct_merchant_count_30d") or 0
                ),
                "distinct_counterparty_count": int(
                    a.get("distinct_counterparty_count") or 0
                ),
                "is_ring_community": is_ring,
                "fraud_risk_tier": "high" if is_ring else "low",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def load_rings(
    ws: WorkspaceClient,
    config: AppConfig,
    driver: Driver,
    ring_ids: list[str],
    risk_account_ids: list[str] | None = None,
    central_account_ids: list[str] | None = None,
) -> LoadOut:
    target_tables = [
        f"{config.catalog}.{config.schema_}.gold_accounts",
        f"{config.catalog}.{config.schema_}.gold_fraud_ring_communities",
        f"{config.catalog}.{config.schema_}.gold_account_similarity_pairs",
    ]
    steps = [LoadStep(label=label, status="done") for label in _step_labels()]
    row_counts: dict[str, int] = {
        "gold_accounts": 0,
        "gold_fraud_ring_communities": 0,
        "gold_account_similarity_pairs": 0,
    }

    community_ids = _coerce_ring_ids(ring_ids)
    account_ids = _coerce_account_ids(
        [*(risk_account_ids or []), *(central_account_ids or [])]
    )
    if not community_ids and not account_ids:
        return LoadOut(
            target_tables=target_tables,
            steps=[LoadStep(label=label, status="todo") for label in _step_labels()],
            row_counts=row_counts,
            quality_checks=[
                QualityCheck(name="At least one valid signal id provided", passed=False),
            ],
        )

    with driver.session() as session:
        if account_ids:
            resolved = session.run(
                _ACCOUNT_COMMUNITIES_CYPHER,
                account_ids=account_ids,
            ).data()
            resolved_ids = (
                resolved[0].get("community_ids", []) if resolved else []
            )
            community_ids.extend(
                int(cid) for cid in resolved_ids if cid is not None
            )
            community_ids = sorted(set(community_ids))

        if not community_ids:
            return LoadOut(
                target_tables=target_tables,
                steps=[
                    LoadStep(label=label, status="todo")
                    for label in _step_labels()
                ],
                row_counts=row_counts,
                quality_checks=[
                    QualityCheck(
                        name="At least one selected signal resolved to a community",
                        passed=False,
                    ),
                ],
            )

        accounts_raw = _normalize_accounts(
            session.run(_ACCOUNTS_CYPHER, community_ids=community_ids).data()
        )
        communities_raw = session.run(
            _COMMUNITIES_CYPHER,
            community_ids=community_ids,
            high_risk_gate=_HIGH_RISK_MEMBER_GATE,
        ).data()
        similarity = session.run(
            _SIMILARITY_CYPHER,
            community_ids=community_ids,
            row_cap=_SIMILARITY_ROW_CAP,
        ).data()

    communities = _decorate_communities(communities_raw)
    accounts = _decorate_accounts(accounts_raw, communities)

    row_counts["gold_accounts"] = _write_table(
        ws, config, "gold_accounts", _ACCOUNTS_SCHEMA, accounts
    )
    row_counts["gold_fraud_ring_communities"] = _write_table(
        ws, config, "gold_fraud_ring_communities", _COMMUNITIES_SCHEMA, communities
    )
    row_counts["gold_account_similarity_pairs"] = _write_table(
        ws,
        config,
        "gold_account_similarity_pairs",
        _SIMILARITY_SCHEMA,
        similarity,
    )

    quality_checks = [
        QualityCheck(
            name="Accounts loaded",
            passed=row_counts["gold_accounts"] > 0,
        ),
        QualityCheck(
            name="Communities loaded",
            passed=row_counts["gold_fraud_ring_communities"] > 0,
        ),
        QualityCheck(
            name="All accounts have a community_id",
            passed=all(a.get("community_id") is not None for a in accounts),
        ),
        QualityCheck(
            name="All accounts have a risk_score",
            passed=all(a.get("risk_score") is not None for a in accounts),
        ),
        QualityCheck(
            name="Member counts match aggregate",
            passed=sum(int(c.get("member_count") or 0) for c in communities)
            == len(accounts),
        ),
        QualityCheck(
            name="All selected communities returned",
            passed={
                int(c["community_id"])
                for c in communities
                if c.get("community_id") is not None
            }
            == set(community_ids),
        ),
    ]

    return LoadOut(
        target_tables=target_tables,
        steps=steps,
        row_counts=row_counts,
        quality_checks=quality_checks,
    )

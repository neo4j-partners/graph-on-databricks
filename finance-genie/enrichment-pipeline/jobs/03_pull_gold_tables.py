"""Pull GDS features from Neo4j and write enriched gold tables to Delta Lake.

This agent module is the source of truth for the gold tables the after-GDS
Genie Space reads. `workshop/03_pull_gold_tables.ipynb` will be synced to
match in phase 11e.

Writes three tables into `graph-on-databricks.graph-enriched-schema`:
  gold_accounts                   account metadata + GDS features + community
                                  aggregates + fraud_risk_tier (20 cols)
  gold_account_similarity_pairs   pair-level similarity + same_community flag
  gold_fraud_ring_communities     per-community summary for ring-level queries

Schema contract: gold_schema.sql (uploaded alongside this script) defines all
three tables with Unity Catalog column-level comments. This script applies that
schema first, then writes data with overwriteSchema=false so column comments
survive every pipeline run. Any schema change must be reflected in both files.

Usage (from finance-genie/enrichment-pipeline/ with .env in place):
    python -m cli upload --all
    python -m cli submit 03_pull_gold_tables.py
    python -m cli logs

Cluster prerequisite: the Neo4j Spark Connector JAR must be installed as a
cluster library before submitting this job:
    org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3

Run `validation/validate_cluster.py` locally before submitting to confirm.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _cluster_bootstrap import inject_params, resolve_here

# --------------------------------------------------------------------------- #
# 1. Bootstrap: inject .env vars from KEY=VALUE argv, resolve script directory #
# --------------------------------------------------------------------------- #
inject_params()
_HERE = resolve_here()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pyspark.sql import SparkSession, Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from _neo4j_secrets import load_neo4j_opts  # noqa: E402
from _gold_constants import (  # noqa: E402
    COMMUNITY_AVG_RISK_MIN,
    RING_SIZE_HIGH,
    RING_SIZE_LOW,
    TIER_HIGH,
    TIER_LOW,
)


# --------------------------------------------------------------------------- #
# 2. Schema helper                                                             #
# --------------------------------------------------------------------------- #

def _apply_schema(spark: "SparkSession", catalog: str, schema: str) -> None:
    """Apply gold_schema.sql — creates all three gold tables with column comments.

    gold_schema.sql defines the table structure before data is written so that
    Unity Catalog column descriptions survive every pipeline run. Column comments
    live in the CREATE OR REPLACE TABLE DDL and are not wiped by saveAsTable().
    """
    sql_file = _HERE / "gold_schema.sql"
    text = sql_file.read_text(encoding="utf-8")
    text = text.replace("${catalog}", catalog).replace("${schema}", schema)
    for raw in text.split(";"):
        lines = [ln for ln in raw.split("\n") if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            spark.sql(stmt)
    print("Schema applied: gold_accounts, gold_account_similarity_pairs, gold_fraud_ring_communities")


# --------------------------------------------------------------------------- #
# 3. Main                                                                      #
# --------------------------------------------------------------------------- #

def main() -> None:
    # ----------------------------------------------------------------------- #
    # Config + Neo4j credentials                                               #
    # ----------------------------------------------------------------------- #
    # Silver source tables are read from SILVER_CATALOG; gold tables are
    # created/written under GOLD_CATALOG. Each falls back to the legacy single
    # CATALOG when its split-catalog override is unset.
    CATALOG = os.environ.get("SILVER_CATALOG") or os.environ["CATALOG"]
    GOLD_CATALOG = os.environ.get("GOLD_CATALOG") or os.environ["CATALOG"]
    SCHEMA = os.environ["SCHEMA"]
    SECRET_SCOPE = os.environ["NEO4J_SECRET_SCOPE"]

    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_OPTS = load_neo4j_opts(SECRET_SCOPE)

    # ----------------------------------------------------------------------- #
    # Spark session                                                             #
    # ----------------------------------------------------------------------- #
    spark = SparkSession.builder.getOrCreate()

    _apply_schema(spark, GOLD_CATALOG, SCHEMA)

    # ----------------------------------------------------------------------- #
    # Read GDS features from Neo4j Account nodes                               #
    #    Cache so the DataFrame is only read from Neo4j once — it is reused in #
    #    the gold_accounts join and would otherwise trigger a second full read. #
    # ----------------------------------------------------------------------- #
    graph_features_df = (
        spark.read
        .format("org.neo4j.spark.DataSource")
        .options(**NEO4J_OPTS)
        .option("labels", "Account")
        .load()
        .select(
            F.col("account_id").cast("long"),
            F.col("risk_score").cast("double"),
            F.col("betweenness_centrality").cast("double"),
            F.col("community_id").cast("long"),
            F.col("similarity_score").cast("double"),
        )
        .cache()
    )
    print(f"Read {graph_features_df.count():,} Account nodes with GDS features")

    # ----------------------------------------------------------------------- #
    # Build gold_accounts with community aggregates + fraud_risk_tier          #
    #                                                                           #
    # Targeted fillna on inbound_transfer_events only — leaving community_id,  #
    # risk_score, and similarity_score null for unscored accounts is            #
    # intentional: a blanket fillna(0) would bucket every unscored account     #
    # into a synthetic community_id=0 and poison the window aggregates.        #
    #                                                                           #
    # gold_df is cached and reused in later sections; no write-then-read cycle. #
    # ----------------------------------------------------------------------- #
    GOLD_ACCOUNTS_TABLE = f"`{GOLD_CATALOG}`.`{SCHEMA}`.gold_accounts"

    account_links_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.account_links").cache()
    transactions_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.transactions").cache()

    inbound_counts = (
        account_links_df
        .groupBy(F.col("dst_account_id").alias("account_id"))
        .agg(F.count("*").alias("inbound_transfer_events"))
    )

    max_txn_timestamp = transactions_df.agg(
        F.max("txn_timestamp").alias("max_txn_timestamp")
    ).collect()[0]["max_txn_timestamp"]
    recent_transactions = (
        transactions_df
        .filter(
            F.col("txn_timestamp")
            >= F.lit(max_txn_timestamp).cast("timestamp") - F.expr("INTERVAL 30 DAYS")
        )
    )
    transaction_metrics = (
        recent_transactions
        .groupBy("account_id")
        .agg(
            F.count("*").cast("long").alias("txn_count_30d"),
            F.countDistinct("merchant_id").cast("long").alias(
                "distinct_merchant_count_30d"
            ),
        )
    )

    counterparty_counts = (
        account_links_df
        .select(
            F.col("src_account_id").alias("account_id"),
            F.col("dst_account_id").alias("counterparty_account_id"),
        )
        .unionByName(
            account_links_df.select(
                F.col("dst_account_id").alias("account_id"),
                F.col("src_account_id").alias("counterparty_account_id"),
            )
        )
        .groupBy("account_id")
        .agg(
            F.countDistinct("counterparty_account_id")
            .cast("long")
            .alias("distinct_counterparty_count")
        )
    )

    # Unscored accounts land in a single null-community partition; their
    # community_size/avg/rank aggregate together, and they fall to
    # fraud_risk_tier='low' via the is_ring_community guard below.
    w_community = Window.partitionBy("community_id")
    # row_number (not rank) with an account_id tiebreak so community_risk_rank=1
    # identifies exactly one account per community — same row that
    # gold_fraud_ring_communities.top_account_id points at.
    w_community_rank = Window.partitionBy("community_id").orderBy(
        F.desc("similarity_score"), F.desc("risk_score"), F.asc("account_id")
    )

    gold_df = (
        spark.table(f"`{CATALOG}`.`{SCHEMA}`.accounts")
        .join(graph_features_df, "account_id", "left")
        .join(inbound_counts, "account_id", "left")
        .join(transaction_metrics, "account_id", "left")
        .join(counterparty_counts, "account_id", "left")
        .fillna(
            {
                "inbound_transfer_events": 0,
                "txn_count_30d": 0,
                "distinct_merchant_count_30d": 0,
                "distinct_counterparty_count": 0,
            }
        )
        .withColumn("community_size", F.count("*").over(w_community))
        .withColumn("community_avg_risk_score", F.avg("risk_score").over(w_community))
        .withColumn("community_risk_rank", F.row_number().over(w_community_rank))
        .withColumn(
            "is_ring_community",
            (F.col("community_size").between(RING_SIZE_LOW, RING_SIZE_HIGH))
            & (F.col("community_avg_risk_score") > COMMUNITY_AVG_RISK_MIN),
        )
        .withColumn(
            "fraud_risk_tier",
            F.when(F.col("is_ring_community"), TIER_HIGH).otherwise(TIER_LOW),
        )
        .select(
            "account_id",
            "account_hash",
            "account_type",
            "region",
            "balance",
            "opened_date",
            "holder_age",
            "risk_score",
            "betweenness_centrality",
            "community_id",
            "similarity_score",
            "community_size",
            "community_avg_risk_score",
            "community_risk_rank",
            "inbound_transfer_events",
            "txn_count_30d",
            "distinct_merchant_count_30d",
            "distinct_counterparty_count",
            "is_ring_community",
            "fraud_risk_tier",
        )
        .cache()
    )

    n_gold = gold_df.count()  # materializes the cache; subsequent reads are free.

    (
        gold_df
        .write.format("delta").mode("overwrite")
        .option("overwriteSchema", "false")
        .saveAsTable(GOLD_ACCOUNTS_TABLE)
    )
    print(f"Written {GOLD_ACCOUNTS_TABLE} ({n_gold:,} rows, 20 columns)")

    # ----------------------------------------------------------------------- #
    # Build gold_account_similarity_pairs with same_community flag             #
    #                                                                           #
    # Both sides are guarded non-null before equality so pairs involving an    #
    # unscored account come out as false, not null.                            #
    # ----------------------------------------------------------------------- #
    GOLD_PAIRS_TABLE = f"`{GOLD_CATALOG}`.`{SCHEMA}`.gold_account_similarity_pairs"

    community_lookup = gold_df.select("account_id", "community_id")

    similarity_pairs_df = (
        spark.read
        .format("org.neo4j.spark.DataSource")
        .options(**NEO4J_OPTS)
        .option("relationship", "SIMILAR_TO")
        .option("relationship.source.labels", ":Account")
        .option("relationship.target.labels", ":Account")
        .load()
        .select(
            F.least(
                F.col("`source.account_id`"), F.col("`target.account_id`")
            ).cast("long").alias("account_id_a"),
            F.greatest(
                F.col("`source.account_id`"), F.col("`target.account_id`")
            ).cast("long").alias("account_id_b"),
            F.col("`rel.similarity_score`").cast("double").alias("similarity_score"),
        )
        .dropDuplicates(["account_id_a", "account_id_b"])
    )

    similarity_pairs_df = (
        similarity_pairs_df
        .join(
            community_lookup.withColumnRenamed("account_id", "account_id_a")
                            .withColumnRenamed("community_id", "community_id_a"),
            "account_id_a",
            "left",
        )
        .join(
            community_lookup.withColumnRenamed("account_id", "account_id_b")
                            .withColumnRenamed("community_id", "community_id_b"),
            "account_id_b",
            "left",
        )
        .withColumn(
            "same_community",
            F.col("community_id_a").isNotNull()
            & F.col("community_id_b").isNotNull()
            & (F.col("community_id_a") == F.col("community_id_b")),
        )
        .drop("community_id_a", "community_id_b")
    )

    similarity_pairs_df = similarity_pairs_df.cache()
    n_pairs = similarity_pairs_df.count()

    (
        similarity_pairs_df
        .write.format("delta").mode("overwrite")
        .option("overwriteSchema", "false")
        .saveAsTable(GOLD_PAIRS_TABLE)
    )
    print(f"Written {GOLD_PAIRS_TABLE} ({n_pairs:,} rows)")
    similarity_pairs_df.unpersist()

    # ----------------------------------------------------------------------- #
    # Build gold_fraud_ring_communities — one row per Louvain community        #
    #                                                                           #
    # ROW_NUMBER (not RANK) with a deterministic tiebreak on account_id so    #
    # ties cannot produce duplicate top_account_id rows.                       #
    #                                                                           #
    # top_account_id sorts by similarity_score DESC before risk_score DESC.    #
    # Fraud ring members share anchor merchants → high NodeSimilarity score    #
    # (~0.20 avg). "Whale" accounts have high PageRank (risk_score) but low    #
    # similarity (~0.10 avg) because their merchant visits are not correlated  #
    # with any specific community. Sorting on risk_score alone caused a whale  #
    # that landed in the same Louvain community as ring 3 to be selected as    #
    # top_account_id instead of an actual ring member.                         #
    # ----------------------------------------------------------------------- #
    GOLD_RING_COMMUNITIES_TABLE = f"`{GOLD_CATALOG}`.`{SCHEMA}`.gold_fraud_ring_communities"

    ring_aggregates = (
        gold_df
        .filter(F.col("community_id").isNotNull())
        .groupBy("community_id")
        .agg(
            F.count("*").alias("member_count"),
            F.round(F.avg("risk_score"), 6).alias("avg_risk_score"),
            F.round(F.max("risk_score"), 6).alias("max_risk_score"),
            F.round(F.avg("similarity_score"), 5).alias("avg_similarity_score"),
            F.sum(F.when(F.col("risk_score") > 1.0, 1).otherwise(0))
                .alias("high_risk_member_count"),
        )
        .withColumn(
            "is_ring_candidate",
            F.col("member_count").between(RING_SIZE_LOW, RING_SIZE_HIGH)
            & (F.col("avg_risk_score") > COMMUNITY_AVG_RISK_MIN),
        )
    )

    w_top = Window.partitionBy("community_id").orderBy(
        F.desc("similarity_score"), F.desc("risk_score"), F.asc("account_id")
    )

    top_accounts = (
        gold_df
        .filter(F.col("community_id").isNotNull())
        .select("community_id", "account_id", "risk_score", "similarity_score")
        .withColumn("_row", F.row_number().over(w_top))
        .filter(F.col("_row") == 1)
        .select(
            F.col("community_id"),
            F.col("account_id").alias("top_account_id"),
        )
    )

    community_members = (
        gold_df
        .filter(F.col("community_id").isNotNull())
        .select("community_id", "account_id")
    )

    within_community_links = (
        account_links_df
        .join(
            community_lookup
            .withColumnRenamed("account_id", "src_account_id")
            .withColumnRenamed("community_id", "src_community_id"),
            "src_account_id",
            "left",
        )
        .join(
            community_lookup
            .withColumnRenamed("account_id", "dst_account_id")
            .withColumnRenamed("community_id", "dst_community_id"),
            "dst_account_id",
            "left",
        )
        .filter(
            F.col("src_community_id").isNotNull()
            & F.col("dst_community_id").isNotNull()
            & (F.col("src_community_id") == F.col("dst_community_id"))
        )
        .select(
            F.col("src_community_id").alias("community_id"),
            "src_account_id",
            "dst_account_id",
            "amount",
        )
        .cache()
    )

    community_volume = (
        within_community_links
        .groupBy("community_id")
        .agg(F.round(F.sum("amount"), 2).alias("total_volume_usd"))
    )

    undirected_edges = (
        within_community_links
        .select(
            "community_id",
            F.least("src_account_id", "dst_account_id").alias("account_id_a"),
            F.greatest("src_account_id", "dst_account_id").alias("account_id_b"),
        )
        .filter(F.col("account_id_a") != F.col("account_id_b"))
        .dropDuplicates(["community_id", "account_id_a", "account_id_b"])
        .cache()
    )

    edge_counts = (
        undirected_edges
        .groupBy("community_id")
        .agg(F.count("*").cast("double").alias("edge_count"))
    )
    degree_counts = (
        undirected_edges
        .select("community_id", F.col("account_id_a").alias("account_id"))
        .unionByName(
            undirected_edges.select(
                "community_id", F.col("account_id_b").alias("account_id")
            )
        )
        .groupBy("community_id", "account_id")
        .agg(F.count("*").cast("double").alias("degree"))
    )
    degree_stats = (
        community_members
        .join(degree_counts, ["community_id", "account_id"], "left")
        .fillna({"degree": 0.0})
        .groupBy("community_id")
        .agg(
            F.max("degree").alias("max_degree"),
            F.avg("degree").alias("avg_degree"),
        )
    )
    topology = (
        ring_aggregates
        .select("community_id", "member_count")
        .join(degree_stats, "community_id", "left")
        .join(edge_counts, "community_id", "left")
        .fillna({"max_degree": 0.0, "avg_degree": 0.0, "edge_count": 0.0})
        .withColumn(
            "degree_skew",
            F.when(F.col("avg_degree") > 0, F.col("max_degree") / F.col("avg_degree"))
            .otherwise(F.lit(0.0)),
        )
        .withColumn(
            "max_possible_edges",
            (F.col("member_count") * (F.col("member_count") - 1) / F.lit(2.0)),
        )
        .withColumn(
            "edge_density",
            F.when(
                F.col("max_possible_edges") > 0,
                F.col("edge_count") / F.col("max_possible_edges"),
            ).otherwise(F.lit(0.0)),
        )
        .withColumn(
            "topology",
            F.when(F.col("degree_skew") > 3.0, F.lit("star"))
            .when(F.col("edge_density") > 0.15, F.lit("mesh"))
            .otherwise(F.lit("chain")),
        )
        .select("community_id", "topology")
    )

    # Build the same ring-to-community map that is emitted as an artifact, then
    # use it to attach ground-truth anchor categories to every mapped community.
    GROUND_TRUTH_PATH = os.environ.get("GROUND_TRUTH_PATH")
    ring_community_map: dict[str, list[int]] = {}
    anchor_categories = None
    if GROUND_TRUTH_PATH:
        with open(GROUND_TRUTH_PATH) as _f:
            _gt = json.load(_f)

        _ring_acct_rows = [
            (str(ring["ring_id"]), int(acct_id))
            for ring in _gt["rings"]
            for acct_id in ring["account_ids"]
        ]
        _ring_acct_df = spark.createDataFrame(_ring_acct_rows, ["ring_id", "account_id"])

        _ring_community_df = (
            _ring_acct_df
            .join(gold_df.select("account_id", "community_id"), "account_id", "left")
            .filter(F.col("community_id").isNotNull())
            .select("ring_id", "community_id")
            .distinct()
        )

        for _row in _ring_community_df.collect():
            ring_community_map.setdefault(_row["ring_id"], []).append(
                int(_row["community_id"])
            )
        ring_community_map = {k: sorted(v) for k, v in ring_community_map.items()}

        _ring_categories = {
            str(ring["ring_id"]): [
                str(merchant["category"]) for merchant in ring["anchor_merchants"]
            ]
            for ring in _gt["rings"]
        }
        _community_to_categories: dict[int, list[str]] = {}
        for ring_id in sorted(ring_community_map, key=int):
            if ring_id not in _ring_categories:
                continue
            for community_id in ring_community_map[ring_id]:
                _community_to_categories.setdefault(
                    int(community_id), _ring_categories[ring_id]
                )
        _anchor_rows = sorted(_community_to_categories.items())
        if _anchor_rows:
            anchor_categories = (
                spark.createDataFrame(
                    _anchor_rows,
                    "community_id long, anchor_merchant_categories array<string>",
                )
                .dropDuplicates(["community_id"])
            )

    ring_communities_df = (
        ring_aggregates
        .join(top_accounts, "community_id", "left")
        .join(community_volume, "community_id", "left")
        .join(topology, "community_id", "left")
        .fillna({"total_volume_usd": 0.0, "topology": "chain"})
    )
    if anchor_categories is not None:
        ring_communities_df = ring_communities_df.join(
            anchor_categories, "community_id", "left"
        )
    else:
        ring_communities_df = ring_communities_df.withColumn(
            "anchor_merchant_categories", F.lit(None).cast("array<string>")
        )
    ring_communities_df = ring_communities_df.cache()

    ring_counts = ring_communities_df.agg(
        F.count("*").alias("total"),
        F.sum(F.col("is_ring_candidate").cast("int")).alias("candidates"),
    ).collect()[0]
    n_ring = int(ring_counts["total"])
    n_ring_candidates = int(ring_counts["candidates"] or 0)

    (
        ring_communities_df
        .write.format("delta").mode("overwrite")
        .option("overwriteSchema", "false")
        .saveAsTable(GOLD_RING_COMMUNITIES_TABLE)
    )
    print(
        f"Written {GOLD_RING_COMMUNITIES_TABLE} "
        f"({n_ring:,} rows, {n_ring_candidates} ring candidates)"
    )

    # ----------------------------------------------------------------------- #
    # Build ring_community_map.json — written to the same volume directory as #
    # ground_truth.json. Maps each synthetic ring_id to the set of Louvain    #
    # community_ids that contain at least one of its members. Generated fresh  #
    # on every gold table rebuild so it stays in sync with community_id        #
    # assignments, which change whenever the GDS graph is re-projected.        #
    # ----------------------------------------------------------------------- #
    if GROUND_TRUTH_PATH:
        _map_path = str(Path(GROUND_TRUTH_PATH).parent / "ring_community_map.json")
        with open(_map_path, "w") as _f:
            json.dump(
                {
                    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ring_community_map": ring_community_map,
                },
                _f,
                indent=2,
            )
        print(f"Written {_map_path} ({len(ring_community_map)} rings)")

    undirected_edges.unpersist()
    within_community_links.unpersist()
    ring_communities_df.unpersist()
    gold_df.unpersist()
    transactions_df.unpersist()
    account_links_df.unpersist()
    graph_features_df.unpersist()

    print("Done.")


if __name__ == "__main__":
    main()

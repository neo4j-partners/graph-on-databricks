"""Push Delta Lake tables into Neo4j as a property graph.

Translated from finance-genie/workshop/01_neo4j_ingest.ipynb.
Runs as a Databricks Python task (no notebook kernel required).

Usage (from finance-genie/enrichment-pipeline/ with .env in place):
    python -m cli upload --all
    python -m cli submit 02_neo4j_ingest.py
    python -m cli logs

Cluster prerequisites (install as cluster libraries before submitting):
    - org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3  (JAR)
    - graphdatascience  (PyPI)
"""

from __future__ import annotations

import os
import sys

from _cluster_bootstrap import inject_params, resolve_here

# --------------------------------------------------------------------------- #
# 1. Bootstrap: inject .env vars from KEY=VALUE argv, resolve script directory #
# --------------------------------------------------------------------------- #
inject_params()
_HERE = resolve_here()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from graphdatascience import GraphDataScience  # noqa: E402
from pyspark.sql import SparkSession  # noqa: E402

from _neo4j_secrets import load_neo4j_opts  # noqa: E402

# --------------------------------------------------------------------------- #
# 2. Config + Neo4j credentials                                                #
# --------------------------------------------------------------------------- #
# Reads the five raw (silver) business tables. Silver catalog falls back to
# the legacy single CATALOG when SILVER_CATALOG is unset.
CATALOG = os.environ.get("SILVER_CATALOG") or os.environ["CATALOG"]
SCHEMA = os.environ["SCHEMA"]
SECRET_SCOPE = os.environ["NEO4J_SECRET_SCOPE"]

NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_OPTS = load_neo4j_opts(SECRET_SCOPE)

# --------------------------------------------------------------------------- #
# 3. Spark session + catalog                                                   #
# --------------------------------------------------------------------------- #
spark = SparkSession.builder.getOrCreate()
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

# --------------------------------------------------------------------------- #
# 4. Clear Neo4j (idempotent re-runs)                                          #
# --------------------------------------------------------------------------- #
gds = GraphDataScience(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
# Batch the wipe so it fits in memory on small Aura tiers. A single
# unbatched DETACH DELETE of ~32k nodes + ~470k rels can trip
# TransactionOutOfMemoryError. CALL ... IN TRANSACTIONS is auto-commit only,
# which is what gds.run_cypher's session.run provides.
gds.run_cypher(
    "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
)
print("Neo4j cleared.")

# --------------------------------------------------------------------------- #
# 5. Write Account nodes                                                        #
# --------------------------------------------------------------------------- #
accounts_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.accounts")

(
    accounts_df.write.format("org.neo4j.spark.DataSource")
    .mode("Append")
    .options(**NEO4J_OPTS)
    .option("labels", ":Account")
    .option("node.keys", "account_id")
    .save()
)
print("Account nodes written.")

# --------------------------------------------------------------------------- #
# 6. Write Merchant nodes                                                       #
# --------------------------------------------------------------------------- #
merchants_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.merchants")

(
    merchants_df.write.format("org.neo4j.spark.DataSource")
    .mode("Append")
    .options(**NEO4J_OPTS)
    .option("labels", ":Merchant")
    .option("node.keys", "merchant_id")
    .save()
)
print("Merchant nodes written.")

# --------------------------------------------------------------------------- #
# 7. Create indexes before relationship writes                                  #
#    Uniqueness constraints also create an index; without these the Spark      #
#    Connector does a full node scan per relationship row.                     #
# --------------------------------------------------------------------------- #
gds.run_cypher("""
    CREATE CONSTRAINT account_id_unique IF NOT EXISTS
    FOR (a:Account) REQUIRE a.account_id IS UNIQUE
""")
gds.run_cypher("""
    CREATE CONSTRAINT merchant_id_unique IF NOT EXISTS
    FOR (m:Merchant) REQUIRE m.merchant_id IS UNIQUE
""")
print("Indexes ready.")

# --------------------------------------------------------------------------- #
# 8. Write TRANSACTED_WITH relationships (Account -> Merchant)                  #
# --------------------------------------------------------------------------- #
txn_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.transactions")

(
    txn_df.write.format("org.neo4j.spark.DataSource")
    .mode("Overwrite")
    .options(**NEO4J_OPTS)
    .option("relationship", "TRANSACTED_WITH")
    .option("relationship.save.strategy", "keys")
    .option("relationship.source.labels", ":Account")
    .option("relationship.source.node.keys", "account_id:account_id")
    .option("relationship.target.labels", ":Merchant")
    .option("relationship.target.node.keys", "merchant_id:merchant_id")
    .save()
)
print("TRANSACTED_WITH relationships written.")

# --------------------------------------------------------------------------- #
# 9. Write TRANSFERRED_TO relationships (Account -> Account)                   #
# --------------------------------------------------------------------------- #
p2p_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.account_links")

(
    p2p_df.write.format("org.neo4j.spark.DataSource")
    .mode("Overwrite")
    .options(**NEO4J_OPTS)
    .option("relationship", "TRANSFERRED_TO")
    .option("relationship.save.strategy", "keys")
    .option("relationship.source.labels", ":Account")
    .option("relationship.source.node.keys", "src_account_id:account_id")
    .option("relationship.target.labels", ":Account")
    .option("relationship.target.node.keys", "dst_account_id:account_id")
    .save()
)
print("TRANSFERRED_TO relationships written.")

# --------------------------------------------------------------------------- #
# 10. Verify — quick counts                                                    #
# --------------------------------------------------------------------------- #
counts = gds.run_cypher("""
    MATCH (a:Account) WITH count(a) AS accounts
    MATCH (m:Merchant) WITH accounts, count(m) AS merchants
    MATCH ()-[t:TRANSACTED_WITH]->() WITH accounts, merchants, count(t) AS txns
    MATCH ()-[p:TRANSFERRED_TO]->() WITH accounts, merchants, txns, count(p) AS p2p
    RETURN accounts, merchants, txns, p2p
""")
print(counts.to_string(index=False))
print("Done.")

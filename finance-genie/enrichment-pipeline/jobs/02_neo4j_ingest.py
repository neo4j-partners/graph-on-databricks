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
# unbatched DETACH DELETE of ~107k nodes + ~550k rels (accounts, merchants,
# and the customer identity layer) can trip TransactionOutOfMemoryError.
# CALL ... IN TRANSACTIONS is auto-commit only, which is what
# gds.run_cypher's session.run provides.
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
# 7. Write Customer nodes                                                       #
#    Phone and address are deliberately left off the node: they become          #
#    :Phone / :Address nodes so shared identifiers are graph structure.        #
# --------------------------------------------------------------------------- #
customers_df = spark.table(f"`{CATALOG}`.`{SCHEMA}`.customers")

(
    customers_df.selectExpr("customer_id", "customer_name AS name", "email")
    .write.format("org.neo4j.spark.DataSource")
    .mode("Append")
    .options(**NEO4J_OPTS)
    .option("labels", ":Customer")
    .option("node.keys", "customer_id")
    .save()
)
print("Customer nodes written.")

# --------------------------------------------------------------------------- #
# 8. Create indexes before relationship writes                                  #
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
gds.run_cypher("""
    CREATE CONSTRAINT customer_id_unique IF NOT EXISTS
    FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE
""")
gds.run_cypher("""
    CREATE CONSTRAINT phone_number_unique IF NOT EXISTS
    FOR (p:Phone) REQUIRE p.number IS UNIQUE
""")
gds.run_cypher("""
    CREATE CONSTRAINT address_address_unique IF NOT EXISTS
    FOR (a:Address) REQUIRE a.address IS UNIQUE
""")
# Knowledge-layer keys. The Policy/BusinessTerm/BusinessRule/DataSource nodes
# themselves are created by validation/run_gds.py so classification and
# provenance are written together; their uniqueness constraints live here
# alongside the other node keys.
gds.run_cypher("""
    CREATE CONSTRAINT policy_id_unique IF NOT EXISTS
    FOR (p:Policy) REQUIRE p.policy_id IS UNIQUE
""")
gds.run_cypher("""
    CREATE CONSTRAINT business_term_name_unique IF NOT EXISTS
    FOR (t:BusinessTerm) REQUIRE t.name IS UNIQUE
""")
gds.run_cypher("""
    CREATE CONSTRAINT business_rule_id_unique IF NOT EXISTS
    FOR (r:BusinessRule) REQUIRE r.rule_id IS UNIQUE
""")
gds.run_cypher("""
    CREATE CONSTRAINT data_source_name_unique IF NOT EXISTS
    FOR (d:DataSource) REQUIRE d.name IS UNIQUE
""")
print("Indexes ready.")

# --------------------------------------------------------------------------- #
# 9. Write TRANSACTED_WITH relationships (Account -> Merchant)                  #
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
# 10. Write TRANSFERRED_TO relationships (Account -> Account)                   #
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
# 11. Write OWNS relationships (Customer -> Account)                           #
# --------------------------------------------------------------------------- #
(
    customers_df.select("customer_id", "account_id")
    .write.format("org.neo4j.spark.DataSource")
    .mode("Overwrite")
    .options(**NEO4J_OPTS)
    .option("relationship", "OWNS")
    .option("relationship.save.strategy", "keys")
    .option("relationship.source.labels", ":Customer")
    .option("relationship.source.node.keys", "customer_id:customer_id")
    .option("relationship.target.labels", ":Account")
    .option("relationship.target.node.keys", "account_id:account_id")
    .save()
)
print("OWNS relationships written.")

# --------------------------------------------------------------------------- #
# 12. Write HAS_PHONE relationships (Customer -> Phone)                        #
#     target.save.mode Overwrite MERGEs :Phone on number, so customers        #
#     sharing a phone converge on a single node. coalesce(1) serializes the   #
#     write: two partitions MERGEing the same shared value concurrently race  #
#     on node creation and one dies on the uniqueness constraint.             #
# --------------------------------------------------------------------------- #
(
    customers_df.select("customer_id", "phone")
    .coalesce(1)
    .write.format("org.neo4j.spark.DataSource")
    .mode("Overwrite")
    .options(**NEO4J_OPTS)
    .option("relationship", "HAS_PHONE")
    .option("relationship.save.strategy", "keys")
    .option("relationship.source.labels", ":Customer")
    .option("relationship.source.node.keys", "customer_id:customer_id")
    .option("relationship.target.labels", ":Phone")
    .option("relationship.target.node.keys", "phone:number")
    .option("relationship.target.save.mode", "Overwrite")
    .save()
)
print("HAS_PHONE relationships written.")

# --------------------------------------------------------------------------- #
# 13. Write HAS_ADDRESS relationships (Customer -> Address)                    #
#     coalesce(1) for the same shared-target MERGE race as HAS_PHONE.         #
# --------------------------------------------------------------------------- #
(
    customers_df.select("customer_id", "address")
    .coalesce(1)
    .write.format("org.neo4j.spark.DataSource")
    .mode("Overwrite")
    .options(**NEO4J_OPTS)
    .option("relationship", "HAS_ADDRESS")
    .option("relationship.save.strategy", "keys")
    .option("relationship.source.labels", ":Customer")
    .option("relationship.source.node.keys", "customer_id:customer_id")
    .option("relationship.target.labels", ":Address")
    .option("relationship.target.node.keys", "address:address")
    .option("relationship.target.save.mode", "Overwrite")
    .save()
)
print("HAS_ADDRESS relationships written.")

# --------------------------------------------------------------------------- #
# 14. Verify — quick counts                                                    #
# --------------------------------------------------------------------------- #
counts = gds.run_cypher("""
    MATCH (a:Account) WITH count(a) AS accounts
    MATCH (m:Merchant) WITH accounts, count(m) AS merchants
    MATCH (c:Customer) WITH accounts, merchants, count(c) AS customers
    MATCH (ph:Phone) WITH accounts, merchants, customers, count(ph) AS phones
    MATCH (ad:Address)
    WITH accounts, merchants, customers, phones, count(ad) AS addresses
    MATCH ()-[t:TRANSACTED_WITH]->()
    WITH accounts, merchants, customers, phones, addresses, count(t) AS txns
    MATCH ()-[p:TRANSFERRED_TO]->()
    WITH accounts, merchants, customers, phones, addresses, txns, count(p) AS p2p
    RETURN accounts, merchants, customers, phones, addresses, txns, p2p
""")
print(counts.to_string(index=False))
print("Done.")

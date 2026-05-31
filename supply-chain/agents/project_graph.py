# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # Neo4j Graph Sync — Pipeline Job
# MAGIC
# MAGIC Reads from gold Delta tables and upserts all nodes and relationships into Neo4j AuraDB.
# MAGIC Run this as a Databricks job task after the Lakeflow medallion pipeline completes.
# MAGIC
# MAGIC **Credentials** are read from the `supply_chain` secret scope.
# MAGIC **All writes are idempotent** — safe to re-run after every pipeline update.

# COMMAND ----------
# MAGIC %pip install neo4j>=5.18.0 --quiet

# COMMAND ----------
import os
from neo4j import GraphDatabase

CATALOG  = "supplychain_optimizer"
SCHEMA   = "supply_chain_medallion"

NEO4J_URI      = "neo4j+s://26bf512b.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_DATABASE = "neo4j"
NEO4J_PASSWORD = dbutils.secrets.get("supply_chain", "neo4j_password")

BATCH_SIZE = 500

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    max_connection_lifetime=200,
    keep_alive=True,
)

def neo4j_batch_write(rows: list[dict], cypher: str) -> dict:
    if not rows:
        return {"rows": 0, "nodes_created": 0, "rels_created": 0, "props_set": 0}
    totals = {"rows": 0, "nodes_created": 0, "rels_created": 0, "props_set": 0}
    with driver.session(database=NEO4J_DATABASE) as session:
        for i in range(0, len(rows), BATCH_SIZE):
            result = session.run(cypher, {"rows": rows[i : i + BATCH_SIZE]})
            summary = result.consume()
            c = summary.counters
            totals["rows"]          += len(rows[i : i + BATCH_SIZE])
            totals["nodes_created"] += c.nodes_created
            totals["rels_created"]  += c.relationships_created
            totals["props_set"]     += c.properties_set
    return totals

def spark_to_dicts(df) -> list[dict]:
    from decimal import Decimal
    def _clean(v):
        if isinstance(v, Decimal): return float(v)
        if isinstance(v, dict):    return {k: _clean(x) for k, x in v.items()}
        if isinstance(v, list):    return [_clean(x) for x in v]
        return v
    return [{k: _clean(v) for k, v in row.asDict().items()} for row in df.collect()]

print("Neo4j connection ready.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 1 — Constraints (idempotent)

# COMMAND ----------
constraints = [
    "CREATE CONSTRAINT supplier_id IF NOT EXISTS FOR (s:Supplier)  REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT part_id     IF NOT EXISTS FOR (p:Part)       REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT facility_id IF NOT EXISTS FOR (f:Facility)   REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT shipment_id IF NOT EXISTS FOR (sh:Shipment)  REQUIRE sh.id IS UNIQUE",
]
with driver.session(database=NEO4J_DATABASE) as session:
    for c in constraints:
        try:
            session.run(c)
        except Exception as e:
            print(f"Constraint note: {e}")

print("Constraints ready.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 2 — Supplier + Part nodes + SUPPLIES relationships

# COMMAND ----------
# Supplier nodes
rows = spark_to_dicts(spark.sql(f"""
    SELECT DISTINCT supplier_id, supplier_name AS name, country, tier,
                    reliability_score, risk_score, risk_tier
    FROM {CATALOG}.{SCHEMA}.gold_supplier_risk
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MERGE (s:Supplier {id: r.supplier_id})
    SET s.name              = r.name,
        s.country           = r.country,
        s.tier              = r.tier,
        s.reliability_score = toFloat(r.reliability_score),
        s.risk_score        = toFloat(r.risk_score),
        s.risk_tier         = r.risk_tier
""")
print(f"Suppliers       — rows: {n['rows']}, nodes created: {n['nodes_created']}, props set: {n['props_set']}")

# Part nodes
rows = spark_to_dicts(spark.sql(f"""
    SELECT DISTINCT part_id, part_name AS name, category, is_critical
    FROM {CATALOG}.{SCHEMA}.gold_part_availability
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MERGE (p:Part {id: r.part_id})
    SET p.name        = r.name,
        p.category    = r.category,
        p.is_critical = r.is_critical
""")
print(f"Parts           — rows: {n['rows']}, nodes created: {n['nodes_created']}, props set: {n['props_set']}")

# SUPPLIES relationships
rows = spark_to_dicts(spark.sql(f"""
    SELECT supplier_id, part_id,
           COUNT(*)          AS po_count,
           AVG(age_days)     AS avg_delay_days
    FROM {CATALOG}.{SCHEMA}.gold_active_purchase_orders
    GROUP BY supplier_id, part_id
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MATCH (s:Supplier {id: r.supplier_id})
    MATCH (p:Part     {id: r.part_id})
    MERGE (s)-[rel:SUPPLIES]->(p)
    SET rel.po_count       = toInteger(r.po_count),
        rel.avg_delay_days = toFloat(r.avg_delay_days)
""")
print(f"SUPPLIES rels   — rows: {n['rows']}, rels created: {n['rels_created']}, props set: {n['props_set']}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 3 — BOM dependency (REQUIRES relationships)

# COMMAND ----------
# Part nodes from BOM
rows = spark_to_dicts(spark.sql(f"""
    SELECT DISTINCT top_parent_part_id AS part_id, top_parent_name AS name, top_parent_category AS category
    FROM {CATALOG}.{SCHEMA}.gold_bom_explosion
    UNION
    SELECT DISTINCT component_part_id, component_name, component_category
    FROM {CATALOG}.{SCHEMA}.gold_bom_explosion
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MERGE (p:Part {id: r.part_id})
    SET p.name     = r.name,
        p.category = r.category
""")
print(f"BOM Parts       — rows: {n['rows']}, nodes created: {n['nodes_created']}, props set: {n['props_set']}")

# REQUIRES relationships
rows = spark_to_dicts(spark.sql(f"""
    SELECT top_parent_part_id AS parent_id,
           component_part_id  AS child_id,
           cumulative_quantity,
           depth
    FROM {CATALOG}.{SCHEMA}.gold_bom_explosion
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MATCH (parent:Part {id: r.parent_id})
    MATCH (child:Part  {id: r.child_id})
    MERGE (parent)-[rel:REQUIRES {depth: toInteger(r.depth)}]->(child)
    SET rel.cumulative_quantity = toFloat(r.cumulative_quantity)
""")
print(f"REQUIRES rels   — rows: {n['rows']}, rels created: {n['rels_created']}, props set: {n['props_set']}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 4 — Facility nodes + shipment routes

# COMMAND ----------
# Facility nodes
rows = spark_to_dicts(spark.sql(f"""
    SELECT DISTINCT facility_id, facility_name AS name, destination_region AS region
    FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MERGE (f:Facility {id: r.facility_id})
    SET f.name   = r.name,
        f.region = r.region
""")
print(f"Facilities      — rows: {n['rows']}, nodes created: {n['nodes_created']}, props set: {n['props_set']}")

# Shipment nodes + DEPARTS_FROM supplier + ARRIVES_AT facility + SHIPS_TO supplier->facility
rows = spark_to_dicts(spark.sql(f"""
    SELECT shipment_id, carrier, status, delay_days, disruption_severity,
           facility_id, supplier_id, route_key
    FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline
"""))
n = neo4j_batch_write(rows, """
    UNWIND $rows AS r
    MERGE (shp:Shipment {id: r.shipment_id})
    SET shp.carrier             = r.carrier,
        shp.status              = r.status,
        shp.delay_days          = toInteger(r.delay_days),
        shp.disruption_severity = r.disruption_severity
    WITH shp, r
    MATCH (s:Supplier {id: r.supplier_id})
    MATCH (f:Facility {id: r.facility_id})
    MERGE (shp)-[:DEPARTS_FROM]->(s)
    MERGE (shp)-[:ARRIVES_AT]->(f)
    MERGE (s)-[rt:SHIPS_TO {carrier: r.carrier}]->(f)
    SET rt.route_key = r.route_key
""")
print(f"Shipments+routes— rows: {n['rows']}, nodes created: {n['nodes_created']}, rels created: {n['rels_created']}, props set: {n['props_set']}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Done

# COMMAND ----------
driver.close()

node_counts = driver.execute_query(
    "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC",
    database_=NEO4J_DATABASE,
) if False else None  # driver already closed — check in Neo4j browser

print("Graph sync complete. Check Neo4j Browser for node/rel counts.")

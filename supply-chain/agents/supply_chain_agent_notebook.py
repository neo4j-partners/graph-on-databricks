# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # Supply Chain Optimizer — Agent Layer
# MAGIC
# MAGIC Router → SQL Agent (gold Delta tables), Graph Agent (Neo4j Cypher), or GDS Agent (graph algorithms)
# MAGIC
# MAGIC **Setup:** Store secrets before first run:
# MAGIC ```
# MAGIC databricks secrets create-scope supply_chain
# MAGIC databricks secrets put-secret supply_chain anthropic_api_key   --string-value sk-ant-...
# MAGIC databricks secrets put-secret supply_chain neo4j_password       --string-value <password>
# MAGIC ```

# COMMAND ----------
# MAGIC %pip install anthropic>=0.49.0 neo4j>=5.18.0 --quiet

# COMMAND ----------
# ── Widget inputs ─────────────────────────────────────────────────────────────
dbutils.widgets.text("question", "Which suppliers have Critical risk scores?", "Question")
dbutils.widgets.dropdown("route_override", "auto", ["auto", "sql", "graph", "gds"], "Force Route")
dbutils.widgets.dropdown("model", "claude-sonnet-4-6", ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"], "Model")

# ── Credentials ───────────────────────────────────────────────────────────────
import os, json, hashlib, time
from decimal import Decimal
from datetime import datetime, timezone

def _secret(scope: str, key: str, fallback_env: str = "") -> str:
    try:
        return dbutils.secrets.get(scope=scope, key=key)
    except Exception:
        val = os.getenv(fallback_env, "")
        if not val:
            raise EnvironmentError(f"Secret '{scope}/{key}' not found and env var '{fallback_env}' is not set.")
        return val

ANTHROPIC_API_KEY = _secret("supply_chain", "anthropic_api_key", "ANTHROPIC_API_KEY")
NEO4J_URI         = os.getenv("NEO4J_URI",      "neo4j+s://26bf512b.databases.neo4j.io")
NEO4J_USERNAME    = os.getenv("NEO4J_USERNAME",  "neo4j")
NEO4J_PASSWORD    = _secret("supply_chain", "neo4j_password", "NEO4J_PASSWORD")
NEO4J_DATABASE    = os.getenv("NEO4J_DATABASE",  "neo4j")

CATALOG         = "supplychain"
SCHEMA          = "supply_chain_medallion"
MAX_SQL_ROWS    = 500
CACHE_TTL_HOURS = 24
OPUS_MODELS     = {"claude-opus-4-6"}

print("Config loaded.")

# COMMAND ----------
# ── SQL helpers (spark directly — no SDK needed in notebook) ──────────────────

def _safe(val):
    if isinstance(val, Decimal):
        return float(val)
    return val

def run_sql(query: str) -> list[dict]:
    df   = spark.sql(query)
    rows = df.limit(MAX_SQL_ROWS).collect()
    cols = df.columns
    return [{k: _safe(v) for k, v in zip(cols, row)} for row in rows]

def ensure_cache_table() -> None:
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.answer_cache (
            question_hash  STRING    NOT NULL,
            question_text  STRING,
            query_type     STRING,
            subgraph_type  STRING,
            result_json    STRING,
            computed_at    TIMESTAMP,
            ttl_hours      INT,
            hit_count      BIGINT
        )
        USING DELTA
        CLUSTER BY (question_hash)
        TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
    """)

ensure_cache_table()
print("Cache table ready.")

# COMMAND ----------
# ── Answer cache ──────────────────────────────────────────────────────────────

def cache_hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()

def cache_get(question: str) -> dict | None:
    h = cache_hash(question)
    rows = run_sql(f"""
        SELECT result_json, computed_at, ttl_hours
        FROM {CATALOG}.{SCHEMA}.answer_cache
        WHERE question_hash = '{h}' LIMIT 1
    """)
    if not rows:
        return None
    row = rows[0]
    computed_at = datetime.fromisoformat(str(row["computed_at"]).replace("Z", "+00:00"))
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - computed_at).total_seconds() / 3600 > float(row["ttl_hours"] or 24):
        return None
    spark.sql(f"UPDATE {CATALOG}.{SCHEMA}.answer_cache SET hit_count = hit_count + 1 WHERE question_hash = '{h}'")
    try:
        cached = json.loads(row["result_json"])
    except Exception:
        cached = None
    answer_text = (cached or {}).get("result", {}).get("answer", "") if cached else ""
    if not cached or "iteration limit" in answer_text.lower():
        spark.sql(f"DELETE FROM {CATALOG}.{SCHEMA}.answer_cache WHERE question_hash = '{h}'")
        return None
    return cached

def cache_put(question: str, result: dict, query_type: str, subgraph_type: str = "") -> None:
    from pyspark.sql.types import StructType, StructField, StringType, TimestampType, IntegerType, LongType
    from pyspark.sql import Row
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    schema = StructType([
        StructField("question_hash", StringType(),    False),
        StructField("question_text", StringType(),    True),
        StructField("query_type",    StringType(),    True),
        StructField("subgraph_type", StringType(),    True),
        StructField("result_json",   StringType(),    True),
        StructField("computed_at",   TimestampType(), True),
        StructField("ttl_hours",     IntegerType(),   True),
        StructField("hit_count",     LongType(),      True),
    ])
    row = Row(
        question_hash=cache_hash(question), question_text=question,
        query_type=query_type, subgraph_type=subgraph_type or "",
        result_json=json.dumps(result), computed_at=now,
        ttl_hours=CACHE_TTL_HOURS, hit_count=0,
    )
    df = spark.createDataFrame([row], schema=schema)
    df.createOrReplaceTempView("_cache_upsert")
    spark.sql(f"""
        MERGE INTO {CATALOG}.{SCHEMA}.answer_cache AS t
        USING _cache_upsert AS s ON t.question_hash = s.question_hash
        WHEN MATCHED THEN UPDATE SET
            t.result_json=s.result_json, t.computed_at=s.computed_at,
            t.ttl_hours=s.ttl_hours, t.hit_count=0
        WHEN NOT MATCHED THEN INSERT *
    """)

print("Cache helpers ready.")

# COMMAND ----------
# ── Neo4j connector ───────────────────────────────────────────────────────────
from neo4j import GraphDatabase
from neo4j.graph import Node, Relationship, Path

class Neo4jConnector:
    BATCH_SIZE = 500

    def __init__(self):
        self._driver    = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        self._projected: set[str] = set()
        self._ensure_constraints()

    def close(self):
        self._driver.close()

    def query(self, cypher: str, params: dict = None) -> list[dict]:
        def _convert(val):
            if isinstance(val, Node):         return {"_labels": list(val.labels), **dict(val)}
            elif isinstance(val, Relationship): return {"_type": val.type, **dict(val)}
            elif isinstance(val, Path):         return [_convert(n) for n in val.nodes]
            elif isinstance(val, list):         return [_convert(v) for v in val]
            return val
        with self._driver.session(database=NEO4J_DATABASE) as s:
            return [{k: _convert(v) for k, v in dict(r).items()} for r in s.run(cypher, params or {})]

    def _write_batch(self, rows: list[dict], cypher: str) -> int:
        if not rows:
            return 0
        total = 0
        with self._driver.session(database=NEO4J_DATABASE) as s:
            for i in range(0, len(rows), self.BATCH_SIZE):
                s.run(cypher, {"rows": rows[i:i+self.BATCH_SIZE]})
                total += len(rows[i:i+self.BATCH_SIZE])
        return total

    def _ensure_constraints(self):
        for c in [
            "CREATE CONSTRAINT supplier_id IF NOT EXISTS FOR (s:Supplier) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT part_id     IF NOT EXISTS FOR (p:Part)     REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT facility_id IF NOT EXISTS FOR (f:Facility) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT shipment_id IF NOT EXISTS FOR (sh:Shipment) REQUIRE sh.id IS UNIQUE",
        ]:
            try:
                self.query(c)
            except Exception:
                pass

    _EXISTENCE_CHECKS = {
        "supplier_risk":  "MATCH ()-[:SUPPLIES]->() RETURN count(*) AS n",
        "bom_dependency": "MATCH ()-[:REQUIRES]->() RETURN count(*) AS n",
        "shipment_route": "MATCH ()-[:SHIPS_TO]->()  RETURN count(*) AS n",
    }

    def _already_projected(self, subgraph_type: str) -> bool:
        if subgraph_type == "full_network":
            return all(self._already_projected(t) for t in ["supplier_risk", "bom_dependency", "shipment_route"])
        cypher = self._EXISTENCE_CHECKS.get(subgraph_type)
        if not cypher:
            return False
        rows = self.query(cypher)
        return bool(rows and rows[0].get("n", 0) > 0)

    def project_subgraph(self, subgraph_type: str) -> int:
        if subgraph_type in self._projected or self._already_projected(subgraph_type):
            self._projected.add(subgraph_type)
            print(f"  [Neo4j] '{subgraph_type}' already projected — skipping")
            return 0
        projectors = {
            "supplier_risk":  self._project_supplier_risk,
            "bom_dependency": self._project_bom_dependency,
            "shipment_route": self._project_shipment_route,
            "full_network":   self._project_full_network,
        }
        if subgraph_type not in projectors:
            raise ValueError(f"Unknown subgraph_type: {subgraph_type}")
        count = projectors[subgraph_type]()
        self._projected.add(subgraph_type)
        print(f"  [Neo4j] Projected '{subgraph_type}': {count} nodes/rels")
        return count

    def _project_supplier_risk(self) -> int:
        total = 0
        rows = run_sql(f"SELECT DISTINCT supplier_id, supplier_name AS name, country, tier, reliability_score, risk_score, risk_tier FROM {CATALOG}.{SCHEMA}.gold_supplier_risk LIMIT 500")
        total += self._write_batch(rows, "UNWIND $rows AS r MERGE (s:Supplier {id: r.supplier_id}) SET s.name=r.name, s.country=r.country, s.tier=r.tier, s.reliability_score=toFloat(r.reliability_score), s.risk_score=toFloat(r.risk_score), s.risk_tier=r.risk_tier")
        rows = run_sql(f"SELECT DISTINCT part_id, part_name AS name, category, is_critical FROM {CATALOG}.{SCHEMA}.gold_part_availability LIMIT 500")
        total += self._write_batch(rows, "UNWIND $rows AS r MERGE (p:Part {id: r.part_id}) SET p.name=r.name, p.category=r.category, p.is_critical=r.is_critical")
        rows = run_sql(f"SELECT supplier_id, part_id, COUNT(*) AS po_count, AVG(aging_days) AS avg_delay_days FROM {CATALOG}.{SCHEMA}.gold_active_purchase_orders GROUP BY supplier_id, part_id LIMIT 2000")
        total += self._write_batch(rows, "UNWIND $rows AS r MATCH (s:Supplier {id: r.supplier_id}) MATCH (p:Part {id: r.part_id}) MERGE (s)-[rel:SUPPLIES]->(p) SET rel.po_count=toInteger(r.po_count), rel.avg_delay_days=toFloat(r.avg_delay_days)")
        return total

    def _project_bom_dependency(self) -> int:
        total = 0
        rows = run_sql(f"SELECT top_parent_part_id AS part_id, top_parent_name AS name, top_parent_category AS category FROM {CATALOG}.{SCHEMA}.gold_bom_explosion UNION SELECT component_part_id, component_name, component_category FROM {CATALOG}.{SCHEMA}.gold_bom_explosion LIMIT 1000")
        total += self._write_batch(rows, "UNWIND $rows AS r MERGE (p:Part {id: r.part_id}) SET p.name=r.name, p.category=r.category")
        rows = run_sql(f"SELECT top_parent_part_id AS parent_id, component_part_id AS child_id, cumulative_quantity, depth FROM {CATALOG}.{SCHEMA}.gold_bom_explosion LIMIT 5000")
        total += self._write_batch(rows, "UNWIND $rows AS r MATCH (parent:Part {id: r.parent_id}) MATCH (child:Part {id: r.child_id}) MERGE (parent)-[rel:REQUIRES {depth: toInteger(r.depth)}]->(child) SET rel.cumulative_quantity=toFloat(r.cumulative_quantity)")
        return total

    def _project_shipment_route(self) -> int:
        total = 0
        # Schema: supplier_id → facility_id (no origin/destination facility pair)
        rows = run_sql(f"SELECT DISTINCT facility_id, facility_name AS name, destination_region AS region FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline LIMIT 200")
        total += self._write_batch(rows, "UNWIND $rows AS r MERGE (f:Facility {id: r.facility_id}) SET f.name=r.name, f.region=r.region")
        rows = run_sql(f"SELECT shipment_id, supplier_id, facility_id, carrier, status, delay_days, disruption_severity, route_key FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline LIMIT 2000")
        total += self._write_batch(rows, "UNWIND $rows AS r MERGE (shp:Shipment {id: r.shipment_id}) SET shp.carrier=r.carrier, shp.status=r.status, shp.delay_days=toInteger(r.delay_days), shp.disruption_severity=r.disruption_severity WITH shp, r MATCH (s:Supplier {id: r.supplier_id}) MATCH (f:Facility {id: r.facility_id}) MERGE (shp)-[:DEPARTS_FROM]->(s) MERGE (shp)-[:ARRIVES_AT]->(f) MERGE (s)-[rt:SHIPS_TO {carrier: r.carrier}]->(f) SET rt.route_key=r.route_key")
        return total

    def _project_full_network(self) -> int:
        return self._project_supplier_risk() + self._project_bom_dependency() + self._project_shipment_route()

    # ── GDS projections ────────────────────────────────────────────────────────
    GDS_PROJECT_CYPHER = {
        "bom_network": """
            CALL gds.graph.project(
                'bom_network', 'Part',
                {REQUIRES: {type: 'REQUIRES', orientation: 'NATURAL', properties: ['cumulative_quantity']}}
            ) YIELD graphName, nodeCount, relationshipCount
        """,
        "supply_risk_network": """
            CALL gds.graph.project(
                'supply_risk_network', ['Supplier', 'Part'],
                {SUPPLIES: {type: 'SUPPLIES', orientation: 'NATURAL', properties: ['po_count', 'avg_delay_days']}}
            ) YIELD graphName, nodeCount, relationshipCount
        """,
        "facility_network": """
            CALL gds.graph.project(
                'facility_network', ['Supplier', 'Facility'], 'SHIPS_TO'
            ) YIELD graphName, nodeCount, relationshipCount
        """,
    }

    GDS_PREREQS = {
        "bom_network":         ["bom_dependency"],
        "supply_risk_network": ["supplier_risk"],
        "facility_network":    ["shipment_route"],
    }

    def gds_projection_exists(self, name: str) -> bool:
        try:
            rows = self.query(f"CALL gds.graph.exists('{name}') YIELD exists")
            return bool(rows and rows[0].get("exists"))
        except Exception:
            return False

    def ensure_gds_projection(self, name: str) -> str:
        for sg in self.GDS_PREREQS.get(name, []):
            self.project_subgraph(sg)
        if self.gds_projection_exists(name):
            return f"GDS projection '{name}' already exists"
        cypher = self.GDS_PROJECT_CYPHER.get(name)
        if not cypher:
            return f"No projection definition for '{name}'"
        try:
            rows = self.query(cypher)
            row  = rows[0] if rows else {}
            return f"Created GDS projection '{name}': {row.get('nodeCount',0)} nodes, {row.get('relationshipCount',0)} rels"
        except Exception as e:
            return f"GDS projection '{name}' failed: {e}"

neo4j = Neo4jConnector()
print("Neo4j connector ready.")

# COMMAND ----------
# ── Prompts ───────────────────────────────────────────────────────────────────
import anthropic

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ROUTER_SYSTEM = """You are a supply chain analytics router. Call exactly one tool — never answer in plain text.

Use route_to_sql for:
- Risk scores, risk tiers, reliability rankings
- Part availability, stock status, lead times
- Purchase order status, aging, exposure
- Shipment delays, disruption severity
- BOM cost rollup, component counts

Use route_to_graph for:
- "What happens if X fails / is disrupted"
- "What is at risk if..."
- "Which parts/assemblies depend on supplier X"
- Relationship chains, multi-hop dependencies
- Ripple-effect or cascading impact analysis

Use route_to_gds for:
- Bottleneck or centrality questions ("most critical node", "biggest bottleneck")
- Network-wide scoring that requires algorithm execution (PageRank, Betweenness)
- Cluster or community detection ("which suppliers cluster together")
- Node similarity ("find suppliers like X", "substitutes for this part")
- Weighted shortest path ("cheapest sourcing path", "least-delay route")
- Connected components ("isolated parts", "disconnected subgraphs")

When in doubt: IMPACT/DEPENDENCY → graph. NETWORK SCORING/CLUSTERING/PATH → gds."""

ROUTER_TOOLS = [
    {"name": "route_to_sql",   "description": "Route to SQL agent.", "input_schema": {"type": "object", "properties": {"question": {"type": "string"}, "relevant_tables": {"type": "array", "items": {"type": "string"}}}, "required": ["question", "relevant_tables"]}},
    {"name": "route_to_graph", "description": "Route to graph traversal agent.", "input_schema": {"type": "object", "properties": {"question": {"type": "string"}, "subgraph_type": {"type": "string", "enum": ["supplier_risk", "bom_dependency", "shipment_route", "full_network"]}}, "required": ["question", "subgraph_type"]}},
    {"name": "route_to_gds",   "description": "Route to GDS algorithm agent.", "input_schema": {"type": "object", "properties": {"question": {"type": "string"}, "projection": {"type": "string", "enum": ["bom_network", "supply_risk_network", "facility_network"]}}, "required": ["question", "projection"]}},
]

SQL_SYSTEM = f"""You are a Databricks SQL analyst for a manufacturing supply chain.
Gold tables in {CATALOG}.{SCHEMA}:
- gold_supplier_risk: supplier_id, supplier_name, country, tier, risk_score (0-100), risk_tier (Low/Medium/High/Critical)
- gold_part_availability: part_id, part_name, category, is_critical, facility_id, stock_status
- gold_active_purchase_orders: po_id, supplier_id, part_id, status, aging_days, exposure_score
- gold_shipment_pipeline: shipment_id, carrier, delay_days, disruption_severity, route_key
- gold_bom_explosion: top_parent_part_id, component_part_id, depth (1-2), cumulative_quantity, rolled_up_cost_usd
Always use fully-qualified table names. Max {MAX_SQL_ROWS} rows."""

SQL_TOOLS = [{"name": "execute_sql", "description": "Run SQL against gold tables.", "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}, "description": {"type": "string"}}, "required": ["sql", "description"]}}]

GRAPH_SYSTEM = """You are a Neo4j graph analyst for a supply chain network.
Subgraphs and their relationships:
- supplier_risk   → (:Supplier)-[:SUPPLIES]->(:Part)
- bom_dependency  → (:Part)-[:REQUIRES {depth}]->(:Part)
- shipment_route  → (:Supplier)-[:SHIPS_TO]->(:Facility)
All required subgraphs are pre-projected before you start. Run Cypher queries directly.
Node properties — Supplier: id, name, country, tier, risk_score, risk_tier | Part: id, name, category, is_critical | Facility: id, name, region"""

GRAPH_TOOLS = [{"name": "run_cypher", "description": "Run Cypher against Neo4j.", "input_schema": {"type": "object", "properties": {"cypher": {"type": "string"}, "description": {"type": "string"}}, "required": ["cypher", "description"]}}]

GDS_SYSTEM = """You are a Neo4j GDS analyst for a supply chain network.
Three named in-memory graph projections are pre-created for you:
- "bom_network"          — Part nodes, REQUIRES relationships (weight: cumulative_quantity). Best for: gds.pageRank, gds.betweenness, gds.wcc, gds.shortestPath.dijkstra
- "supply_risk_network"  — Supplier + Part nodes, SUPPLIES relationships (weights: po_count, avg_delay_days). Best for: gds.nodeSimilarity, gds.louvain, gds.shortestPath.dijkstra
- "facility_network"     — Supplier + Facility nodes, SHIPS_TO relationships (Supplier→Facility). Best for: gds.betweenness, gds.shortestPath.dijkstra, gds.louvain

Node properties: Supplier: id, name, country, tier, reliability_score, risk_score, risk_tier | Part: id, name, category, is_critical | Facility: id, name, region

GDS procedure patterns:
  CALL gds.pageRank.stream("<projection>", {maxIterations: 20, dampingFactor: 0.85}) YIELD nodeId, score
  CALL gds.betweenness.stream("<projection>") YIELD nodeId, score
  CALL gds.louvain.stream("<projection>") YIELD nodeId, communityId
  CALL gds.nodeSimilarity.stream("<projection>") YIELD node1, node2, similarity
  CALL gds.wcc.stream("<projection>") YIELD nodeId, componentId

Always resolve nodeId → node using gds.util.asNode(nodeId). Return names and IDs. Limit results to top 20."""

GDS_TOOLS = [{"name": "run_gds_cypher", "description": "Run a GDS procedure or Cypher query against Neo4j.", "input_schema": {"type": "object", "properties": {"cypher": {"type": "string"}, "description": {"type": "string"}}, "required": ["cypher", "description"]}}]

print("Prompts ready.")

# COMMAND ----------
# ── Agents ────────────────────────────────────────────────────────────────────

def _text(content):
    return "\n".join(b.text for b in content if hasattr(b, "type") and b.type == "text").strip()

def _thinking(model: str, enabled: bool = False) -> dict:
    return {"type": "adaptive"} if enabled and model in OPUS_MODELS else {"type": "disabled"}

def sql_agent(question: str, relevant_tables: list, model: str) -> dict:
    messages, queries = [{"role": "user", "content": question}], []
    for _ in range(6):
        resp = client.messages.create(model=model, max_tokens=4096, thinking=_thinking(model), system=SQL_SYSTEM, tools=SQL_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return {"answer": _text(resp.content), "queries": queries}
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type != "tool_use": continue
                print(f"  [SQL] {b.input.get('description','')}")
                try:
                    rows = run_sql(b.input["sql"])
                    queries.append({"sql": b.input["sql"], "rows": rows})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:MAX_SQL_ROWS])})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
            messages.append({"role": "user", "content": results})
    return {"answer": "Could not complete within iteration limit.", "queries": queries}

def graph_agent(question: str, subgraph_type: str, model: str) -> dict:
    required = {"supplier_risk": ["supplier_risk"], "bom_dependency": ["bom_dependency"], "shipment_route": ["shipment_route"], "full_network": ["supplier_risk", "bom_dependency", "shipment_route"]}
    for sg in required.get(subgraph_type, [subgraph_type]):
        neo4j.project_subgraph(sg)
    messages, queries = [{"role": "user", "content": question}], []
    for _ in range(8):
        resp = client.messages.create(model=model, max_tokens=4096, thinking=_thinking(model), system=GRAPH_SYSTEM, tools=GRAPH_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return {"answer": _text(resp.content), "cypher_queries": queries, "subgraph_type": subgraph_type}
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type != "tool_use": continue
                print(f"  [Cypher] {b.input.get('description','')}")
                try:
                    rows = neo4j.query(b.input["cypher"])
                    queries.append({"cypher": b.input["cypher"], "rows": rows})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:50])})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
            messages.append({"role": "user", "content": results})
    return {"answer": "Could not complete within iteration limit.", "cypher_queries": queries, "subgraph_type": subgraph_type}

def gds_agent(question: str, projection: str, model: str) -> dict:
    msg = neo4j.ensure_gds_projection(projection)
    print(f"  [GDS] {msg}")
    messages, queries = [{"role": "user", "content": question}], []
    for _ in range(8):
        resp = client.messages.create(model=model, max_tokens=4096, thinking=_thinking(model), system=GDS_SYSTEM, tools=GDS_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return {"answer": _text(resp.content), "gds_queries": queries, "projection": projection}
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type != "tool_use": continue
                print(f"  [GDS Cypher] {b.input.get('description','')}")
                try:
                    rows = neo4j.query(b.input["cypher"])
                    queries.append({"cypher": b.input["cypher"], "rows": rows})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:50])})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
            messages.append({"role": "user", "content": results})
    return {"answer": "Could not complete within iteration limit.", "gds_queries": queries, "projection": projection}

print("Agents ready.")

# COMMAND ----------
# ── Router ────────────────────────────────────────────────────────────────────

def route_and_answer(question: str, model: str, route_override: str = "auto") -> dict:
    t0 = time.time()

    cached = cache_get(question)
    if cached:
        print(f"  [Cache HIT] {time.time()-t0:.2f}s")
        return {**cached, "from_cache": True}

    if route_override in ("sql", "graph", "gds"):
        route = route_override
        tool_input = {"question": question, "relevant_tables": [], "subgraph_type": "full_network", "projection": "bom_network"}
        print(f"  [Route FORCED → {route.upper()}]")
    else:
        resp = client.messages.create(
            model=model, max_tokens=512,
            system=ROUTER_SYSTEM, tools=ROUTER_TOOLS, tool_choice={"type": "any"},
            messages=[{"role": "user", "content": question}],
        )
        tool = next((b for b in resp.content if b.type == "tool_use"), None)
        if tool is None:
            route, tool_input = "sql", {"question": question, "relevant_tables": []}
        else:
            route      = {"route_to_sql": "sql", "route_to_graph": "graph", "route_to_gds": "gds"}.get(tool.name, "sql")
            tool_input = tool.input
        print(f"  [Route → {route.upper()}] router: {time.time()-t0:.2f}s")

    t_agent = time.time()
    if route == "sql":
        result = sql_agent(question, tool_input.get("relevant_tables", []), model)
    elif route == "gds":
        result = gds_agent(question, tool_input.get("projection", "bom_network"), model)
    else:
        result = graph_agent(question, tool_input.get("subgraph_type", "full_network"), model)

    elapsed = time.time() - t0
    print(f"  [Agent: {time.time()-t_agent:.2f}s | Total: {elapsed:.2f}s]")

    payload = {"route": route, "result": result, "from_cache": False}
    answer_text = result.get("answer", "")
    if answer_text and "iteration limit" not in answer_text.lower():
        cache_put(question, payload, route, tool_input.get("subgraph_type", "") or tool_input.get("projection", ""))
    return payload

print("Router ready.")

# COMMAND ----------
# ── Ask a question ────────────────────────────────────────────────────────────
question       = dbutils.widgets.get("question")
route_override = dbutils.widgets.get("route_override")
model          = dbutils.widgets.get("model")

print(f"\nQuestion : {question}")
print(f"Model    : {model}\n")

output = route_and_answer(question, model, route_override)

route      = output.get("route", "?")
from_cache = output.get("from_cache", False)
inner      = output.get("result", {})

print(f"\n{'='*60}")
print(f"  Route: {route.upper()}{'  [CACHED]' if from_cache else ''}")
print(f"{'='*60}")
print(inner.get("answer", ""))

queries = inner.get("queries") or inner.get("cypher_queries") or inner.get("gds_queries") or []
if queries:
    print(f"\n  — {len(queries)} quer{'y' if len(queries)==1 else 'ies'} executed")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Example questions to try
# MAGIC
# MAGIC **SQL — Delta Lake**
# MAGIC - `Which suppliers have Critical risk scores?`
# MAGIC - `Show me all delayed purchase orders over 30 days old`
# MAGIC - `What are the top 10 most expensive BOM assemblies?`
# MAGIC - `Which shipments have High or Critical disruption severity?`
# MAGIC - `What is the stock status for critical parts?`
# MAGIC
# MAGIC **Graph — Neo4j Cypher traversal**
# MAGIC - `What parts are at risk if our highest-risk supplier fails?`
# MAGIC - `Which critical parts have only a single supplier?`
# MAGIC - `What assemblies would be affected if a Tier-1 supplier from China is disrupted?`
# MAGIC - `Show me the most depended-upon components in the BOM network`
# MAGIC - `Which carrier routes have the most disrupted shipments?`
# MAGIC
# MAGIC **GDS — Neo4j Graph Algorithms**
# MAGIC - `Which parts are the biggest structural bottlenecks in the BOM? (Betweenness Centrality)`
# MAGIC - `Rank parts by how many assemblies depend on them using PageRank`
# MAGIC - `Which suppliers have the most similar part portfolios? (Node Similarity)`
# MAGIC - `Detect supplier-part communities — which clusters are most exposed to risk? (Louvain)`
# MAGIC - `Which facilities are the most critical routing hubs in the shipment network?`
# MAGIC - `Are there any isolated or disconnected parts in the BOM? (WCC)`

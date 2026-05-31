"""
Supply Chain Optimizer — Databricks App
Gradio chat UI backed by router + SQL agent + graph agent.
"""
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import anthropic
import gradio as gr
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from neo4j import GraphDatabase
from neo4j.graph import Node, Relationship, Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
NEO4J_URI    = os.environ.get("NEO4J_URI",      "neo4j+s://26bf512b.databases.neo4j.io")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
CATALOG      = os.environ.get("SUPPLYCHAIN_CATALOG", "supplychain")
SCHEMA       = os.environ.get("SUPPLYCHAIN_SCHEMA",  "supply_chain_medallion")
CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]
OPUS_MODELS = {"claude-opus-4-6"}
MAX_SQL_ROWS = 200
CACHE_TTL_HOURS = 24

# ── Databricks SDK ────────────────────────────────────────────────────────────
# Databricks Apps injects DATABRICKS_HOST and DATABRICKS_TOKEN automatically.
_host  = os.environ.get("DATABRICKS_HOST",  "https://dbc-768fa6aa-1875.cloud.databricks.com")
_token = os.environ.get("DATABRICKS_TOKEN", "")
dbx = WorkspaceClient(host=_host, token=_token) if _token else WorkspaceClient(host=_host)

# Read secrets via SDK
def _get_secret(scope: str, key: str, env_fallback: str = "") -> str:
    try:
        import base64
        val = dbx.secrets.get_secret(scope=scope, key=key)
        return base64.b64decode(val.value).decode("utf-8")
    except Exception as e:
        logger.warning("Secret fetch failed (%s/%s): %s", scope, key, e)
        return os.environ.get(env_fallback, "")

ANTHROPIC_API_KEY = _get_secret("supply_chain", "anthropic_api_key", "ANTHROPIC_API_KEY")
NEO4J_PASSWORD    = _get_secret("supply_chain", "neo4j_password",    "NEO4J_PASSWORD")
_warehouse_id = None

def get_warehouse_id() -> str:
    global _warehouse_id
    if _warehouse_id:
        return _warehouse_id
    for wh in dbx.warehouses.list():
        if wh.state and wh.state.value in ("RUNNING", "STARTING"):
            _warehouse_id = wh.id
            return _warehouse_id
    _warehouse_id = list(dbx.warehouses.list())[0].id
    return _warehouse_id

def _safe(val):
    if isinstance(val, Decimal):
        return float(val)
    return val

def run_sql(query: str) -> list[dict]:
    stmt = dbx.statement_execution.execute_statement(
        warehouse_id=get_warehouse_id(),
        statement=query,
    )
    while stmt.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(0.5)
        stmt = dbx.statement_execution.get_statement(stmt.statement_id)
    if stmt.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL failed: {stmt.status.error}")
    if not stmt.result or not stmt.result.data_array:
        return []
    cols = [c.name for c in stmt.manifest.schema.columns]
    return [{k: _safe(v) for k, v in zip(cols, row)} for row in stmt.result.data_array]

# ── Answer cache ──────────────────────────────────────────────────────────────
def cache_hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()

def cache_get(question: str) -> dict | None:
    h = cache_hash(question)
    try:
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
        cached = json.loads(row["result_json"])
        answer_text = (cached or {}).get("result", {}).get("answer", "")
        if not cached or "iteration limit" in answer_text.lower():
            run_sql(f"DELETE FROM {CATALOG}.{SCHEMA}.answer_cache WHERE question_hash = '{h}'")
            return None
        run_sql(f"UPDATE {CATALOG}.{SCHEMA}.answer_cache SET hit_count = hit_count + 1 WHERE question_hash = '{h}'")
        return cached
    except Exception as e:
        logger.warning("Cache read error: %s", e)
        return None

def cache_put(question: str, result: dict, query_type: str, subgraph_type: str = "") -> None:
    answer_text = result.get("result", {}).get("answer", "")
    if not answer_text or "iteration limit" in answer_text.lower():
        return
    try:
        from databricks.sdk.service.sql import StatementParameterListItem
        h   = cache_hash(question)
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        result_json = json.dumps(result)
        # Write via temp table to avoid SQL injection / control char issues
        import tempfile, os as _os
        data = [{
            "question_hash": h, "question_text": question,
            "query_type": query_type, "subgraph_type": subgraph_type or "",
            "result_json": result_json, "computed_at": now,
            "ttl_hours": CACHE_TTL_HOURS, "hit_count": 0,
        }]
        # Use multi-statement approach: insert via VALUES with escaped JSON
        safe_json = result_json.replace("\\", "\\\\").replace("'", "\\'")
        safe_q    = question.replace("'", "\\'")
        run_sql(f"""
            MERGE INTO {CATALOG}.{SCHEMA}.answer_cache AS t
            USING (
                SELECT '{h}' AS question_hash,
                       '{safe_q[:500]}' AS question_text,
                       '{query_type}' AS query_type,
                       '{subgraph_type}' AS subgraph_type,
                       '{safe_json}' AS result_json,
                       TIMESTAMP '{now}' AS computed_at,
                       {CACHE_TTL_HOURS} AS ttl_hours,
                       0L AS hit_count
            ) AS s ON t.question_hash = s.question_hash
            WHEN MATCHED THEN UPDATE SET
                t.result_json=s.result_json, t.computed_at=s.computed_at,
                t.ttl_hours=s.ttl_hours, t.hit_count=0
            WHEN NOT MATCHED THEN INSERT *
        """)
    except Exception as e:
        logger.warning("Cache write error: %s", e)

# ── Neo4j ─────────────────────────────────────────────────────────────────────
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
_projected: set[str] = set()
BATCH_SIZE = 500

def _convert(val):
    if isinstance(val, Node):
        return {"_labels": list(val.labels), **dict(val)}
    elif isinstance(val, Relationship):
        return {"_type": val.type, **dict(val)}
    elif isinstance(val, Path):
        return [_convert(n) for n in val.nodes]
    elif isinstance(val, list):
        return [_convert(v) for v in val]
    return val

def neo4j_query(cypher: str, params: dict = None) -> list[dict]:
    with neo4j_driver.session(database=NEO4J_DATABASE) as s:
        return [{k: _convert(v) for k, v in dict(r).items()} for r in s.run(cypher, params or {})]

def neo4j_write_batch(rows: list[dict], cypher: str) -> int:
    if not rows:
        return 0
    total = 0
    with neo4j_driver.session(database=NEO4J_DATABASE) as s:
        for i in range(0, len(rows), BATCH_SIZE):
            s.run(cypher, {"rows": rows[i:i+BATCH_SIZE]})
            total += len(rows[i:i+BATCH_SIZE])
    return total

def _already_projected(subgraph_type: str) -> bool:
    checks = {
        "supplier_risk":  "MATCH ()-[:SUPPLIES]->() RETURN count(*) AS n",
        "bom_dependency": "MATCH ()-[:REQUIRES]->() RETURN count(*) AS n",
        "shipment_route": "MATCH ()-[:SHIPS_TO]->()  RETURN count(*) AS n",
    }
    if subgraph_type == "full_network":
        return all(_already_projected(t) for t in ["supplier_risk", "bom_dependency", "shipment_route"])
    cypher = checks.get(subgraph_type)
    if not cypher:
        return False
    rows = neo4j_query(cypher)
    return bool(rows and rows[0].get("n", 0) > 0)

def project_subgraph(subgraph_type: str) -> str:
    if subgraph_type in _projected or _already_projected(subgraph_type):
        _projected.add(subgraph_type)
        return f"'{subgraph_type}' already in graph — skipping"

    if subgraph_type == "full_network":
        for sg in ["supplier_risk", "bom_dependency", "shipment_route"]:
            project_subgraph(sg)
        _projected.add("full_network")
        return "Full network projected"

    total = 0
    if subgraph_type == "supplier_risk":
        rows = run_sql(f"SELECT DISTINCT supplier_id, supplier_name AS name, country, tier, reliability_score, risk_score, risk_tier FROM {CATALOG}.{SCHEMA}.gold_supplier_risk LIMIT 500")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MERGE (s:Supplier {id: r.supplier_id}) SET s.name=r.name, s.country=r.country, s.tier=r.tier, s.reliability_score=toFloat(r.reliability_score), s.risk_score=toFloat(r.risk_score), s.risk_tier=r.risk_tier")
        rows = run_sql(f"SELECT DISTINCT part_id, part_name AS name, category, is_critical FROM {CATALOG}.{SCHEMA}.gold_part_availability LIMIT 500")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MERGE (p:Part {id: r.part_id}) SET p.name=r.name, p.category=r.category, p.is_critical=r.is_critical")
        rows = run_sql(f"SELECT supplier_id, part_id, COUNT(*) AS po_count, AVG(aging_days) AS avg_delay_days FROM {CATALOG}.{SCHEMA}.gold_active_purchase_orders GROUP BY supplier_id, part_id LIMIT 2000")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MATCH (s:Supplier {id: r.supplier_id}) MATCH (p:Part {id: r.part_id}) MERGE (s)-[rel:SUPPLIES]->(p) SET rel.po_count=toInteger(r.po_count), rel.avg_delay_days=toFloat(r.avg_delay_days)")
    elif subgraph_type == "bom_dependency":
        rows = run_sql(f"SELECT top_parent_part_id AS part_id, top_parent_name AS name, top_parent_category AS category FROM {CATALOG}.{SCHEMA}.gold_bom_explosion UNION SELECT component_part_id, component_name, component_category FROM {CATALOG}.{SCHEMA}.gold_bom_explosion LIMIT 1000")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MERGE (p:Part {id: r.part_id}) SET p.name=r.name, p.category=r.category")
        rows = run_sql(f"SELECT top_parent_part_id AS parent_id, component_part_id AS child_id, cumulative_quantity, depth FROM {CATALOG}.{SCHEMA}.gold_bom_explosion LIMIT 5000")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MATCH (parent:Part {id: r.parent_id}) MATCH (child:Part {id: r.child_id}) MERGE (parent)-[rel:REQUIRES {depth: toInteger(r.depth)}]->(child) SET rel.cumulative_quantity=toFloat(r.cumulative_quantity)")
    elif subgraph_type == "shipment_route":
        # Actual schema: supplier_id → facility_id (no origin/destination facility pair)
        rows = run_sql(f"SELECT DISTINCT facility_id, facility_name AS name, destination_region AS region FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline LIMIT 200")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MERGE (f:Facility {id: r.facility_id}) SET f.name=r.name, f.region=r.region")
        rows = run_sql(f"SELECT shipment_id, supplier_id, facility_id, carrier, status, delay_days, disruption_severity, route_key FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline LIMIT 2000")
        total += neo4j_write_batch(rows, "UNWIND $rows AS r MERGE (shp:Shipment {id: r.shipment_id}) SET shp.carrier=r.carrier, shp.status=r.status, shp.delay_days=toInteger(r.delay_days), shp.disruption_severity=r.disruption_severity WITH shp, r MATCH (s:Supplier {id: r.supplier_id}) MATCH (f:Facility {id: r.facility_id}) MERGE (shp)-[:DEPARTS_FROM]->(s) MERGE (shp)-[:ARRIVES_AT]->(f) MERGE (s)-[rt:SHIPS_TO {carrier: r.carrier}]->(f) SET rt.route_key=r.route_key")

    _projected.add(subgraph_type)
    return f"Projected '{subgraph_type}': {total} nodes/rels"

# ── GDS projections ───────────────────────────────────────────────────────────
GDS_PROJECTIONS = {
    "bom_network": {
        "nodes": "Part",
        "rels": {"REQUIRES": {"properties": ["cumulative_quantity"]}},
        "description": "Part→Part BOM graph. Use for PageRank, Betweenness Centrality, WCC, Shortest Path.",
    },
    "supply_risk_network": {
        "nodes": ["Supplier", "Part"],
        "rels": {"SUPPLIES": {"properties": ["po_count", "avg_delay_days"]}},
        "description": "Supplier+Part bipartite graph. Use for Node Similarity, Community Detection, weighted Shortest Path.",
    },
    "facility_network": {
        "nodes": ["Supplier", "Facility"],
        "rels": {"SHIPS_TO": {"properties": []}},
        "description": "Supplier→Facility shipping graph. Use for Betweenness Centrality, Shortest Path, Community Detection.",
    },
}

def gds_projection_exists(name: str) -> bool:
    try:
        rows = neo4j_query(f"CALL gds.graph.exists('{name}') YIELD exists")
        return bool(rows and rows[0].get("exists"))
    except Exception as e:
        logger.warning("GDS exists check failed: %s", e)
        return False

GDS_PROJECT_CYPHER = {
    "bom_network": """
        CALL gds.graph.project(
            'bom_network',
            'Part',
            {REQUIRES: {type: 'REQUIRES', orientation: 'NATURAL', properties: ['cumulative_quantity']}}
        ) YIELD graphName, nodeCount, relationshipCount
    """,
    "supply_risk_network": """
        CALL gds.graph.project(
            'supply_risk_network',
            ['Supplier', 'Part'],
            {SUPPLIES: {type: 'SUPPLIES', orientation: 'NATURAL', properties: ['po_count', 'avg_delay_days']}}
        ) YIELD graphName, nodeCount, relationshipCount
    """,
    "facility_network": """
        CALL gds.graph.project(
            'facility_network',
            ['Supplier', 'Facility'],
            'SHIPS_TO'
        ) YIELD graphName, nodeCount, relationshipCount
    """,
}

# Neo4j subgraphs that must be loaded before each GDS projection
GDS_PREREQS = {
    "bom_network":          ["bom_dependency"],
    "supply_risk_network":  ["supplier_risk"],
    "facility_network":     ["shipment_route"],
}

def ensure_gds_projection(name: str) -> str:
    # Load underlying Neo4j data first
    for sg in GDS_PREREQS.get(name, []):
        msg = project_subgraph(sg)
        logger.info("[GDS prereq] %s", msg)

    if gds_projection_exists(name):
        return f"GDS projection '{name}' already exists"
    cypher = GDS_PROJECT_CYPHER.get(name)
    if not cypher:
        return f"No projection definition for '{name}'"
    try:
        rows = neo4j_query(cypher)
        row  = rows[0] if rows else {}
        return f"Created GDS projection '{name}': {row.get('nodeCount',0)} nodes, {row.get('relationshipCount',0)} rels"
    except Exception as e:
        return f"GDS projection '{name}' failed: {e}"

# ── Prompts ───────────────────────────────────────────────────────────────────
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
- shipment_route  → (:Facility)-[:SHIPS_TO]->(:Facility)
All required subgraphs are pre-projected before you start. Run Cypher queries directly."""

GRAPH_TOOLS = [{"name": "run_cypher", "description": "Run Cypher against Neo4j.", "input_schema": {"type": "object", "properties": {"cypher": {"type": "string"}, "description": {"type": "string"}}, "required": ["cypher", "description"]}}]

GDS_SYSTEM = """You are a Neo4j GDS (Graph Data Science) analyst for a supply chain network.
Three named in-memory graph projections are pre-created for you:

- "bom_network"          — Part nodes, REQUIRES relationships (weight: cumulative_quantity)
  Best for: gds.pageRank, gds.betweenness, gds.wcc, gds.shortestPath.dijkstra

- "supply_risk_network"  — Supplier + Part nodes, SUPPLIES relationships (weights: po_count, avg_delay_days)
  Best for: gds.nodeSimilarity, gds.louvain, gds.shortestPath.dijkstra (weight: avg_delay_days)

- "facility_network"     — Supplier + Facility nodes, SHIPS_TO relationships (Supplier→Facility)
  Best for: gds.betweenness, gds.shortestPath.dijkstra, gds.louvain

Node properties (use these exact names):
- Supplier: id, name, country, tier, reliability_score, risk_score, risk_tier
- Part:     id, name, category, is_critical
- Facility: id, name, region
- Shipment: id, carrier, status, delay_days, disruption_severity

GDS procedure patterns:
  CALL gds.pageRank.stream("<projection>", {maxIterations: 20, dampingFactor: 0.85})
       YIELD nodeId, score
  CALL gds.betweenness.stream("<projection>")
       YIELD nodeId, score
  CALL gds.louvain.stream("<projection>")
       YIELD nodeId, communityId
  CALL gds.nodeSimilarity.stream("<projection>")
       YIELD node1, node2, similarity
  CALL gds.wcc.stream("<projection>")
       YIELD nodeId, componentId
  CALL gds.shortestPath.dijkstra.stream("<projection>",
       {sourceNode: elementId(source), relationshipWeightProperty: "avg_delay_days"})
       YIELD index, sourceNode, targetNode, totalCost, nodeIds, path

Always resolve nodeId → node using gds.util.asNode(nodeId). Return names and IDs, not raw node IDs.
Limit streamed results to top 20 unless the question asks for all."""

GDS_TOOLS = [{"name": "run_gds_cypher", "description": "Run a GDS procedure or Cypher query against Neo4j.", "input_schema": {"type": "object", "properties": {"cypher": {"type": "string"}, "description": {"type": "string"}}, "required": ["cypher", "description"]}}]

# ── Agents ────────────────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def _text(content):
    return "\n".join(b.text for b in content if hasattr(b, "type") and b.type == "text").strip()

def _thinking(model: str, enabled: bool) -> dict:
    if enabled and model in OPUS_MODELS:
        return {"type": "adaptive"}
    return {"type": "disabled"}

def sql_agent(question: str, relevant_tables: list, model: str, thinking: bool) -> dict:
    messages = [{"role": "user", "content": question}]
    queries = []
    for _ in range(6):
        resp = claude.messages.create(model=model, max_tokens=4096, thinking=_thinking(model, thinking), system=SQL_SYSTEM, tools=SQL_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return {"answer": _text(resp.content), "queries": queries}
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                logger.info("[SQL] %s\n%s", b.input.get("description", ""), b.input.get("sql", ""))
                try:
                    rows = run_sql(b.input["sql"])
                    queries.append({"sql": b.input["sql"], "rows": rows})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:MAX_SQL_ROWS])})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
            messages.append({"role": "user", "content": results})
    return {"answer": "Could not complete within iteration limit.", "queries": queries}

def graph_agent(question: str, subgraph_type: str, model: str, thinking: bool) -> dict:
    required = {"supplier_risk": ["supplier_risk"], "bom_dependency": ["bom_dependency"], "shipment_route": ["shipment_route"], "full_network": ["supplier_risk", "bom_dependency", "shipment_route"]}
    for sg in required.get(subgraph_type, [subgraph_type]):
        msg = project_subgraph(sg)
        logger.info("[Neo4j] %s", msg)

    messages = [{"role": "user", "content": question}]
    queries = []
    for _ in range(8):
        resp = claude.messages.create(model=model, max_tokens=4096, thinking=_thinking(model, thinking), system=GRAPH_SYSTEM, tools=GRAPH_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return {"answer": _text(resp.content), "cypher_queries": queries, "subgraph_type": subgraph_type}
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                logger.info("[Cypher] %s\n%s", b.input.get("description", ""), b.input.get("cypher", ""))
                try:
                    rows = neo4j_query(b.input["cypher"])
                    queries.append({"cypher": b.input["cypher"], "rows": rows})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:50])})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
            messages.append({"role": "user", "content": results})
    return {"answer": "Could not complete within iteration limit.", "cypher_queries": queries, "subgraph_type": subgraph_type}

def gds_agent(question: str, projection: str, model: str, thinking: bool) -> dict:
    msg = ensure_gds_projection(projection)
    logger.info("[GDS] %s", msg)

    messages = [{"role": "user", "content": question}]
    queries  = []
    for _ in range(8):
        resp = claude.messages.create(model=model, max_tokens=4096, thinking=_thinking(model, thinking), system=GDS_SYSTEM, tools=GDS_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return {"answer": _text(resp.content), "gds_queries": queries, "projection": projection}
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                logger.info("[GDS Cypher] %s\n%s", b.input.get("description", ""), b.input.get("cypher", ""))
                try:
                    rows = neo4j_query(b.input["cypher"])
                    queries.append({"cypher": b.input["cypher"], "rows": rows})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:50])})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
            messages.append({"role": "user", "content": results})
    return {"answer": "Could not complete within iteration limit.", "gds_queries": queries, "projection": projection}

def route_and_answer(question: str, model: str = CLAUDE_MODEL, thinking: bool = False) -> tuple[str, str]:
    """Returns (answer_markdown, route_label)"""
    t0 = time.time()

    cached = cache_get(question)
    if cached:
        elapsed = time.time() - t0
        route   = cached.get("route", "?").upper()
        answer  = cached.get("result", {}).get("answer", "")
        logger.info("Total time: %.2fs (cache hit, route=%s)", elapsed, route)
        return answer, f"✓ {route} (cached) — {elapsed:.1f}s"

    t_router = time.time()
    resp = claude.messages.create(
        model=model, max_tokens=512,
        system=ROUTER_SYSTEM, tools=ROUTER_TOOLS, tool_choice={"type": "any"},
        messages=[{"role": "user", "content": question}],
    )
    logger.info("Router: %.2fs", time.time() - t_router)

    tool = next((b for b in resp.content if b.type == "tool_use"), None)
    if tool is None:
        route, tool_input = "sql", {"question": question, "relevant_tables": []}
    else:
        route      = {"route_to_sql": "sql", "route_to_graph": "graph", "route_to_gds": "gds"}.get(tool.name, "sql")
        tool_input = tool.input

    logger.info("Route → %s", route.upper())

    t_agent = time.time()
    if route == "sql":
        result = sql_agent(question, tool_input.get("relevant_tables", []), model, thinking)
    elif route == "gds":
        result = gds_agent(question, tool_input.get("projection", "bom_network"), model, thinking)
    else:
        result = graph_agent(question, tool_input.get("subgraph_type", "full_network"), model, thinking)
    logger.info("Agent (%s, thinking=%s): %.2fs", model, thinking, time.time() - t_agent)

    elapsed = time.time() - t0
    logger.info("Total time: %.2fs (route=%s)", elapsed, route.upper())

    payload = {"route": route, "result": result}
    cache_put(question, payload, route, tool_input.get("subgraph_type", ""))

    return result.get("answer", "No answer returned."), f"→ {route.upper()} — {elapsed:.1f}s"

# ── Gradio UI ─────────────────────────────────────────────────────────────────
EXAMPLE_QUESTIONS = [
    "Which suppliers have the highest risk scores?",
    "Show me all delayed purchase orders over 30 days old",
    "What are the top 10 most expensive BOM assemblies?",
    "Which shipments have High or Critical disruption severity?",
    "What is the stock status for critical parts?",
    "What parts are at risk if our highest-risk supplier fails?",
    "Which critical parts have only a single supplier?",
    "What assemblies would be affected if a Tier-1 supplier from China is disrupted?",
    "Show me the most depended-upon components in the BOM network",
    "Which carrier routes have the most disrupted shipments?",
    "Which parts are the biggest structural bottlenecks in the BOM? (GDS Betweenness Centrality)",
    "Rank parts by how many assemblies depend on them using PageRank (GDS)",
    "Which suppliers have the most similar part portfolios? (GDS Node Similarity)",
    "Detect supplier-part communities — which clusters are most exposed to risk? (GDS Louvain)",
    "Which facilities are the most critical routing hubs in the shipment network? (GDS Betweenness)",
    "Are there any isolated or disconnected parts in the BOM? (GDS WCC)",
]

def chat(message: str, history: list, model: str, thinking: bool) -> str:
    if not message.strip():
        return ""
    logger.info("Request — model=%s thinking=%s", model, thinking)
    answer, route_label = route_and_answer(message, model, thinking)
    return f"**[{route_label}]**\n\n{answer}"

CUSTOM_CSS = """
.input-container textarea {
    background-color: #f0f7ff !important;
    border: 2px solid #3b82f6 !important;
    border-radius: 10px !important;
    font-size: 15px !important;
    color: #1e293b !important;
}
.input-container textarea:focus {
    border-color: #1d4ed8 !important;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2) !important;
}
.input-container textarea::placeholder {
    color: #94a3b8 !important;
}
"""

def get_status() -> str:
    lines = ["### Neo4j AuraDB — Node Counts"]
    try:
        rows = neo4j_query("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC")
        if rows:
            lines.append("| Label | Count |")
            lines.append("|-------|-------|")
            for r in rows:
                lines.append(f"| {r.get('label','?')} | {r.get('count',0)} |")
        else:
            lines.append("_No nodes found._")
    except Exception as e:
        lines.append(f"_Error: {e}_")

    lines.append("\n### Neo4j AuraDB — Relationship Counts")
    try:
        rows = neo4j_query("MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC")
        if rows:
            lines.append("| Relationship | Count |")
            lines.append("|-------------|-------|")
            for r in rows:
                lines.append(f"| {r.get('rel_type','?')} | {r.get('count',0)} |")
        else:
            lines.append("_No relationships found._")
    except Exception as e:
        lines.append(f"_Error: {e}_")

    lines.append("\n### GDS Named Graph Projections")
    try:
        rows = neo4j_query("CALL gds.graph.list() YIELD graphName, nodeCount, relationshipCount, creationTime")
        if rows:
            lines.append("| Projection | Nodes | Relationships | Created |")
            lines.append("|-----------|-------|---------------|---------|")
            for r in rows:
                lines.append(f"| {r['graphName']} | {r['nodeCount']} | {r['relationshipCount']} | {str(r.get('creationTime',''))[:19]} |")
        else:
            lines.append("_No GDS projections in memory._")
    except Exception as e:
        lines.append(f"_Error: {e}_")

    return "\n".join(lines)

with gr.Blocks(theme=gr.themes.Soft(), css=CUSTOM_CSS) as demo:
    gr.Markdown("# Supply Chain Optimizer")
    gr.Markdown("Ask questions about supplier risk, part availability, shipment disruptions, and BOM dependencies. Routes to **SQL** (Delta Lake), **Graph** (Neo4j), or **GDS** (graph algorithms) automatically.")
    with gr.Tabs():
        with gr.Tab("💬 Chat"):
            gr.ChatInterface(
                fn=chat,
                title=None,
                description=None,
                examples=[[q, "claude-sonnet-4-6", False] for q in EXAMPLE_QUESTIONS],
                chatbot=gr.Chatbot(height=650),
                textbox=gr.Textbox(placeholder="Ask a supply chain question...", container=False, elem_classes=["input-container"]),
                additional_inputs=[
                    gr.Dropdown(
                        choices=CLAUDE_MODELS,
                        value="claude-sonnet-4-6",
                        label="Model",
                        info="Sonnet is faster for SQL; Opus is better for complex graph reasoning.",
                    ),
                    gr.Checkbox(
                        value=False,
                        label="Adaptive Thinking (Opus only)",
                        info="Enables extended thinking — slower but better for complex multi-hop queries.",
                    ),
                ],
                additional_inputs_accordion=gr.Accordion(label="⚙️ Model Settings", open=False),
            )
        with gr.Tab("📊 Status"):
            status_output = gr.Markdown()
            gr.Button("Refresh", variant="primary").click(fn=get_status, outputs=status_output)
            demo.load(fn=get_status, outputs=status_output)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 8000)))

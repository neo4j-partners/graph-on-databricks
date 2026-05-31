"""
Graph Agent — MLflow PyFunc Model (code-based logging)
Referenced by mlflow_agent_registration.py
"""
import base64
import json
import os
import time
from decimal import Decimal

import anthropic
import mlflow
import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from neo4j import GraphDatabase
from neo4j.graph import Node, Relationship, Path


class GraphAgentModel(mlflow.pyfunc.PythonModel):

    def load_context(self, context):
        cfg = context.model_config or {}
        self.catalog       = cfg.get("catalog",        "supplychain_optimizer")
        self.schema        = cfg.get("schema",         "supply_chain_medallion")
        self.model         = cfg.get("model",          "claude-sonnet-4-6")
        self.max_rows      = cfg.get("max_rows",       200)
        neo4j_uri          = cfg.get("neo4j_uri",      "neo4j+s://26bf512b.databases.neo4j.io")
        neo4j_username     = cfg.get("neo4j_username", "neo4j")
        self.neo4j_db      = cfg.get("neo4j_database", "neo4j")

        def _secret(scope, key, env):
            try:
                w   = WorkspaceClient()
                val = w.secrets.get_secret(scope=scope, key=key)
                return base64.b64decode(val.value).decode("utf-8")
            except Exception:
                return os.getenv(env, "")

        anthropic_key  = _secret("supply_chain", "anthropic_api_key", "ANTHROPIC_API_KEY")
        neo4j_password = _secret("supply_chain", "neo4j_password",    "NEO4J_PASSWORD")

        self.claude = anthropic.Anthropic(api_key=anthropic_key)
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password))
        self.dbx    = WorkspaceClient()
        self._warehouse_id = None
        self._projected: set = set()

        self.GRAPH_SYSTEM = """You are a Neo4j graph analyst for a supply chain network.
Subgraphs and their relationships:
- supplier_risk   → (:Supplier)-[:SUPPLIES]->(:Part)
- bom_dependency  → (:Part)-[:REQUIRES {depth}]->(:Part)
- shipment_route  → (:Supplier)-[:SHIPS_TO]->(:Facility)
All required subgraphs are pre-projected before you start. Run Cypher queries directly.
Node properties — Supplier: id, name, country, tier, risk_score, risk_tier | Part: id, name, category, is_critical | Facility: id, name, region"""

        self.GRAPH_TOOLS = [{
            "name": "run_cypher",
            "description": "Run Cypher against Neo4j.",
            "input_schema": {"type": "object", "properties": {"cypher": {"type": "string"}, "description": {"type": "string"}}, "required": ["cypher", "description"]},
        }]

    def _get_warehouse(self):
        if self._warehouse_id:
            return self._warehouse_id
        for wh in self.dbx.warehouses.list():
            if wh.state and wh.state.value in ("RUNNING", "STARTING"):
                self._warehouse_id = wh.id
                return self._warehouse_id
        self._warehouse_id = list(self.dbx.warehouses.list())[0].id
        return self._warehouse_id

    def _run_sql(self, query):
        stmt = self.dbx.statement_execution.execute_statement(warehouse_id=self._get_warehouse(), statement=query)
        while stmt.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(0.5)
            stmt = self.dbx.statement_execution.get_statement(stmt.statement_id)
        if stmt.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"SQL failed: {stmt.status.error}")
        if not stmt.result or not stmt.result.data_array:
            return []
        cols = [c.name for c in stmt.manifest.schema.columns]
        def _safe(v): return float(v) if isinstance(v, Decimal) else v
        return [{k: _safe(v) for k, v in zip(cols, row)} for row in stmt.result.data_array]

    def _neo4j_query(self, cypher, params=None):
        def _convert(val):
            if isinstance(val, Node):          return {"_labels": list(val.labels), **dict(val)}
            elif isinstance(val, Relationship): return {"_type": val.type, **dict(val)}
            elif isinstance(val, Path):         return [_convert(n) for n in val.nodes]
            elif isinstance(val, list):         return [_convert(v) for v in val]
            return val
        with self.driver.session(database=self.neo4j_db) as s:
            return [{k: _convert(v) for k, v in dict(r).items()} for r in s.run(cypher, params or {})]

    def _write_batch(self, rows, cypher, batch=500):
        if not rows: return 0
        total = 0
        with self.driver.session(database=self.neo4j_db) as s:
            for i in range(0, len(rows), batch):
                s.run(cypher, {"rows": rows[i:i+batch]})
                total += len(rows[i:i+batch])
        return total

    def _already_projected(self, sg):
        checks = {
            "supplier_risk":  "MATCH ()-[:SUPPLIES]->() RETURN count(*) AS n",
            "bom_dependency": "MATCH ()-[:REQUIRES]->() RETURN count(*) AS n",
            "shipment_route": "MATCH ()-[:SHIPS_TO]->()  RETURN count(*) AS n",
        }
        if sg == "full_network":
            return all(self._already_projected(t) for t in ["supplier_risk", "bom_dependency", "shipment_route"])
        cypher = checks.get(sg)
        if not cypher: return False
        rows = self._neo4j_query(cypher)
        return bool(rows and rows[0].get("n", 0) > 0)

    def _project(self, sg):
        if sg in self._projected or self._already_projected(sg):
            self._projected.add(sg)
            return
        c, s = self.catalog, self.schema
        if sg == "supplier_risk":
            rows = self._run_sql(f"SELECT DISTINCT supplier_id, supplier_name AS name, country, tier, reliability_score, risk_score, risk_tier FROM {c}.{s}.gold_supplier_risk LIMIT 500")
            self._write_batch(rows, "UNWIND $rows AS r MERGE (s:Supplier {id: r.supplier_id}) SET s.name=r.name, s.country=r.country, s.tier=r.tier, s.risk_score=toFloat(r.risk_score), s.risk_tier=r.risk_tier")
            rows = self._run_sql(f"SELECT DISTINCT part_id, part_name AS name, category, is_critical FROM {c}.{s}.gold_part_availability LIMIT 500")
            self._write_batch(rows, "UNWIND $rows AS r MERGE (p:Part {id: r.part_id}) SET p.name=r.name, p.category=r.category, p.is_critical=r.is_critical")
            rows = self._run_sql(f"SELECT supplier_id, part_id, COUNT(*) AS po_count, AVG(aging_days) AS avg_delay_days FROM {c}.{s}.gold_active_purchase_orders GROUP BY supplier_id, part_id LIMIT 2000")
            self._write_batch(rows, "UNWIND $rows AS r MATCH (s:Supplier {id: r.supplier_id}) MATCH (p:Part {id: r.part_id}) MERGE (s)-[rel:SUPPLIES]->(p) SET rel.po_count=toInteger(r.po_count), rel.avg_delay_days=toFloat(r.avg_delay_days)")
        elif sg == "bom_dependency":
            rows = self._run_sql(f"SELECT top_parent_part_id AS part_id, top_parent_name AS name, top_parent_category AS category FROM {c}.{s}.gold_bom_explosion UNION SELECT component_part_id, component_name, component_category FROM {c}.{s}.gold_bom_explosion LIMIT 1000")
            self._write_batch(rows, "UNWIND $rows AS r MERGE (p:Part {id: r.part_id}) SET p.name=r.name, p.category=r.category")
            rows = self._run_sql(f"SELECT top_parent_part_id AS parent_id, component_part_id AS child_id, cumulative_quantity, depth FROM {c}.{s}.gold_bom_explosion LIMIT 5000")
            self._write_batch(rows, "UNWIND $rows AS r MATCH (parent:Part {id: r.parent_id}) MATCH (child:Part {id: r.child_id}) MERGE (parent)-[rel:REQUIRES {depth: toInteger(r.depth)}]->(child) SET rel.cumulative_quantity=toFloat(r.cumulative_quantity)")
        elif sg == "shipment_route":
            rows = self._run_sql(f"SELECT DISTINCT facility_id, facility_name AS name, destination_region AS region FROM {c}.{s}.gold_shipment_pipeline LIMIT 200")
            self._write_batch(rows, "UNWIND $rows AS r MERGE (f:Facility {id: r.facility_id}) SET f.name=r.name, f.region=r.region")
            rows = self._run_sql(f"SELECT shipment_id, supplier_id, facility_id, carrier, status, delay_days, disruption_severity, route_key FROM {c}.{s}.gold_shipment_pipeline LIMIT 2000")
            self._write_batch(rows, "UNWIND $rows AS r MERGE (shp:Shipment {id: r.shipment_id}) SET shp.carrier=r.carrier, shp.status=r.status, shp.delay_days=toInteger(r.delay_days), shp.disruption_severity=r.disruption_severity WITH shp, r MATCH (sup:Supplier {id: r.supplier_id}) MATCH (f:Facility {id: r.facility_id}) MERGE (shp)-[:DEPARTS_FROM]->(sup) MERGE (shp)-[:ARRIVES_AT]->(f) MERGE (sup)-[rt:SHIPS_TO {carrier: r.carrier}]->(f) SET rt.route_key=r.route_key")
        self._projected.add(sg)

    def predict(self, context, model_input):
        if isinstance(model_input, pd.DataFrame):
            row       = model_input.iloc[0]
            messages  = row["messages"]
            subgraph_type = row.get("subgraph_type", "full_network")
        else:
            messages      = model_input.get("messages", [])
            subgraph_type = model_input.get("subgraph_type", "full_network")

        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

        required = {
            "supplier_risk":  ["supplier_risk"],
            "bom_dependency": ["bom_dependency"],
            "shipment_route": ["shipment_route"],
            "full_network":   ["supplier_risk", "bom_dependency", "shipment_route"],
        }
        for sg in required.get(subgraph_type, [subgraph_type]):
            self._project(sg)

        msgs   = [{"role": "user", "content": question}]
        answer = "Could not complete within iteration limit."
        for _ in range(8):
            resp = self.claude.messages.create(
                model=self.model, max_tokens=4096, thinking={"type": "disabled"},
                system=self.GRAPH_SYSTEM, tools=self.GRAPH_TOOLS, messages=msgs,
            )
            msgs.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "end_turn":
                answer = "\n".join(b.text for b in resp.content if hasattr(b, "type") and b.type == "text").strip()
                break
            if resp.stop_reason == "tool_use":
                results = []
                for b in resp.content:
                    if b.type != "tool_use": continue
                    try:
                        rows = self._neo4j_query(b.input["cypher"])
                        results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(rows[:50])})
                    except Exception as e:
                        results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})
                msgs.append({"role": "user", "content": results})

        return {"choices": [{"message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}]}


mlflow.models.set_model(GraphAgentModel())

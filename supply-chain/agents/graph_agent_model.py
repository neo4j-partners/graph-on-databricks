"""
Graph Agent — MLflow PyFunc Model (slim version)
Assumes Neo4j graph is already populated by the Gradio app / pipeline projection job.
Credentials read from env vars injected via serving endpoint configuration.
"""
import json
import os

import anthropic
import mlflow
import pandas as pd
from neo4j import GraphDatabase
from neo4j.graph import Node, Relationship, Path


class GraphAgentModel(mlflow.pyfunc.PythonModel):

    def load_context(self, context):
        cfg = context.model_config or {}
        self.model    = cfg.get("model",          "claude-sonnet-4-6")
        neo4j_uri     = cfg.get("neo4j_uri",      "neo4j+s://26bf512b.databases.neo4j.io")
        neo4j_username = cfg.get("neo4j_username", "neo4j")
        self.neo4j_db = cfg.get("neo4j_database", "neo4j")

        # Credentials from env vars injected via serving endpoint environment_vars config
        anthropic_key  = os.getenv("ANTHROPIC_API_KEY", "")
        neo4j_password = os.getenv("NEO4J_PASSWORD",    "")

        self.claude = anthropic.Anthropic(api_key=anthropic_key)
        self._neo4j_uri  = neo4j_uri
        self._neo4j_auth = (neo4j_username, neo4j_password)
        self.driver = GraphDatabase.driver(
            neo4j_uri,
            auth=self._neo4j_auth,
            max_connection_lifetime=200,   # recycle connections before AuraDB drops them (~300s idle)
            keep_alive=True,
        )

        self.GRAPH_SYSTEM = """You are a Neo4j graph analyst for a supply chain network.
The graph is already populated — run Cypher queries directly, no projection needed.

Graph schema:
- (:Supplier)-[:SUPPLIES {po_count, avg_delay_days}]->(:Part)
- (:Part)-[:REQUIRES {depth, cumulative_quantity}]->(:Part)
- (:Supplier)-[:SHIPS_TO {carrier, route_key}]->(:Facility)
- (:Shipment)-[:DEPARTS_FROM]->(:Supplier)
- (:Shipment)-[:ARRIVES_AT]->(:Facility)

Node properties (use EXACTLY these names):
- Supplier: id, name, country, tier, risk_score, risk_tier
- Part: id, name, category, is_critical
- Facility: id, name, region"""

        self.GRAPH_TOOLS = [{
            "name": "run_cypher",
            "description": "Run Cypher against Neo4j.",
            "input_schema": {"type": "object", "properties": {"cypher": {"type": "string"}, "description": {"type": "string"}}, "required": ["cypher", "description"]},
        }]

    def _neo4j_query(self, cypher, params=None):
        def _convert(val):
            if isinstance(val, Node):          return {"_labels": list(val.labels), **dict(val)}
            elif isinstance(val, Relationship): return {"_type": val.type, **dict(val)}
            elif isinstance(val, Path):         return [_convert(n) for n in val.nodes]
            elif isinstance(val, list):         return [_convert(v) for v in val]
            return val
        # Retry once on connection failure — handles AuraDB idle timeout reconnect
        for attempt in range(2):
            try:
                with self.driver.session(database=self.neo4j_db) as s:
                    return [{k: _convert(v) for k, v in dict(r).items()} for r in s.run(cypher, params or {})]
            except Exception as e:
                if attempt == 0 and ("defunct" in str(e).lower() or "no data" in str(e).lower()):
                    self.driver.close()
                    self.driver = GraphDatabase.driver(
                        self._neo4j_uri, auth=self._neo4j_auth,
                        max_connection_lifetime=200, keep_alive=True,
                    )
                    continue
                raise

    def predict(self, context, model_input):
        if isinstance(model_input, pd.DataFrame):
            messages = model_input.iloc[0]["messages"]
        else:
            messages = model_input.get("messages", [])

        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

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

        # FIX: ai_query() requires "predictions" or "outputs" field — not OpenAI's "choices" format.
        # Strip non-ASCII (emojis, flags) AND ASCII control chars (0x00-0x1f except \n\t) that break
        # ai_query JSON parsing. Also truncate to avoid payload size limits.
        answer = answer.encode("ascii", errors="ignore").decode("ascii")
        answer = "".join(c for c in answer if c >= " " or c in "\n\t")
        answer = answer[:6000]
        return {"predictions": [answer]}


mlflow.models.set_model(GraphAgentModel())

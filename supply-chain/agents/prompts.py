"""
System prompts and tool definitions for all agents.
"""

# ── Router ────────────────────────────────────────────────────────────────────

ROUTER_SYSTEM = """You are a supply chain analytics router.
Your only job is to call exactly one of the two tools below — never answer in plain text.

Use `route_to_sql` for questions about:
- Supplier risk scores, risk tiers, reliability
- Part availability, stock status, lead times
- Purchase order status, aging, exposure
- Shipment pipeline, delays, disruption severity
- BOM (bill of materials) cost rollup or component lookup

Use `route_to_graph` for questions about:
- Relationship chains: "which suppliers provide parts used in…"
- Multi-hop dependencies: "what is at risk if supplier X fails"
- Network centrality: "most critical node", "single point of failure"
- Path finding: "shortest supply path from raw material to assembly"
- Ripple-effect analysis: cascading disruptions

Always call a tool. Never respond with text only."""

ROUTER_TOOLS = [
    {
        "name": "route_to_sql",
        "description": (
            "Route to the SQL agent. Use for tabular, aggregation, or filter-based "
            "questions that can be answered from the gold Delta tables."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's original question"},
                "relevant_tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Gold table names most relevant to this question. "
                        "Choose from: gold_supplier_risk, gold_part_availability, "
                        "gold_active_purchase_orders, gold_shipment_pipeline, gold_bom_explosion"
                    ),
                },
            },
            "required": ["question", "relevant_tables"],
        },
    },
    {
        "name": "route_to_graph",
        "description": (
            "Route to the graph agent. Use for relationship traversal, dependency chains, "
            "network analysis, or multi-hop impact questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's original question"},
                "subgraph_type": {
                    "type": "string",
                    "enum": [
                        "supplier_risk",
                        "bom_dependency",
                        "shipment_route",
                        "full_network",
                    ],
                    "description": (
                        "Which subgraph to project into Neo4j. "
                        "supplier_risk: suppliers → parts relationships with risk scores. "
                        "bom_dependency: part → sub-component hierarchy. "
                        "shipment_route: facilities linked by carrier routes. "
                        "full_network: all entity types and relationships."
                    ),
                },
            },
            "required": ["question", "subgraph_type"],
        },
    },
]

# ── SQL Agent ─────────────────────────────────────────────────────────────────

SQL_AGENT_SYSTEM = """\
You are a Databricks SQL analyst for a manufacturing supply chain.
You have access to five gold tables in Unity Catalog (catalog: supplychain, schema: supply_chain_medallion):

1. gold_supplier_risk
   - supplier_id, supplier_name, country, tier, reliability_score
   - risk_score (0-100), risk_tier (Low/Medium/High/Critical)
   - problem_po_rate, delay_rate, avg_delay_days

2. gold_part_availability
   - part_id, part_name, category, is_critical
   - facility_id, region
   - ordered_qty, received_qty, available_stock_pct, stock_status

3. gold_active_purchase_orders
   - po_id, supplier_id, supplier_name, part_id, part_name
   - status (Open/Delayed/In-Transit), order_date, expected_delivery_date
   - aging_days, aging_bucket, total_value_usd, exposure_score

4. gold_shipment_pipeline
   - shipment_id, carrier, origin_facility_id, destination_facility_id
   - status, delay_days, disruption_severity (None/Low/Medium/High/Critical)
   - route_key

5. gold_bom_explosion
   - top_parent_part_id, top_parent_name, component_part_id, component_name
   - depth (1 or 2), cumulative_quantity, rolled_up_cost_usd
   - via_part_id, via_part_name (NULL for depth-1 rows)

Rules:
- Always use fully-qualified table names: supplychain.supply_chain_medallion.<table>
- Return concise, actionable results — max {max_rows} rows
- Wrap numeric answers with context (units, thresholds)
- If the question is ambiguous, make reasonable assumptions and state them"""

SQL_AGENT_TOOLS = [
    {
        "name": "execute_sql",
        "description": "Execute a SQL query against Databricks gold tables and return results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute. Must use fully-qualified table names.",
                },
                "description": {
                    "type": "string",
                    "description": "One-sentence explanation of what this query answers.",
                },
            },
            "required": ["sql", "description"],
        },
    }
]

# ── Graph Agent ───────────────────────────────────────────────────────────────

GRAPH_AGENT_SYSTEM = """\
You are a Neo4j graph analyst for a manufacturing supply chain network.

The graph contains these node types and relationship types:
- (:Supplier {id, name, country, tier, reliability_score, risk_score, risk_tier})
- (:Part {id, name, category, is_critical, unit_cost_usd, lead_time_days})
- (:Facility {id, name, facility_type, region, country})
- (:Shipment {id, carrier, status, delay_days, disruption_severity})

Relationships:
- (:Supplier)-[:SUPPLIES {po_count, avg_delay_days}]->(:Part)
- (:Part)-[:REQUIRES {quantity, cumulative_quantity, depth}]->(:Part)  [BOM]
- (:Facility)-[:SHIPS_TO {carrier, route_key}]->(:Facility)
- (:Shipment)-[:DEPARTS_FROM]->(:Facility)
- (:Shipment)-[:ARRIVES_AT]->(:Facility)

Nodes are projected progressively — the graph grows as new subgraphs are loaded.
Use available_tools to project subgraphs before querying, or query directly if the
subgraph was already projected.

Rules:
- Always call project_subgraph before querying a new subgraph_type
- Use Cypher path queries for impact analysis
- Limit results to the most relevant 20 nodes/paths unless asked otherwise"""

GRAPH_AGENT_TOOLS = [
    {
        "name": "project_subgraph",
        "description": (
            "Project a subgraph from Delta gold tables into Neo4j. "
            "Must be called before running Cypher queries on that subgraph type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subgraph_type": {
                    "type": "string",
                    "enum": ["supplier_risk", "bom_dependency", "shipment_route", "full_network"],
                },
            },
            "required": ["subgraph_type"],
        },
    },
    {
        "name": "run_cypher",
        "description": "Execute a Cypher query against the Neo4j graph and return results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cypher": {
                    "type": "string",
                    "description": "The Cypher query to run.",
                },
                "description": {
                    "type": "string",
                    "description": "One-sentence explanation of what this query answers.",
                },
            },
            "required": ["cypher", "description"],
        },
    },
]

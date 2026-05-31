"""
Neo4j AuraDB connector + progressive subgraph projector.

Progressive projection pattern:
  Each subgraph_type reads from Databricks gold Delta tables via the
  Databricks SDK (SQL Statement Execution API) and writes nodes/relationships
  into Neo4j using batched MERGE statements.

  Subgraphs accumulate — projecting "supplier_risk" then "bom_dependency"
  leaves both sets of nodes/rels in the graph.
"""
import json
import logging
import time
from typing import Any

from neo4j import GraphDatabase
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from agents.config import (
    NEO4J_URI,
    NEO4J_USERNAME,
    NEO4J_PASSWORD,
    NEO4J_DATABASE,
    CATALOG,
    SCHEMA,
    MAX_SQL_ROWS,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


class Neo4jConnector:
    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        )
        self._dbx = WorkspaceClient()
        self._warehouse_id: str | None = None
        self._ensure_constraints()

    def close(self) -> None:
        self._driver.close()

    # ── Public API ─────────────────────────────────────────────────────────────

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Execute a read Cypher query and return results as list of dicts."""
        with self._driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(cypher, params or {})
            return [dict(record) for record in result]

    def write(self, cypher: str, params: dict | None = None) -> None:
        """Execute a write Cypher statement."""
        with self._driver.session(database=NEO4J_DATABASE) as session:
            session.run(cypher, params or {})

    def project_subgraph(self, subgraph_type: str) -> int:
        """
        Project a named subgraph from Delta gold tables into Neo4j.
        Returns total number of nodes + relationships created/merged.
        """
        projectors = {
            "supplier_risk": self._project_supplier_risk,
            "bom_dependency": self._project_bom_dependency,
            "shipment_route": self._project_shipment_route,
            "full_network": self._project_full_network,
        }
        projector = projectors.get(subgraph_type)
        if projector is None:
            raise ValueError(f"Unknown subgraph_type: '{subgraph_type}'")
        return projector()

    # ── Subgraph projectors ───────────────────────────────────────────────────

    def _project_supplier_risk(self) -> int:
        """
        Project: (:Supplier)-[:SUPPLIES]->(:Part)
        Source: gold_supplier_risk JOIN gold_active_purchase_orders
        """
        total = 0

        # 1. Merge Supplier nodes
        sql_suppliers = f"""
            SELECT DISTINCT
                supplier_id, supplier_name AS name, country, tier,
                reliability_score, risk_score, risk_tier
            FROM {CATALOG}.{SCHEMA}.gold_supplier_risk
            LIMIT 500
        """
        rows = self._sql(sql_suppliers)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MERGE (s:Supplier {id: r.supplier_id})
            SET s.name             = r.name,
                s.country          = r.country,
                s.tier             = r.tier,
                s.reliability_score = toFloat(r.reliability_score),
                s.risk_score       = toFloat(r.risk_score),
                s.risk_tier        = r.risk_tier
            """,
        )

        # 2. Merge Part nodes (from availability table for cross-ref)
        sql_parts = f"""
            SELECT DISTINCT part_id, part_name AS name, category, is_critical
            FROM {CATALOG}.{SCHEMA}.gold_part_availability
            LIMIT 500
        """
        rows = self._sql(sql_parts)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MERGE (p:Part {id: r.part_id})
            SET p.name        = r.name,
                p.category    = r.category,
                p.is_critical = r.is_critical
            """,
        )

        # 3. Merge SUPPLIES relationships from active POs
        sql_rels = f"""
            SELECT
                apo.supplier_id,
                apo.part_id,
                COUNT(*)                          AS po_count,
                AVG(apo.aging_days)               AS avg_delay_days
            FROM {CATALOG}.{SCHEMA}.gold_active_purchase_orders apo
            GROUP BY apo.supplier_id, apo.part_id
            LIMIT 2000
        """
        rows = self._sql(sql_rels)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MATCH (s:Supplier {id: r.supplier_id})
            MATCH (p:Part {id: r.part_id})
            MERGE (s)-[rel:SUPPLIES]->(p)
            SET rel.po_count       = toInteger(r.po_count),
                rel.avg_delay_days = toFloat(r.avg_delay_days)
            """,
        )

        return total

    def _project_bom_dependency(self) -> int:
        """
        Project: (:Part)-[:REQUIRES {quantity, depth}]->(:Part)
        Source: gold_bom_explosion
        """
        total = 0

        # Ensure Part nodes exist (merge from BOM)
        sql_parts = f"""
            SELECT DISTINCT
                top_parent_part_id AS part_id,
                top_parent_name    AS name,
                top_parent_category AS category
            FROM {CATALOG}.{SCHEMA}.gold_bom_explosion
            UNION
            SELECT DISTINCT
                component_part_id  AS part_id,
                component_name     AS name,
                component_category AS category
            FROM {CATALOG}.{SCHEMA}.gold_bom_explosion
            LIMIT 1000
        """
        rows = self._sql(sql_parts)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MERGE (p:Part {id: r.part_id})
            SET p.name     = r.name,
                p.category = r.category
            """,
        )

        # Merge REQUIRES relationships
        sql_rels = f"""
            SELECT
                top_parent_part_id AS parent_id,
                component_part_id  AS child_id,
                cumulative_quantity,
                depth
            FROM {CATALOG}.{SCHEMA}.gold_bom_explosion
            LIMIT 5000
        """
        rows = self._sql(sql_rels)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MATCH (parent:Part {id: r.parent_id})
            MATCH (child:Part  {id: r.child_id})
            MERGE (parent)-[rel:REQUIRES {depth: toInteger(r.depth)}]->(child)
            SET rel.cumulative_quantity = toFloat(r.cumulative_quantity)
            """,
        )

        return total

    def _project_shipment_route(self) -> int:
        """
        Project: (:Facility)-[:SHIPS_TO]->(:Facility)
                 (:Shipment)-[:DEPARTS_FROM/ARRIVES_AT]->(:Facility)
        Source: gold_shipment_pipeline
        """
        total = 0

        # Facilities
        sql_fac = f"""
            SELECT DISTINCT origin_facility_id AS facility_id FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline
            UNION
            SELECT DISTINCT destination_facility_id FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline
            LIMIT 200
        """
        rows = self._sql(sql_fac)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MERGE (f:Facility {id: r.facility_id})
            """,
        )

        # Shipment nodes
        sql_shp = f"""
            SELECT
                shipment_id, carrier, status,
                delay_days, disruption_severity,
                origin_facility_id, destination_facility_id,
                route_key
            FROM {CATALOG}.{SCHEMA}.gold_shipment_pipeline
            LIMIT 2000
        """
        rows = self._sql(sql_shp)
        total += self._batch_write(
            rows,
            """
            UNWIND $rows AS r
            MERGE (shp:Shipment {id: r.shipment_id})
            SET shp.carrier              = r.carrier,
                shp.status               = r.status,
                shp.delay_days           = toInteger(r.delay_days),
                shp.disruption_severity  = r.disruption_severity
            WITH shp, r
            MATCH (o:Facility {id: r.origin_facility_id})
            MATCH (d:Facility {id: r.destination_facility_id})
            MERGE (shp)-[:DEPARTS_FROM]->(o)
            MERGE (shp)-[:ARRIVES_AT]->(d)
            MERGE (o)-[rt:SHIPS_TO {carrier: r.carrier}]->(d)
            SET rt.route_key = r.route_key
            """,
        )

        return total

    def _project_full_network(self) -> int:
        """Project all subgraphs."""
        total = 0
        total += self._project_supplier_risk()
        total += self._project_bom_dependency()
        total += self._project_shipment_route()
        return total

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ensure_constraints(self) -> None:
        constraints = [
            "CREATE CONSTRAINT supplier_id IF NOT EXISTS FOR (s:Supplier) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT part_id     IF NOT EXISTS FOR (p:Part)     REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT facility_id IF NOT EXISTS FOR (f:Facility) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT shipment_id IF NOT EXISTS FOR (sh:Shipment) REQUIRE sh.id IS UNIQUE",
        ]
        with self._driver.session(database=NEO4J_DATABASE) as session:
            for c in constraints:
                try:
                    session.run(c)
                except Exception as exc:
                    logger.debug("Constraint note: %s", exc)

    def _get_warehouse_id(self) -> str:
        if self._warehouse_id:
            return self._warehouse_id
        for wh in self._dbx.warehouses.list():
            if wh.state and wh.state.value in ("RUNNING", "STARTING"):
                self._warehouse_id = wh.id
                return self._warehouse_id
        warehouses = list(self._dbx.warehouses.list())
        if not warehouses:
            raise RuntimeError("No SQL warehouses available.")
        self._warehouse_id = warehouses[0].id
        return self._warehouse_id

    def _sql(self, sql: str) -> list[dict]:
        """Execute SQL via Databricks and return list of dicts."""
        stmt = self._dbx.statement_execution.execute_statement(
            warehouse_id=self._get_warehouse_id(),
            statement=sql,
        )
        while stmt.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(0.5)
            stmt = self._dbx.statement_execution.get_statement(stmt.statement_id)

        if stmt.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(
                f"SQL failed [{stmt.status.state}]: {stmt.status.error}"
            )

        if not stmt.result or not stmt.result.data_array:
            return []

        columns = [col.name for col in stmt.manifest.schema.columns]
        return [dict(zip(columns, row)) for row in stmt.result.data_array]

    def _batch_write(self, rows: list[dict], cypher: str) -> int:
        """Write rows to Neo4j in batches; return row count processed."""
        if not rows:
            return 0
        total = 0
        with self._driver.session(database=NEO4J_DATABASE) as session:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                session.run(cypher, {"rows": batch})
                total += len(batch)
        return total

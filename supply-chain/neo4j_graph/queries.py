"""
Pre-built Cypher query library for common supply chain graph questions.

Used by the graph agent as starting points; Claude may modify them
or write new ones via the run_cypher tool.
"""


class CypherQueries:
    """Namespace for named Cypher templates."""

    # ── Supplier impact ───────────────────────────────────────────────────────

    SUPPLIER_IMPACT = """
    // What parts are at risk if a given supplier fails?
    MATCH (s:Supplier {id: $supplier_id})-[:SUPPLIES]->(p:Part)
    RETURN s.id AS supplier_id, s.name AS supplier_name,
           p.id AS part_id, p.name AS part_name,
           p.is_critical, s.risk_score
    ORDER BY p.is_critical DESC, s.risk_score DESC
    """

    # ── Critical supplier ranking ─────────────────────────────────────────────

    HIGH_RISK_SUPPLIERS = """
    // Suppliers with risk_tier Critical or High, ranked by risk_score
    MATCH (s:Supplier)
    WHERE s.risk_tier IN ['Critical', 'High']
    OPTIONAL MATCH (s)-[:SUPPLIES]->(p:Part)
    RETURN s.id, s.name, s.tier, s.country, s.risk_score, s.risk_tier,
           COUNT(p) AS parts_supplied
    ORDER BY s.risk_score DESC
    LIMIT 20
    """

    # ── BOM dependency chain ──────────────────────────────────────────────────

    BOM_UPSTREAM = """
    // All components (up to 3 hops) needed to build a given assembly
    MATCH path = (parent:Part {id: $part_id})-[:REQUIRES*1..3]->(component:Part)
    RETURN parent.id, parent.name,
           component.id, component.name, component.category,
           component.is_critical,
           length(path) AS depth
    ORDER BY depth, component.is_critical DESC
    """

    BOM_DOWNSTREAM = """
    // Which assemblies use a given component (reverse BOM)
    MATCH path = (assembly:Part)-[:REQUIRES*1..3]->(comp:Part {id: $part_id})
    RETURN assembly.id, assembly.name, assembly.category,
           length(path) AS depth
    ORDER BY depth
    LIMIT 30
    """

    # ── Network centrality proxy ───────────────────────────────────────────────

    MOST_CRITICAL_PARTS = """
    // Parts with the highest in-degree (most assemblies depend on them)
    MATCH (p:Part)<-[:REQUIRES]-(dependent:Part)
    WITH p, COUNT(dependent) AS dependents
    WHERE p.is_critical = true OR dependents > 3
    RETURN p.id, p.name, p.category, p.is_critical, dependents
    ORDER BY dependents DESC
    LIMIT 20
    """

    SINGLE_SOURCE_PARTS = """
    // Critical parts supplied by only ONE supplier (single point of failure)
    MATCH (s:Supplier)-[:SUPPLIES]->(p:Part)
    WHERE p.is_critical = true
    WITH p, COUNT(s) AS supplier_count, COLLECT(s.name) AS suppliers
    WHERE supplier_count = 1
    RETURN p.id, p.name, p.category, supplier_count, suppliers
    ORDER BY p.name
    """

    # ── Shipment disruptions ──────────────────────────────────────────────────

    DISRUPTED_ROUTES = """
    // Routes (facility pairs) with the most disrupted shipments
    MATCH (o:Facility)<-[:DEPARTS_FROM]-(shp:Shipment)-[:ARRIVES_AT]->(d:Facility)
    WHERE shp.disruption_severity IN ['High', 'Critical']
    WITH o, d, COUNT(shp) AS disrupted_count, AVG(shp.delay_days) AS avg_delay
    RETURN o.id AS origin, d.id AS destination,
           disrupted_count, round(avg_delay, 1) AS avg_delay_days
    ORDER BY disrupted_count DESC
    LIMIT 15
    """

    # ── Multi-hop: "What is at risk if country X is cut off?" ─────────────────

    COUNTRY_RISK_EXPOSURE = """
    // Parts and assemblies at risk if all suppliers from a country fail
    MATCH (s:Supplier {country: $country})-[:SUPPLIES]->(p:Part)
    OPTIONAL MATCH (assembly:Part)-[:REQUIRES*1..2]->(p)
    RETURN s.name AS supplier_name, s.risk_tier,
           p.id AS affected_part_id, p.name AS affected_part,
           p.is_critical,
           COLLECT(DISTINCT assembly.name) AS affected_assemblies
    ORDER BY p.is_critical DESC, s.risk_tier
    """

    # ── Shortest supply path ──────────────────────────────────────────────────

    SUPPLY_PATH = """
    // Shortest relationship path from a supplier to a target assembly
    MATCH path = shortestPath(
        (s:Supplier {id: $supplier_id})-[*..6]-(target:Part {id: $part_id})
    )
    RETURN [node IN nodes(path) | labels(node)[0] + ': ' + coalesce(node.name, node.id)]
           AS path_steps,
           length(path) AS hops
    """

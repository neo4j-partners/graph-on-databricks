"""Shared neo4j-viz rendering for the Lakehouse and Operational-graph map halves.

Both map halves query the same NeoCarta semantic store and share one rendering
function and one trace control: nodes and relationships belonging to the
traced entity stay full-size and coloured by label, everything else in the
map dims. Writing this twice for the two data pages is how they would drift
apart, so `render_map` is parameterised entirely by query, hidden labels/
relationship types, and a trace predicate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import streamlit.components.v1 as components
from neo4j import Driver, RoutingControl
from neo4j_viz import Relationship
from neo4j_viz.neo4j import from_neo4j

TRACED_SIZE = 42
DIMMED_SIZE = 14
DIMMED_COLOR = "#C7C7C7"
DEFAULT_HEIGHT = 480

LAKEHOUSE_MAP_QUERY = """
MATCH (d:Database {name: $catalog})-[:HAS_SCHEMA]->(s:Schema {name: $schema})-[:HAS_TABLE]->(t:Table)
OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
OPTIONAL MATCH (c)-[ref:REFERENCES]->(c2:Column)
RETURN d, s, t, c, ref, c2
"""

LAKEHOUSE_TABLE_REFERENCES_QUERY = """
MATCH (t1:Table)-[:HAS_COLUMN]->(:Column)-[:REFERENCES]->(:Column)<-[:HAS_COLUMN]-(t2:Table)
WHERE t1 <> t2
RETURN DISTINCT t1.id AS source_id, t2.id AS target_id
"""

LAKEHOUSE_TRACE_STATS_QUERY = """
MATCH (t:Table {id: $table_id})
OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
OPTIONAL MATCH (c)-[out:REFERENCES]->(:Column)
OPTIONAL MATCH (:Column)-[in:REFERENCES]->(c)
RETURN count(DISTINCT c) AS column_count,
       count(DISTINCT out) AS references_out,
       count(DISTINCT in) AS references_in
"""

GRAPH_MAP_QUERY = """
MATCH (d:Database {source_scope: $scope})-[:HAS_SCHEMA]->(s:Schema {source_scope: $scope})
OPTIONAL MATCH (s)-[:HAS_NODE]->(n:Node)
OPTIONAL MATCH (n)-[:HAS_PROPERTY]->(p:Property)
OPTIONAL MATCH (s)-[:HAS_RELATIONSHIP]->(rel:Relationship)
OPTIONAL MATCH (rel)-[:HAS_PROPERTY]->(rp:Property)
OPTIONAL MATCH (rel)-[:HAS_SOURCE_NODE]->(src:Node)
OPTIONAL MATCH (rel)-[:HAS_TARGET_NODE]->(tgt:Node)
RETURN d, s, n, p, rel, rp, src, tgt
"""

GRAPH_TRACE_STATS_QUERY = """
MATCH (n:Node {source_scope: $scope, label: $label})
OPTIONAL MATCH (n)-[:HAS_PROPERTY]->(p:Property)
OPTIONAL MATCH (rel:Relationship {source_scope: $scope})-[:HAS_SOURCE_NODE]->(n)
RETURN count(DISTINCT p) AS property_count,
       count(DISTINCT rel) AS relationship_type_count
"""


def _node_caption(properties: Mapping[str, Any], fallback: str) -> str:
    """Prefer `name`, then `label`, then `type`; fall back to neo4j_viz's own caption."""
    return properties.get("name") or properties.get("label") or properties.get("type") or fallback


def render_map(
    driver: Driver,
    database: str,
    query: str,
    params: Mapping[str, Any],
    *,
    hidden_labels: Iterable[str] = (),
    hidden_relationship_types: Iterable[str] = (),
    is_traced_node: Callable[[dict[str, Any]], bool] = lambda properties: False,
    extra_relationships: Iterable[tuple[str, str, str]] = (),
    height: int = DEFAULT_HEIGHT,
) -> tuple[int, int]:
    """Render one map slice, dimmed except the traced entity.

    `extra_relationships` is a sequence of (source domain id, relationship
    kind, target domain id) triples added on top of the query result; the
    Lakehouse page uses it to roll REFERENCES up to table level when columns
    are hidden. Returns the rendered (node_count, relationship_count).
    """
    result = driver.execute_query(
        query,
        parameters_=dict(params),
        database_=database,
        routing_=RoutingControl.READ,
    )
    vg = from_neo4j(result)

    hidden_labels = set(hidden_labels)
    hidden_relationship_types = set(hidden_relationship_types)

    kept_nodes = [
        node
        for node in vg.nodes
        if not hidden_labels.intersection(node.properties.get("labels", ()))
    ]
    kept_ids = {node.id for node in kept_nodes}
    domain_id_to_node_id = {
        node.properties["id"]: node.id for node in kept_nodes if node.properties.get("id")
    }

    kept_relationships = [
        rel
        for rel in vg.relationships
        if rel.properties.get("type") not in hidden_relationship_types
        and rel.source in kept_ids
        and rel.target in kept_ids
    ]

    for index, (source_domain_id, kind, target_domain_id) in enumerate(extra_relationships):
        source_id = domain_id_to_node_id.get(source_domain_id)
        target_id = domain_id_to_node_id.get(target_domain_id)
        if source_id is None or target_id is None:
            continue
        kept_relationships.append(
            Relationship(
                id=f"synthetic-{index}",
                source=source_id,
                target=target_id,
                caption=kind,
                properties={"type": kind, "synthetic": True},
            )
        )

    vg.nodes = kept_nodes
    vg.relationships = kept_relationships
    vg.color_nodes(field="caption")

    # Database/Schema are the map's singleton root context, not part of the
    # traced-vs-everything-else distinction; dimming them made the catalog
    # and schema indistinguishable from the grey background.
    always_traced_labels = {"Database", "Schema"}
    traced_ids: set[str] = {
        node.id
        for node in vg.nodes
        if is_traced_node(node.properties)
        or always_traced_labels.intersection(node.properties.get("labels", ()))
    }
    for rel in vg.relationships:
        if rel.source in traced_ids or rel.target in traced_ids:
            traced_ids.add(rel.source)
            traced_ids.add(rel.target)

    for node in vg.nodes:
        node.caption = _node_caption(node.properties, node.caption)
        if node.id in traced_ids:
            node.size = TRACED_SIZE
        else:
            node.size = DIMMED_SIZE
            node.color = DIMMED_COLOR

    for rel in vg.relationships:
        if rel.source in traced_ids and rel.target in traced_ids:
            rel.width = 3
        else:
            rel.color = DIMMED_COLOR

    html = vg.render(height=f"{height}px").data
    components.html(html, height=height + 20, scrolling=False)
    return len(vg.nodes), len(vg.relationships)

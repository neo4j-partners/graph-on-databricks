"""Operational graph page: the account graph itself, and NeoCarta's map of it.

Two independent selector groups, on purpose. `Label` traces the map half the
same way the Lakehouse page traces a Table. `Account`/`Depth`/`Types` bound
the subgraph rendered in THE DATA, capped at a node budget so a two-hop
account never tries to render the whole graph.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components
from neo4j import Driver, RoutingControl
from neo4j_viz import ColorSpace
from neo4j_viz.neo4j import from_neo4j

import semantic_map
from app_connections import GraphConnection
from config import source_neo4j_connection
from neo4j_schema_map import source_scope

NODE_BUDGET = 150
DEPTH_OPTIONS = (1, 2, 3)


@st.cache_data(show_spinner=False)
def list_labels(_driver: Driver, database: str, scope: str) -> list[str]:
    """Return the Node labels NeoCarta captured for this operational source."""
    records, _, _ = _driver.execute_query(
        "MATCH (n:Node {source_scope: $scope}) RETURN n.label AS label ORDER BY label",
        scope=scope,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [record["label"] for record in records]


@st.cache_data(show_spinner=False)
def list_relationship_types(_driver: Driver, database: str, scope: str) -> list[str]:
    """Return the relationship types NeoCarta captured for this operational source."""
    records, _, _ = _driver.execute_query(
        "MATCH (rel:Relationship {source_scope: $scope}) RETURN rel.type AS type ORDER BY type",
        scope=scope,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [record["type"] for record in records]


@st.cache_data(show_spinner=False)
def list_accounts(_driver: Driver, database: str) -> list[int]:
    """Return Account ids from the operational graph, for the bounding selector."""
    records, _, _ = _driver.execute_query(
        "MATCH (a:Account) RETURN a.account_id AS account_id ORDER BY account_id LIMIT 200",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [record["account_id"] for record in records]


def _relationship_pattern(selected_types: tuple[str, ...], depth: int) -> str:
    """Build a variable-length pattern from selectbox-constrained values only."""
    if selected_types:
        types = "|".join(f"`{name}`" for name in selected_types)
        return f"[:{types}*0..{depth}]"
    return f"[*0..{depth}]"


@st.cache_data(show_spinner=False)
def reachable_node_count(
    _driver: Driver, database: str, account_id: int, selected_types: tuple[str, ...], depth: int
) -> int:
    """Count every node reachable from the account, unbounded, for the caption."""
    pattern = _relationship_pattern(selected_types, depth)
    query = (
        f"MATCH (a:Account {{account_id: $account_id}})-{pattern}-(other) "
        "RETURN count(DISTINCT other) AS node_count"
    )
    records, _, _ = _driver.execute_query(
        query, account_id=account_id, database_=database, routing_=RoutingControl.READ
    )
    return records[0]["node_count"]


def bounded_subgraph(
    driver: Driver, database: str, account_id: int, selected_types: tuple[str, ...], depth: int
):
    """Fetch a node-budget-capped subgraph rooted at one account."""
    pattern = _relationship_pattern(selected_types, depth)
    query = f"""
    MATCH (a:Account {{account_id: $account_id}})
    CALL {{
      WITH a
      MATCH (a)-{pattern}-(other)
      RETURN DISTINCT other
      ORDER BY elementId(other)
      LIMIT $node_limit
    }}
    WITH collect(DISTINCT other) AS others, a
    WITH others + [a] AS kept
    UNWIND kept AS n
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE m IN kept
    RETURN DISTINCT n, r, m
    """
    return driver.execute_query(
        query,
        account_id=account_id,
        node_limit=NODE_BUDGET,
        database_=database,
        routing_=RoutingControl.READ,
    )


def render_data_subgraph(result, height: int = 480) -> int:
    """Render the bounded operational subgraph, colored by risk_score where present."""
    vg = from_neo4j(result)
    if any("risk_score" in node.properties for node in vg.nodes):
        vg.color_nodes(property="risk_score", color_space=ColorSpace.CONTINUOUS)
    else:
        vg.color_nodes(field="caption")
    components.html(vg.render(height=f"{height}px").data, height=height + 20, scrolling=False)
    return len(vg.nodes)


def render(operational_graph: GraphConnection, semantic_store: GraphConnection) -> None:
    st.title("Operational graph")

    if not operational_graph.ok:
        st.error(f"Operational graph unavailable: {operational_graph.error}")
        return
    if not semantic_store.ok:
        st.error(f"NeoCarta semantic store unavailable: {semantic_store.error}")
        return

    st.caption(f"{operational_graph.database} @ {operational_graph.host}")
    driver = semantic_store.driver
    database = semantic_store.database
    scope = source_scope(source_neo4j_connection())

    st.subheader("THE DATA")
    accounts = list_accounts(operational_graph.driver, operational_graph.database)
    if not accounts:
        st.warning("No Account nodes found in the operational graph.")
        return
    all_types = list_relationship_types(driver, database, scope)

    account_column, depth_column, types_column = st.columns(3)
    with account_column:
        account_id = st.selectbox("Account", accounts)
    with depth_column:
        depth = st.selectbox("Depth", DEPTH_OPTIONS, index=1)
    with types_column:
        selected_types = tuple(st.multiselect("Types", all_types))

    total_reachable = reachable_node_count(
        operational_graph.driver, operational_graph.database, account_id, selected_types, depth
    )
    result = bounded_subgraph(
        operational_graph.driver, operational_graph.database, account_id, selected_types, depth
    )
    shown_nodes = render_data_subgraph(result)
    st.caption(
        f"Showing {shown_nodes} of {total_reachable + 1} nodes within depth {depth}. "
        f"Capped at {NODE_BUDGET} nodes."
    )

    st.subheader("THE MAP")
    st.caption(f"NeoCarta store · {database} @ {semantic_store.host}")
    labels = list_labels(driver, database, scope)
    default_index = labels.index("Account") if "Account" in labels else 0
    selected_label = st.selectbox("Label", labels, index=default_index)
    show_properties = st.checkbox("Show properties", value=True)
    show_endpoints = st.checkbox("Show endpoints", value=True)

    hidden_labels = set() if show_properties else {"Property"}
    hidden_relationship_types = (
        set() if show_endpoints else {"HAS_SOURCE_NODE", "HAS_TARGET_NODE"}
    )

    def is_traced(properties: dict) -> bool:
        return properties.get("label") == selected_label

    semantic_map.render_map(
        driver,
        database,
        semantic_map.GRAPH_MAP_QUERY,
        {"scope": scope},
        hidden_labels=hidden_labels,
        hidden_relationship_types=hidden_relationship_types,
        is_traced_node=is_traced,
    )

    stats_records, _, _ = driver.execute_query(
        semantic_map.GRAPH_TRACE_STATS_QUERY,
        scope=scope,
        label=selected_label,
        database_=database,
        routing_=RoutingControl.READ,
    )
    stats = dict(stats_records[0]) if stats_records else {
        "property_count": 0,
        "relationship_type_count": 0,
    }
    st.caption(
        f"Traced: {selected_label} · {stats['property_count']} reported properties · "
        f"source of {stats['relationship_type_count']} relationship types"
    )
    st.caption("Endpoint pairs are statistics-based. No property values retained.")

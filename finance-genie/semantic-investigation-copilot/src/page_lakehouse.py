"""Lakehouse page: the accounts as tables, and the map NeoCarta wrote over them.

One selector drives both halves. Pick a table and the sample rows change and
the map dims to that Table, its Column nodes, and its REFERENCES edges at the
same moment. With `Show columns` off, the six REFERENCES edges NeoCarta
retains roll up to table level, so the map becomes the ER diagram the v1
design drew separately.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st
from neo4j import Driver, RoutingControl

import semantic_map
from app_connections import GraphConnection, WarehouseCredentials, open_warehouse_connection


@dataclass(frozen=True)
class TableEntry:
    """One selectable table and its NeoCarta-assigned identity."""

    name: str
    table_id: str


@st.cache_data(show_spinner=False)
def list_tables(_driver: Driver, database: str, catalog: str, schema: str) -> list[TableEntry]:
    """Return the tables NeoCarta captured for the configured catalog and schema."""
    records, _, _ = _driver.execute_query(
        "MATCH (:Database {name: $catalog})-[:HAS_SCHEMA]->(:Schema {name: $schema})"
        "-[:HAS_TABLE]->(t:Table) RETURN t.name AS name, t.id AS id ORDER BY t.name",
        catalog=catalog,
        schema=schema,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [TableEntry(name=record["name"], table_id=record["id"]) for record in records]


@st.cache_data(show_spinner=False)
def column_descriptions(_driver: Driver, database: str, table_id: str) -> dict[str, str]:
    """Return non-empty column descriptions for one table, for hover help text."""
    records, _, _ = _driver.execute_query(
        "MATCH (:Table {id: $table_id})-[:HAS_COLUMN]->(c:Column) "
        "RETURN c.name AS name, c.description AS description",
        table_id=table_id,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return {
        record["name"]: record["description"]
        for record in records
        if record["description"]
    }


@st.cache_data(show_spinner=False)
def trace_stats(_driver: Driver, database: str, table_id: str) -> dict[str, int]:
    """Return the column and REFERENCES counts shown in the trace caption."""
    records, _, _ = _driver.execute_query(
        semantic_map.LAKEHOUSE_TRACE_STATS_QUERY,
        table_id=table_id,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return dict(records[0]) if records else {"column_count": 0, "references_out": 0, "references_in": 0}


@st.cache_data(show_spinner=False)
def table_references(_driver: Driver, database: str) -> list[tuple[str, str, str]]:
    """Return table-to-table REFERENCES rollups for the columns-off ER view."""
    records, _, _ = _driver.execute_query(
        semantic_map.LAKEHOUSE_TABLE_REFERENCES_QUERY,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [(record["source_id"], "REFERENCES", record["target_id"]) for record in records]


def render(warehouse: WarehouseCredentials, semantic_store: GraphConnection) -> None:
    st.title("Lakehouse")

    if not warehouse.ok:
        st.error(f"SQL warehouse unavailable: {warehouse.error}")
        return
    if not semantic_store.ok:
        st.error(f"NeoCarta semantic store unavailable: {semantic_store.error}")
        return

    st.caption(f"{warehouse.catalog}.{warehouse.schema} · warehouse")
    driver = semantic_store.driver
    database = semantic_store.database

    tables = list_tables(driver, database, warehouse.catalog, warehouse.schema)
    if not tables:
        st.warning("NeoCarta has not captured any tables for this catalog and schema yet.")
        return
    table_names = [entry.name for entry in tables]
    default_index = table_names.index("gold_accounts") if "gold_accounts" in table_names else 0
    selected_name = st.selectbox("Table", table_names, index=default_index)
    selected = next(entry for entry in tables if entry.name == selected_name)

    st.subheader("THE DATA")
    st.caption("10 sample rows")
    try:
        with open_warehouse_connection(warehouse) as connection, connection.cursor() as cursor:
            qualified_table = f"`{warehouse.catalog}`.`{warehouse.schema}`.`{selected_name}`"
            cursor.execute(f"SELECT * FROM {qualified_table} LIMIT 10")  # noqa: S608
            column_names = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
    except Exception as error:  # noqa: BLE001 - surface the warehouse's own error
        st.error(f"Query failed: {error}")
    else:
        import pandas as pd

        descriptions = column_descriptions(driver, database, selected.table_id)
        column_config = {
            name: st.column_config.Column(help=descriptions[name])
            for name in column_names
            if name in descriptions
        }
        st.dataframe(
            pd.DataFrame(rows, columns=column_names),
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )
        st.caption(f"Column comments shown on hover. {len(tables)} tables in scope.")

    if selected_name == "gold_accounts":
        st.info(
            "`gold_accounts` is graph output that came back into the lakehouse — "
            "the only reason the two systems have anything to say to each other."
        )

    st.subheader("THE MAP")
    st.caption(f"NeoCarta store · {database} @ {semantic_store.host}")
    show_columns = st.checkbox("Show columns", value=True)
    show_references = st.checkbox("Show REFERENCES", value=True)

    hidden_labels = set() if show_columns else {"Column"}
    hidden_relationship_types = set() if show_references else {"REFERENCES"}
    extra_relationships = (
        table_references(driver, database) if not show_columns and show_references else ()
    )

    def is_traced(properties: dict) -> bool:
        node_id = properties.get("id", "")
        if node_id == selected.table_id:
            return True
        return "Column" in properties.get("labels", ()) and node_id.startswith(
            f"{selected.table_id}."
        )

    semantic_map.render_map(
        driver,
        database,
        semantic_map.LAKEHOUSE_MAP_QUERY,
        {"catalog": warehouse.catalog, "schema": warehouse.schema},
        key="lakehouse-map",
        hidden_labels=hidden_labels,
        hidden_relationship_types=hidden_relationship_types,
        is_traced_node=is_traced,
        extra_relationships=extra_relationships,
    )

    stats = trace_stats(driver, database, selected.table_id)
    st.caption(
        f"Traced: {selected_name} · {stats['column_count']} columns · "
        f"{stats['references_out']} REFERENCES out · {stats['references_in']} REFERENCES in"
    )
    st.caption("Captured from Unity Catalog information_schema. No row values retained.")

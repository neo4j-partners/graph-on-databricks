"""Ask page: retrieval, grounding, generated queries, and their answers.

Every rerun re-renders from `st.session_state`; only the Ask button and the
two Run buttons advance it. One MCP session and one generation call per Ask
click — never cached across reruns, per `mcp_retrieval.py`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from neo4j import RoutingControl

import grounding
import mcp_retrieval
import query_generation
from app_connections import GraphConnection, WarehouseCredentials, open_warehouse_connection

PRESETS = (
    "Which fraud rings share an identity cluster?",
    "Which accounts moved money to a high-risk account?",
    "Where do identity clusters cross regions?",
)


def _run_sql(warehouse: WarehouseCredentials, sql: str) -> dict:
    try:
        with open_warehouse_connection(warehouse) as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            column_names = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
    except Exception as error:  # noqa: BLE001 - model-generated SQL, show the server's own error
        return {"error": str(error)}
    return {"dataframe": pd.DataFrame(rows, columns=column_names)}


def _run_cypher(operational_graph: GraphConnection, cypher: str) -> dict:
    try:
        records, _, _ = operational_graph.driver.execute_query(
            cypher,
            database_=operational_graph.database,
            routing_=RoutingControl.READ,
        )
        rows = [record.data() for record in records]
    except Exception as error:  # noqa: BLE001 - model-generated Cypher, show the server's own error
        return {"error": str(error)}
    return {"dataframe": pd.DataFrame(rows)}


def render(
    warehouse: WarehouseCredentials,
    operational_graph: GraphConnection,
    semantic_store: GraphConnection,
) -> None:
    st.title("Ask")

    if not warehouse.ok:
        st.error(f"SQL warehouse unavailable: {warehouse.error}")
        return
    if not operational_graph.ok:
        st.error(f"Operational graph unavailable: {operational_graph.error}")
        return
    if not semantic_store.ok:
        st.error(f"NeoCarta semantic store unavailable: {semantic_store.error}")
        return

    preset = st.pills("Presets", PRESETS, selection_mode="single")
    question = st.text_input(
        "Question", value=preset or st.session_state.get("ask_question", "")
    )
    st.session_state["ask_question"] = question

    if st.button("Ask", type="primary", disabled=not question):
        with st.spinner("Retrieving from the map…"):
            trace = mcp_retrieval.run_retrieval(question, warehouse.catalog, warehouse.schema)
        with st.spinner("Generating grounded queries…"):
            generated = query_generation.generate_queries(
                question, trace, catalog=warehouse.catalog, schema=warehouse.schema
            )
        st.session_state["ask_trace"] = trace
        st.session_state["ask_generated"] = generated
        st.session_state.pop("ask_sql_result", None)
        st.session_state.pop("ask_cypher_result", None)

    trace = st.session_state.get("ask_trace")
    generated = st.session_state.get("ask_generated")
    if trace is None or generated is None:
        return

    st.subheader("RETRIEVED FROM THE MAP")
    for tool_call in (trace.table_search, trace.column_search, trace.schema_context):
        with st.status(tool_call.tool_name, state="complete"):
            st.caption(f"Arguments: {tool_call.arguments}")
            st.write(f"Retrieved: {', '.join(tool_call.names) or '(none)'}")
            with st.expander("Raw result"):
                st.json(tool_call.result)

    st.subheader("GROUNDED IN")
    declared = [
        grounding.DeclaredIdentifier(name=name, source_tool=source_tool)
        for name, source_tool in generated.identifiers
    ]
    for row in grounding.ground(declared, trace.retrieved_names()):
        if row.retrieved:
            st.markdown(f"✓ `{row.name}` — {row.source_tool}")
        else:
            st.markdown(f":red[✗ `{row.name}` — {row.source_tool} — not retrieved]")

    st.subheader("QUERIES BUILT FROM THAT CONTEXT")
    sql_column, cypher_column = st.columns(2)
    with sql_column:
        st.code(generated.sql, language="sql")
        if st.button("Run (read-only warehouse)", key="run_sql"):
            st.session_state["ask_sql_result"] = _run_sql(warehouse, generated.sql)
    with cypher_column:
        st.code(generated.cypher, language="cypher")
        if st.button("Run (read-only transaction)", key="run_cypher"):
            st.session_state["ask_cypher_result"] = _run_cypher(
                operational_graph, generated.cypher
            )

    st.subheader("ANSWER")
    answer_sql_column, answer_cypher_column = st.columns(2)
    with answer_sql_column:
        result = st.session_state.get("ask_sql_result")
        if result is None:
            st.caption("Not run yet.")
        elif "error" in result:
            st.error(result["error"])
        else:
            st.dataframe(result["dataframe"], use_container_width=True, hide_index=True)
    with answer_cypher_column:
        result = st.session_state.get("ask_cypher_result")
        if result is None:
            st.caption("Not run yet.")
        elif "error" in result:
            st.error(result["error"])
        else:
            st.dataframe(result["dataframe"], use_container_width=True, hide_index=True)

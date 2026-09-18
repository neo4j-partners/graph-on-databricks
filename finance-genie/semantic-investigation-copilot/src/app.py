"""Semantic Investigation Copilot: Lakehouse, Operational graph, and Ask.

The app opens on Lakehouse. Every page reads from the same three cached,
read-only connections; none of them can write, and this module runs no build
step and offers no destructive action against a remote store.
"""

from __future__ import annotations

import streamlit as st

import page_ask
import page_lakehouse
import page_operational_graph
from app_connections import (
    operational_graph_connection,
    semantic_store_connection,
    warehouse_credentials,
)
from config import load_demo_env

STORE_BUILD_SEQUENCE = """make install
make ingest
make neo4j-schema-ingest
make validate"""


def _badge(label: str, ok: bool) -> str:
    return f"{'🟢' if ok else '🔴'} {label}"


def _render_sidebar_status():
    warehouse = warehouse_credentials()
    operational_graph = operational_graph_connection()
    semantic_store = semantic_store_connection()

    st.sidebar.markdown(_badge("SQL warehouse", warehouse.ok))
    st.sidebar.markdown(_badge("Operational graph", operational_graph.ok))
    st.sidebar.markdown(_badge("Semantic store", semantic_store.ok))

    with st.sidebar.expander("Connections"):
        st.write(f"Warehouse host: `{warehouse.server_hostname or '—'}`")
        st.write(f"Catalog.schema: `{warehouse.catalog}.{warehouse.schema}`")
        st.write(
            f"Operational graph: `{operational_graph.host or '—'}` "
            f"/ `{operational_graph.database or '—'}`"
        )
        st.write(
            f"Semantic store: `{semantic_store.host or '—'}` "
            f"/ `{semantic_store.database or '—'}`"
        )

    with st.sidebar.expander("Store not built?"):
        st.caption(
            "Run these from `semantic-investigation-copilot/` against the configured "
            "NeoCarta store. `make neo4j-up` starts a loopback store only — skip it "
            "against a remote store, and this app never runs any of these for you."
        )
        st.code(STORE_BUILD_SEQUENCE, language="bash")

    return warehouse, operational_graph, semantic_store


def main() -> None:
    load_demo_env()
    st.set_page_config(page_title="Semantic Investigation Copilot", layout="wide")

    warehouse, operational_graph, semantic_store = _render_sidebar_status()

    def _lakehouse_page() -> None:
        page_lakehouse.render(warehouse, semantic_store)

    def _operational_graph_page() -> None:
        page_operational_graph.render(operational_graph, semantic_store)

    def _ask_page() -> None:
        page_ask.render(warehouse, operational_graph, semantic_store)

    pages = st.navigation(
        {
            "DATA AND ITS MAP": [
                st.Page(_lakehouse_page, title="Lakehouse", default=True),
                st.Page(_operational_graph_page, title="Operational graph"),
            ],
            "ASK": [st.Page(_ask_page, title="Ask")],
        }
    )
    pages.run()


main()

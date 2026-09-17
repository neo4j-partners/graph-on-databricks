"""Focused tests for the semantic metadata graph loader."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, ClassVar

import pytest

from semantic_graph import (
    DEFAULT_MAPPING_FILE,
    MAPPINGS_DIR,
    MappingValidationError,
    build_records,
    embed_business_concepts,
    load_mapping,
    load_semantic_graph,
    validate_mapping,
    validate_neocarta_csvs,
    write_graph_adapter,
)


class StubDriver:
    """Capture Cypher and report that every parameter row was processed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute_query(self, query_: str, **kwargs: Any):
        self.calls.append((query_, kwargs))
        rows = kwargs.get("parameters_", {}).get("rows", [])
        records = [{"processed": len(rows)}] if rows else []
        return records, None, None


class StubCSVConnector:
    """Record the Neocarta connector configuration and ingest selection."""

    instances: ClassVar[list[StubCSVConnector]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.ingest_kwargs: dict[str, Any] | None = None
        self.instances.append(self)

    def ingest(self, **kwargs: Any) -> None:
        self.ingest_kwargs = kwargs


class StubEmbeddingConnector:
    """Expose the native-dimension behavior without calling Databricks."""

    instances: ClassVar[list[StubEmbeddingConnector]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.dimensions: int | None = None
        self.run_kwargs: dict[str, Any] | None = None
        self.instances.append(self)

    def run(self, **kwargs: Any) -> None:
        self.run_kwargs = kwargs
        self.dimensions = 1024


def test_repository_mapping_and_csvs_produce_expected_metadata_counts() -> None:
    mapping = load_mapping(DEFAULT_MAPPING_FILE)
    validate_neocarta_csvs(mapping, MAPPINGS_DIR)

    records = build_records(mapping)

    assert len(records.concepts) == 5
    assert len(records.table_mappings) == 6
    assert len(records.column_mappings) == 23
    assert len(records.graph_databases) == 1
    assert len(records.graph_node_labels) == 8
    assert len(records.graph_relationship_types) == 9
    assert len(records.graph_properties) == 35
    assert len(records.relationship_endpoints) == 9
    assert {row["name"] for row in records.graph_relationship_types} >= {
        "HAS_PHONE",
        "TRANSFERRED_TO",
    }
    assert any(
        row["relationship_id"].endswith(":HAS_PHONE")
        and row["source_label_id"].endswith(":Customer")
        and row["target_label_id"].endswith(":Phone")
        for row in records.relationship_endpoints
    )


def test_top_level_loader_uses_neocarta_csv_connector_and_custom_adapter() -> None:
    StubCSVConnector.instances.clear()
    driver = StubDriver()

    counts = load_semantic_graph(
        driver,
        "neo4j",
        csv_connector_factory=StubCSVConnector,
    )

    assert counts.concepts == 5
    assert counts.table_mappings == 6
    assert counts.column_mappings == 23
    assert counts.graph_node_labels == 8
    assert counts.graph_relationship_types == 9
    assert counts.graph_properties == 35
    assert counts.relationship_endpoints == 9
    assert counts.concept_graph_asset_mappings == 81
    connector = StubCSVConnector.instances[-1]
    assert connector.kwargs["csv_directory"] == str(MAPPINGS_DIR)
    assert connector.kwargs["database_name"] == "neo4j"
    assert set(connector.ingest_kwargs["include_nodes"]) == {
        "Glossary",
        "Category",
        "BusinessTerm",
    }
    assert set(connector.ingest_kwargs["include_relationships"]) == {
        "HAS_CATEGORY",
        "HAS_BUSINESS_TERM",
        "TAGGED_WITH",
    }


def test_custom_writes_are_parameterized_scoped_and_idempotent() -> None:
    records = build_records(load_mapping())
    driver = StubDriver()

    first_counts = write_graph_adapter(driver, "neo4j", records)
    first_calls = copy.deepcopy(driver.calls)
    driver.calls.clear()
    second_counts = write_graph_adapter(driver, "neo4j", records)

    assert second_counts == first_counts
    assert driver.calls == first_calls
    mutation_calls = [call for call in first_calls if "UNWIND $rows AS row" in call[0]]
    assert mutation_calls
    assert all("$rows" in query for query, _ in mutation_calls)
    assert all("shared_identity" not in query for query, _ in mutation_calls)
    assert all("CREATE (" not in query for query, _ in mutation_calls)
    assert all(kwargs["database_"] == "neo4j" for _, kwargs in mutation_calls)

    table_query, table_kwargs = next(call for call in mutation_calls if "MAPS_TO_TABLE" in call[0])
    assert "(:Database {id: row.database_id})-[:HAS_SCHEMA]" in table_query
    assert "(:Schema {id: row.schema_id})" in table_query
    assert "(asset:Table {id: row.table_id})" in table_query
    assert len(table_kwargs["parameters_"]["rows"]) == 6

    endpoint_query, endpoint_kwargs = next(
        call for call in mutation_calls if "HAS_SOURCE_LABEL" in call[0]
    )
    assert "HAS_TARGET_LABEL" in endpoint_query
    assert len(endpoint_kwargs["parameters_"]["rows"]) == 9


def test_mapping_boundary_rejects_operational_payloads() -> None:
    mapping = load_mapping()
    changed = copy.deepcopy(mapping)
    changed["concepts"][0]["databricks"]["sample_values"] = ["customer-123"]

    with pytest.raises(MappingValidationError, match="Unsupported.*fields"):
        validate_mapping(changed)


def test_mapping_boundary_rejects_graph_property_outside_declared_schema() -> None:
    mapping = load_mapping()
    changed = copy.deepcopy(mapping)
    changed["concepts"][0]["neo4j"]["properties"]["CustomerRecord"] = ["phone"]

    with pytest.raises(MappingValidationError, match="property owner"):
        validate_mapping(changed)


def test_csv_contract_detects_mapping_drift(tmp_path: Path) -> None:
    for path in MAPPINGS_DIR.glob("*.csv"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    business_terms = tmp_path / "business_term_info.csv"
    business_terms.write_text(
        business_terms.read_text(encoding="utf-8").replace("Shared identity", "Wrong term"),
        encoding="utf-8",
    )

    with pytest.raises(MappingValidationError, match="business_term_info.csv"):
        validate_neocarta_csvs(load_mapping(), tmp_path)


def test_csv_contract_rejects_duplicate_rows(tmp_path: Path) -> None:
    for path in MAPPINGS_DIR.glob("*.csv"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    tables = tmp_path / "table_term_info.csv"
    lines = tables.read_text(encoding="utf-8").splitlines()
    tables.write_text("\n".join([*lines, lines[1]]) + "\n", encoding="utf-8")

    with pytest.raises(MappingValidationError, match="table_term_info.csv"):
        validate_neocarta_csvs(load_mapping(), tmp_path)


def test_csv_contract_rejects_changed_headers(tmp_path: Path) -> None:
    for path in MAPPINGS_DIR.glob("*.csv"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    columns = tmp_path / "column_term_info.csv"
    content = columns.read_text(encoding="utf-8")
    columns.write_text(content.replace("column_id", "asset_id", 1), encoding="utf-8")

    with pytest.raises(MappingValidationError, match="columns changed"):
        validate_neocarta_csvs(load_mapping(), tmp_path)


def test_embeddings_use_databricks_model_and_native_dimensions() -> None:
    StubEmbeddingConnector.instances.clear()

    dimensions = embed_business_concepts(
        StubDriver(),
        "neo4j",
        "databricks/databricks-gte-large-en",
        connector_factory=StubEmbeddingConnector,
    )

    assert dimensions == 1024
    connector = StubEmbeddingConnector.instances[-1]
    assert connector.kwargs["dimensions"] is None
    assert connector.kwargs["embedding_model"] == "databricks/databricks-gte-large-en"
    assert connector.run_kwargs == {"node_labels": ["BusinessTerm"], "batch_size": 100}


def test_embeddings_reject_non_databricks_provider() -> None:
    with pytest.raises(ValueError, match="databricks/"):
        embed_business_concepts(
            StubDriver(),
            "neo4j",
            "text-embedding-3-small",
            connector_factory=StubEmbeddingConnector,
        )

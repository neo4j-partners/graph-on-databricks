"""Focused tests for the source mapping-to-evidence contract."""

from __future__ import annotations

import copy

import pytest

from validate_sources import (
    EVIDENCE_FILE,
    MAPPING_FILE,
    collect_databricks_contract,
    collect_neo4j_contract,
    load_json,
    required_evidence_keys,
    validate_evidence_coverage,
)


def test_repository_contract_has_expected_coverage() -> None:
    required = required_evidence_keys(load_json(MAPPING_FILE))

    assert len(required["databricks_columns"]) == 17
    assert len(required["databricks_joins"]) == 6
    assert len(required["databricks_predicates"]) == 2
    assert len(required["neo4j_labels"]) == 8
    assert len(required["neo4j_relationships"]) == 9
    assert len(required["neo4j_node_properties"]) == 27
    assert len(required["neo4j_relationship_properties"]) == 8
    assert len(required["neo4j_paths"]) == 9


def test_rejects_mapping_claim_missing_from_evidence() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_mapping = copy.deepcopy(mapping)
    changed_mapping["concepts"][0]["databricks"]["columns"].append("unverified_column")

    with pytest.raises(RuntimeError, match="databricks_columns"):
        validate_evidence_coverage(changed_mapping, evidence)


def test_rejects_source_scope_drift() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["neo4j"]["database"] = "different"

    with pytest.raises(RuntimeError, match="source scope"):
        validate_evidence_coverage(mapping, changed_evidence)


def test_rejects_failed_live_observation() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["neo4j"]["verified_paths"][0]["match_count"] = 0

    with pytest.raises(RuntimeError, match="failed observations"):
        validate_evidence_coverage(mapping, changed_evidence)


@pytest.mark.parametrize(
    "predicate",
    [
        "identity_cluster_size > 1; DELETE FROM accounts",
        "identity_cluster_size > 1 -- comment",
        "identity_cluster_size > 1 OR 1 = 1",
        "CALL malicious()",
    ],
)
def test_rejects_unsafe_databricks_predicate(predicate: str) -> None:
    mapping = load_json(MAPPING_FILE)
    changed_mapping = copy.deepcopy(mapping)
    changed_mapping["concepts"][0]["databricks"]["predicate"] = predicate

    with pytest.raises(RuntimeError, match="Unsupported Databricks predicate"):
        collect_databricks_contract(changed_mapping)


@pytest.mark.parametrize(
    "path",
    [
        "(:Customer) DETACH DELETE customer",
        "(:Customer) SET customer.compromised = true",
        "(:Customer) CALL db.labels()",
        "(:Customer); MATCH (node) RETURN node",
        "(:Customer) // comment",
    ],
)
def test_rejects_unsafe_neo4j_path(path: str) -> None:
    mapping = load_json(MAPPING_FILE)
    changed_mapping = copy.deepcopy(mapping)
    changed_mapping["concepts"][0]["neo4j"]["paths"][0] = path

    with pytest.raises(RuntimeError, match="Unsupported Neo4j path pattern"):
        collect_neo4j_contract(changed_mapping)


def test_rejects_tampered_fixture_evidence() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["databricks"]["fixture"]["account_ids"][0] = -1

    with pytest.raises(RuntimeError, match="invalid fixture data"):
        validate_evidence_coverage(mapping, changed_evidence)


def test_rejects_tampered_gds_attestation() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["neo4j"]["existing_validation"]["checks_passed"] = 0

    with pytest.raises(RuntimeError, match="invalid GDS/KYC attestation"):
        validate_evidence_coverage(mapping, changed_evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("working_directory", "elsewhere"),
        ("command", "printf fake"),
        ("script_sha256", "0" * 64),
        ("executed_at", "2026-09-16T00:00:00+00:00"),
    ],
)
def test_rejects_tampered_gds_provenance(field: str, value: str) -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["neo4j"]["existing_validation"][field] = value

    with pytest.raises(RuntimeError, match="invalid GDS/KYC attestation"):
        validate_evidence_coverage(mapping, changed_evidence)


def test_rejects_duplicate_evidence_claim() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["databricks"]["verified_columns"].append(
        copy.deepcopy(changed_evidence["databricks"]["verified_columns"][0])
    )

    with pytest.raises(RuntimeError, match="duplicate claims"):
        validate_evidence_coverage(mapping, changed_evidence)


def test_rejects_unexpected_evidence_claim() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["neo4j"]["verified_paths"].append(
        {"pattern": "(:Unexpected)", "match_count": 1, "concepts": []}
    )

    with pytest.raises(RuntimeError, match="does not exactly match"):
        validate_evidence_coverage(mapping, changed_evidence)


def test_rejects_fabricated_databricks_type() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["databricks"]["verified_columns"][0]["data_type"] = "FABRICATED"

    with pytest.raises(RuntimeError, match="failed observations"):
        validate_evidence_coverage(mapping, changed_evidence)


def test_rejects_impossible_neo4j_property_count() -> None:
    mapping = load_json(MAPPING_FILE)
    evidence = load_json(EVIDENCE_FILE)
    changed_evidence = copy.deepcopy(evidence)
    account = next(
        item
        for item in changed_evidence["neo4j"]["verified_node_labels"]
        if item["label"] == "Account"
    )
    account["node_count"] = 1

    with pytest.raises(RuntimeError, match="property counts exceed"):
        validate_evidence_coverage(mapping, changed_evidence)

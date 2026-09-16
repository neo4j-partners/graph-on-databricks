"""Contract tests for the Phase 1 semantic mappings."""

from __future__ import annotations

import json
from pathlib import Path

MAPPINGS = Path(__file__).parents[1] / "mappings" / "semantic-mappings.json"


def test_mapping_contract_has_five_concepts_and_one_primary() -> None:
    mapping = json.loads(MAPPINGS.read_text())
    concepts = {concept["id"]: concept for concept in mapping["concepts"]}

    assert mapping["primary_concept"] == "shared_identity"
    assert set(concepts) == {
        "shared_identity",
        "kyc_review_candidate",
        "transfer_exposure",
        "fraud_ring_candidate",
        "high_risk",
    }


def test_shared_identity_maps_both_sources() -> None:
    mapping = json.loads(MAPPINGS.read_text())
    shared_identity = next(
        concept for concept in mapping["concepts"] if concept["id"] == "shared_identity"
    )

    assert shared_identity["databricks"]["table"] == "gold_accounts"
    assert "identity_cluster_size" in shared_identity["databricks"]["columns"]
    assert "Customer" in shared_identity["neo4j"]["node_labels"]
    assert "CLASSIFIED_AS" in shared_identity["neo4j"]["relationship_types"]

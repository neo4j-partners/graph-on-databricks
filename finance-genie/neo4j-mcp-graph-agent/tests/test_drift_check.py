import importlib.util
import sys
from pathlib import Path

from agent.prompt import SYSTEM_PROMPT

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_drift.py"
_spec = importlib.util.spec_from_file_location("check_drift", SCRIPT)
cd = importlib.util.module_from_spec(_spec)
sys.modules["check_drift"] = cd
_spec.loader.exec_module(cd)


def test_prompt_schema_reads_labels_properties_and_relationships():
    schema = cd.prompt_schema(SYSTEM_PROMPT)

    assert set(schema.nodes) == {"Account", "Merchant", "Customer", "Phone", "Address"}
    # Notes in parentheses and enum values in brackets are not property names.
    assert {"account_type", "risk_score", "community_id"} <= schema.nodes["Account"]
    assert not any(" " in p or "[" in p for p in schema.nodes["Account"])
    assert schema.rels[("Account", "TRANSFERRED_TO", "Account")] == {
        "amount", "transfer_timestamp", "link_id"
    }
    assert schema.rels[("Customer", "OWNS", "Account")] == set()


def test_live_schema_reads_both_directions():
    payload = {
        "Customer": {
            "type": "node",
            "properties": {"name": {}},
            "relationships": {"OWNS": {"direction": "out", "labels": ["Account"]}},
        },
        "Account": {
            "type": "node",
            "properties": {"account_id": {}},
            "relationships": {
                "OWNS": {"direction": "in", "labels": ["Customer"]},
                "TRANSFERRED_TO": {
                    "direction": "out", "labels": ["Account"], "properties": {"amount": {}}
                },
            },
        },
        "OWNS": {"type": "relationship", "count": 3},
    }

    schema = cd.live_schema(payload)

    assert schema.nodes == {"Customer": {"name"}, "Account": {"account_id"}}
    assert schema.rels == {
        ("Customer", "OWNS", "Account"): set(),
        ("Account", "TRANSFERRED_TO", "Account"): {"amount"},
    }


def test_schema_drift_reports_what_is_missing_and_ignores_extras():
    expected = cd.Schema(
        nodes={"Account": {"account_id", "risk_score"}, "Ghost": set()},
        rels={("Account", "T", "Account"): {"amount"}, ("Account", "X", "Account"): set()},
    )
    live = cd.Schema(
        nodes={"Account": {"account_id", "extra"}, "Policy": set()},
        rels={("Account", "T", "Account"): {"other"}, ("Account", "Y", "Account"): set()},
    )

    assert cd.schema_drift(expected, live) == [
        "Account.risk_score is missing",
        "label Ghost is missing",
        "(Account)-[:T]->(Account) property amount is missing",
        "relationship (Account)-[:X]->(Account) is missing",
    ]
    assert cd.schema_drift(live, live) == []


def test_named_ids_collects_questions_and_cases():
    scenarios = cd.load_scenarios()

    accounts, communities = cd.named_ids(scenarios)

    for case in scenarios.CASES:
        assert set(case.top_accounts) <= set(accounts)
        assert case.community_id in communities
    assert set(cd.HUB_COMMUNITIES) <= set(accounts)

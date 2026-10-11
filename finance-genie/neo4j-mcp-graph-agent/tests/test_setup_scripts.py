import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


attach = _load("attach_nams_key")
grant = _load("grant_genie")


def test_with_nams_key_keeps_existing_resources_and_appends_the_key():
    existing = [
        {"name": "agentbricks-tool-genie", "genie_space": {"space_id": "s1", "permission": "CAN_RUN"}},
        {"name": "runtime-store", "postgres": {"branch": "b", "permission": "CAN_CONNECT_AND_CREATE"}},
    ]

    resources = attach.with_nams_key(existing, "nams", "memory-api-key")

    assert resources[:2] == existing
    assert resources[2] == {
        "name": "nams-api-key",
        "secret": {"scope": "nams", "key": "memory-api-key", "permission": "READ"},
    }


def test_with_nams_key_is_none_when_the_resource_exists():
    existing = [{"name": "nams-api-key", "secret": {"scope": "other", "key": "k"}}]

    assert attach.with_nams_key(existing, "nams", "memory-api-key") is None


def test_update_body_masks_the_write_to_resources():
    body = attach.update_body("my-app", [{"name": "x"}])

    assert body == {"app": {"name": "my-app", "resources": [{"name": "x"}]}, "update_mask": "resources"}


def test_genie_space_ids_reads_only_genie_agent_tools():
    toml = """
[[tools]]
id = "mcp"
source = { kind = "mcp", service = "c.s.svc" }

[[tools]]
id = "genie"
auth = "app"
source = { kind = "genie_agent", space_id = "abc123" }
"""

    assert grant.genie_space_ids(toml) == ["abc123"]


def test_genie_space_ids_reads_the_repo_agent_toml():
    assert len(grant.genie_space_ids(grant.AGENT_TOML.read_text())) == 1


def test_space_schemas_dedupes_the_table_schemas():
    serialized = json.dumps({"data_sources": {"tables": [
        {"identifier": "graph-on-databricks.graph-enriched-schema.accounts"},
        {"identifier": "graph-on-databricks.graph-enriched-schema.merchants"},
        {"identifier": "other.gold.facts"},
    ]}})

    assert grant.space_schemas(serialized) == ["graph-on-databricks.graph-enriched-schema", "other.gold"]


def test_planned_grants_cover_warehouse_catalog_and_schema():
    grants = grant.planned_grants(["wh1"], ["graph-on-databricks.graph-enriched-schema"])

    assert [str(g) for g in grants] == [
        "CAN_USE on warehouse wh1",
        "USE_CATALOG on catalog graph-on-databricks",
        "USE_SCHEMA on schema graph-on-databricks.graph-enriched-schema",
        "SELECT on schema graph-on-databricks.graph-enriched-schema",
    ]

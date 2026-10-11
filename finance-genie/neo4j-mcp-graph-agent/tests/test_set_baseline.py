import importlib.util
import json
import sys
from json import dumps
from pathlib import Path

import httpx
import pytest

ONTOLOGY_DIR = Path(__file__).resolve().parent.parent / "ontology"
sys.path.insert(0, str(ONTOLOGY_DIR))

_spec = importlib.util.spec_from_file_location(
    "set_baseline", ONTOLOGY_DIR / "set_baseline.py"
)
set_baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_baseline)


def version(version_id, revision, doc):
    return {
        "id": version_id,
        "ontology_id": "ont_default",
        "revision": revision,
        "schema_json": dumps(doc),
    }


DEFAULT_DOC = {
    "domain": {"id": "nams-default", "name": "NAMS Default"},
    "entity_types": [{"label": "Person", "pole_type": "PERSON"}],
    "relationships": [],
}


class FakeClient:
    calls: list = []
    active: dict = {}
    versions: list = []

    def __init__(self, **kwargs):
        pass

    def request(self, method, path, json=None):
        FakeClient.calls.append((method, path, json))
        if (method, path) == ("GET", "/v1/ontologies/active"):
            body = FakeClient.active
        elif (method, path) == ("GET", "/v1/ontologies"):
            body = {"ontologies": [
                {"id": "ont_default", "name": "nams-default", "is_system": True}
            ]}
        elif (method, path) == ("GET", "/v1/ontologies/ont_default"):
            body = {"versions": FakeClient.versions}
        else:
            body = {"id": json["version_id"], "ontology_id": "ont_default"}
        return httpx.Response(200, json=body)

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch, tmp_path):
    FakeClient.calls = []
    FakeClient.active = {"version": {"id": "ov_finance", "ontology_id": "ont_f"}}
    FakeClient.versions = [version("ov_d1", 1, DEFAULT_DOC)]
    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setenv("MEMORY_API_KEY", "nams_secret_value")
    monkeypatch.setattr(set_baseline, "STATE_DIR", tmp_path / "out")
    return FakeClient


def writes(fake):
    return [(m, p) for m, p, _ in fake.calls if m in ("POST", "PUT")]


def test_default_activates_plain_default_and_saves_previous(fake, tmp_path):
    assert set_baseline.main(["--baseline", "default"]) == 0
    assert writes(fake) == [("POST", "/v1/ontologies/active")]
    assert fake.calls[-1][2] == {"version_id": "ov_d1"}
    saved = list((tmp_path / "out").glob("previous_active_*.json"))
    assert json.loads(saved[0].read_text())["version_id"] == "ov_finance"


def test_default_is_a_no_op_when_already_active(fake):
    fake.active = {"version": {"id": "ov_d1", "ontology_id": "ont_default"}}
    assert set_baseline.main(["--baseline", "default"]) == 0
    assert writes(fake) == []


def test_none_succeeds_with_no_active_ontology(fake, capsys):
    fake.active = {}
    assert set_baseline.main(["--baseline", "none"]) == 0
    assert writes(fake) == []


def test_none_fails_when_an_ontology_is_active(fake, capsys):
    assert set_baseline.main(["--baseline", "none"]) == 3
    assert "cannot unbind" in capsys.readouterr().err
    assert writes(fake) == []

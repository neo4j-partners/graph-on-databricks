import copy
import importlib.util
import json
import sys
from json import dumps
from pathlib import Path

import httpx
import pytest

ONTOLOGY_DIR = Path(__file__).resolve().parent.parent / "ontology"
YAML_PATH = ONTOLOGY_DIR / "finance_genie.ontology.yaml"

_spec = importlib.util.spec_from_file_location(
    "apply_ontology", ONTOLOGY_DIR / "apply_ontology.py"
)
apply_ontology = importlib.util.module_from_spec(_spec)
sys.modules["apply_ontology"] = apply_ontology
_spec.loader.exec_module(apply_ontology)


@pytest.fixture
def document():
    return apply_ontology.load_ontology(YAML_PATH)


def problems_for(document, mutate):
    broken = copy.deepcopy(document)
    mutate(broken)
    return apply_ontology.validate_ontology(broken)


def rel(document, rel_type, source, target):
    return next(
        r
        for r in document["relationships"]
        if (r["type"], r["source"], r["target"]) == (rel_type, source, target)
    )


def test_yaml_loads_expected_shape(document):
    assert document["domain"]["id"] == "finance-genie-fraud-memory"
    labels = {e["label"] for e in document["entity_types"]}
    assert labels == {
        "Analyst",
        "Team",
        "InvestigationFocus",
        "Account",
        "Customer",
        "Merchant",
        "Community",
        "IdentityCluster",
        "PhoneNumber",
        "Address",
        "Case",
    }
    assert len(document["relationships"]) == 15


def test_shipped_ontology_is_valid(document):
    assert apply_ontology.validate_ontology(document) == []


def test_every_entity_description_has_a_negative_case(document):
    for entity in document["entity_types"]:
        assert "not a" in entity["description"].lower(), entity["label"]


def load_scenarios():
    path = (
        Path(__file__).resolve().parent.parent
        / "traffic"
        / "nams_traffic"
        / "scenarios.py"
    )
    spec = importlib.util.spec_from_file_location("nams_traffic_scenarios", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["nams_traffic_scenarios"] = module
    spec.loader.exec_module(module)
    return module


def test_team_aliases_match_what_the_traffic_sends(document):
    scenarios = load_scenarios()
    team = next(e for e in document["entity_types"] if e["label"] == "Team")
    assert team["aliases"] == {
        canonical: [abbreviation]
        for canonical, abbreviation in zip(
            scenarios.TEAMS, scenarios.TEAM_ABBREVIATIONS, strict=True
        )
    }
    forms = [f for values in team["aliases"].values() for f in values]
    assert forms == list(scenarios.TEAM_ABBREVIATIONS)


def test_team_description_lists_the_short_forms(document):
    scenarios = load_scenarios()
    team = next(e for e in document["entity_types"] if e["label"] == "Team")
    description = " ".join(team["description"].split())
    for abbreviation in scenarios.TEAM_ABBREVIATIONS:
        assert abbreviation in description


def test_shipped_shape_decisions(document):
    entities = {e["label"]: e for e in document["entity_types"]}
    assert entities["InvestigationFocus"]["pole_type"] == "OBJECT"
    assert "CASE-4001" in entities["Case"]["description"]
    assert "manager" in entities["Analyst"]["description"]
    assert rel(document, "FOCUSES_ON", "Analyst", "InvestigationFocus")


def test_rejects_duplicate_label(document):
    problems = problems_for(
        document, lambda d: d["entity_types"].append(dict(d["entity_types"][0]))
    )
    assert any("duplicate entity label" in p for p in problems)


def test_rejects_bad_pole_type(document):
    def mutate(d):
        d["entity_types"][0]["pole_type"] = "THING"

    assert any("pole_type" in p for p in problems_for(document, mutate))


def test_rejects_undeclared_endpoint(document):
    def mutate(d):
        d["relationships"][0]["target"] = "Nonexistent"

    assert any("not a declared entity type" in p for p in problems_for(document, mutate))


def test_rejects_duplicate_triple(document):
    problems = problems_for(
        document, lambda d: d["relationships"].append(dict(d["relationships"][0]))
    )
    assert any("duplicate relationship triple" in p for p in problems)


def test_rejects_allow_self_when_endpoints_differ(document):
    def mutate(d):
        rel(d, "MEMBER_OF", "Analyst", "Team")["allow_self"] = True

    assert any("allow_self" in p for p in problems_for(document, mutate))


def test_allows_allow_self_when_endpoints_match(document):
    def mutate(d):
        rel(d, "SIMILAR_TO", "Account", "Account")["allow_self"] = True

    assert problems_for(document, mutate) == []


def test_inverse_pair_that_mirrors_passes(document):
    def mutate(d):
        rel(d, "MEMBER_OF", "Analyst", "Team")["inverse"] = "HAS_MEMBER"
        d["relationships"].append(
            {"type": "HAS_MEMBER", "source": "Team", "target": "Analyst"}
        )

    assert problems_for(document, mutate) == []


def test_rejects_inverse_that_does_not_mirror(document):
    def mutate(d):
        rel(d, "MEMBER_OF", "Analyst", "Team")["inverse"] = "HAS_MEMBER"
        d["relationships"].append(
            {"type": "HAS_MEMBER", "source": "Analyst", "target": "Team"}
        )

    assert any("inverse" in p for p in problems_for(document, mutate))


def test_rejects_missing_inverse_relationship(document):
    def mutate(d):
        rel(d, "MEMBER_OF", "Analyst", "Team")["inverse"] = "HAS_MEMBER"

    assert any("inverse" in p for p in problems_for(document, mutate))


def test_rejects_lowercase_relationship_type(document):
    def mutate(d):
        d["relationships"][0]["type"] = "member_of"

    assert any("UPPER_SNAKE" in p for p in problems_for(document, mutate))


def test_rejects_bad_property_type(document):
    def mutate(d):
        d["entity_types"][0]["properties"] = [{"name": "age", "type": "boolean"}]

    assert any("property 'age'" in p for p in problems_for(document, mutate))


def test_lint_flags_missing_negative_case(document):
    document["entity_types"][0]["description"] = "A fraud analyst."
    warnings = apply_ontology.lint_ontology(document)
    assert any("negative case" in w for w in warnings)


def test_load_ontology_rejects_non_mapping(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(apply_ontology.OntologyError):
        apply_ontology.load_ontology(path)


def test_dry_run_makes_no_network_call(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("network used in dry run")

    monkeypatch.setattr(httpx, "Client", boom)
    monkeypatch.setattr(httpx, "request", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.delenv("MEMORY_API_KEY", raising=False)

    assert apply_ontology.main(["--yaml", str(YAML_PATH)]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "Local validation passed" in out


def test_invalid_yaml_stops_before_any_write(monkeypatch, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("domain: {id: x, name: y}\nentity_types: []\n")

    def boom(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx, "Client", boom)
    assert apply_ontology.main(["--yaml", str(bad), "--create"]) == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--activate"],
        ["--version-id", "ov_1"],
        ["--rollback", "ov_1", "--create"],
        ["--create", "--version-id", "ov_1", "--activate"],
        ["--update", "ont_1", "--create"],
        ["--update", "ont_1", "--version-id", "ov_1"],
        ["--rollback", "ov_1", "--update", "ont_1"],
    ],
)
def test_invalid_flag_combinations_exit(argv):
    with pytest.raises(SystemExit):
        apply_ontology.main(argv)


class FakeClient:
    """Stands in for httpx.Client and records each request."""

    calls: list[tuple[str, str, dict | None]] = []
    active_body: dict = {}
    stored: dict = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def request(self, method, path, json=None):
        FakeClient.calls.append((method, path, json))
        if (method, path) == ("GET", "/v1/ontologies/active"):
            body = FakeClient.active_body
        elif (method, path) == ("POST", "/v1/ontologies"):
            FakeClient.stored = json["ontology"]
            body = {"id": "ov_new", "ontology_id": "ont_new", "revision": 1}
        elif (method, path) == ("PUT", "/v1/ontologies/ont_x"):
            FakeClient.stored = json["ontology"]
            body = {"id": "ov_rev4", "ontology_id": "ont_x", "revision": 4}
        elif method == "GET" and "/versions/" in path:
            body = {"schema_json": dumps(FakeClient.stored)}
        else:
            body = {"id": json["version_id"], "ontology_id": "ont_new", "revision": 1}
        return httpx.Response(200, json=body)

    def close(self):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.calls = []
    FakeClient.stored = {}
    FakeClient.active_body = {
        "version": {"id": "ov_old", "ontology_id": "ont_x", "revision": 3}
    }
    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setenv("MEMORY_API_KEY", "nams_secret_value")
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", Path("."))
    return FakeClient


def test_create_posts_permissive_and_does_not_activate(fake_client, capsys):
    assert apply_ontology.main(["--yaml", str(YAML_PATH), "--create"]) == 0
    assert [(m, p) for m, p, _ in fake_client.calls] == [
        ("POST", "/v1/ontologies"),
        ("GET", "/v1/ontologies/ont_new/versions/1"),
    ]
    body = fake_client.calls[0][2]
    assert body["validation_mode"] == "permissive"
    assert body["ontology"]["domain"]["id"] == "finance-genie-fraud-memory"
    out = capsys.readouterr().out
    assert "ov_new" in out
    assert "nams_secret_value" not in out


def test_create_and_activate_saves_previous_version_first(
    fake_client, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", tmp_path)
    args = ["--yaml", str(YAML_PATH), "--create", "--activate"]
    assert apply_ontology.main(args) == 0
    sequence = [(m, p) for m, p, _ in fake_client.calls]
    assert sequence == [
        ("GET", "/v1/ontologies/active"),
        ("POST", "/v1/ontologies"),
        ("GET", "/v1/ontologies/ont_new/versions/1"),
        ("POST", "/v1/ontologies/active"),
    ]
    assert fake_client.calls[3][2] == {"version_id": "ov_new"}
    saved = list(tmp_path.glob("previous_active_*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text())["version_id"] == "ov_old"
    assert "nams_secret_value" not in capsys.readouterr().out


def test_rollback_records_current_then_activates(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", tmp_path)
    assert apply_ontology.main(["--yaml", str(YAML_PATH), "--rollback", "ov_old"]) == 0
    assert [(m, p) for m, p, _ in fake_client.calls] == [
        ("GET", "/v1/ontologies/active"),
        ("POST", "/v1/ontologies/active"),
    ]
    assert fake_client.calls[1][2] == {"version_id": "ov_old"}


def test_write_flag_without_key_fails_before_any_request(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx, "Client", boom)
    monkeypatch.delenv("MEMORY_API_KEY", raising=False)
    monkeypatch.setattr(apply_ontology, "DEFAULT_ENV_FILE", tmp_path / "missing.env")
    assert apply_ontology.main(["--yaml", str(YAML_PATH), "--create"]) == 3


def test_parse_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# c\nMEMORY_API_KEY='abc'\nexport MEMORY_ENDPOINT=https://x.test\n")
    assert apply_ontology.parse_env_file(env) == {
        "MEMORY_API_KEY": "abc",
        "MEMORY_ENDPOINT": "https://x.test",
    }


def test_settings_repr_hides_key():
    settings = apply_ontology.Settings(api_key="nams_secret", endpoint="https://x")
    assert "nams_secret" not in repr(settings)


def test_round_trip_clean_reports_nothing_dropped(fake_client, capsys):
    assert apply_ontology.main(["--yaml", str(YAML_PATH), "--create"]) == 0
    out = capsys.readouterr().out
    assert "returned everything we sent" in out
    assert "Dropped by the service" not in out


def mock_nams(monkeypatch, handler):
    """Route NamsClient through an httpx.MockTransport."""
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setenv("MEMORY_API_KEY", "nams_secret_value")
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", Path("."))


def lossy_handler(document, requests):
    """A service that drops aliases, one OWNS and one INVESTIGATES edge."""
    stored = copy.deepcopy(document)
    for entity in stored["entity_types"]:
        entity.pop("aliases", None)
        if entity["label"] == "InvestigationFocus":
            entity["pole_type"] = "EVENT"
        if entity["label"] == "Case":
            entity["description"] = "A case."
    stored["relationships"] = [
        r
        for r in stored["relationships"]
        if (r["type"], r["source"], r["target"])
        not in {
            ("OWNS", "Customer", "Account"),
            ("INVESTIGATES", "Case", "Community"),
        }
    ]

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                201, json={"id": "ov_new", "ontology_id": "ont_new", "revision": 1}
            )
        return httpx.Response(200, json={"schema_json": json.dumps(stored)})

    return handler


def test_round_trip_reports_dropped_items_without_failing(
    monkeypatch, document, capsys
):
    requests = []
    mock_nams(monkeypatch, lossy_handler(document, requests))
    assert apply_ontology.main(["--yaml", str(YAML_PATH), "--create"]) == 0
    out = capsys.readouterr().out
    assert "Dropped by the service" in out
    assert "alias 'Northwind Fraud Ops' (for 'Northwind Bank Fraud Operations')" in out
    assert "alias 'Tailspin Card Investigations'" in out
    assert "InvestigationFocus: pole_type changed" in out
    assert "Case: description changed" in out
    assert "relationship OWNS (Customer -> Account): missing" in out
    assert "relationship INVESTIGATES (Case -> Community): missing" in out
    # Same type on other endpoint pairs survived and must not be reported.
    assert "OWNS (Analyst -> Case)" not in out
    assert "INVESTIGATES (Analyst -> Community)" not in out
    assert "relationship PART_OF" not in out
    assert "nams_secret_value" not in out
    assert requests == [
        ("POST", "/v1/ontologies"),
        ("GET", "/v1/ontologies/ont_new/versions/1"),
    ]


def test_diff_flags_every_service_rewrite(document):
    returned = copy.deepcopy(document)
    returned["entity_types"] = [
        e for e in returned["entity_types"] if e["label"] != "Merchant"
    ]
    returned["extraction_aliases"] = {"Northwind Fraud Ops": "Team"}
    drops = apply_ontology.diff_round_trip(document, returned)
    assert "entity type Merchant: missing" in drops
    # An alias kept via extraction_aliases is not reported as dropped.
    assert not any("Northwind Fraud Ops" in d for d in drops if "alias" in d)


def test_round_trip_read_failure_does_not_fail_create(monkeypatch, capsys):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                201, json={"id": "ov_new", "ontology_id": "ont_new", "revision": 1}
            )
        return httpx.Response(500, text="boom")

    mock_nams(monkeypatch, handler)
    assert apply_ontology.main(["--yaml", str(YAML_PATH), "--create"]) == 0
    assert "Round trip skipped" in capsys.readouterr().out


def test_update_puts_a_new_revision_and_never_posts_or_activates(
    fake_client, capsys
):
    args = ["--yaml", str(YAML_PATH), "--update", "ont_x"]
    assert apply_ontology.main(args) == 0
    assert [(m, p) for m, p, _ in fake_client.calls] == [
        ("PUT", "/v1/ontologies/ont_x"),
        ("GET", "/v1/ontologies/ont_x/versions/4"),
    ]
    assert fake_client.calls[0][2]["validation_mode"] == "permissive"
    out = capsys.readouterr().out
    assert "ov_rev4" in out
    assert "revision=4" in out


def test_update_and_activate_records_previous_first(
    fake_client, monkeypatch, tmp_path
):
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", tmp_path)
    args = ["--yaml", str(YAML_PATH), "--update", "ont_x", "--activate"]
    assert apply_ontology.main(args) == 0
    assert [(m, p) for m, p, _ in fake_client.calls] == [
        ("GET", "/v1/ontologies/active"),
        ("PUT", "/v1/ontologies/ont_x"),
        ("GET", "/v1/ontologies/ont_x/versions/4"),
        ("POST", "/v1/ontologies/active"),
    ]
    assert fake_client.calls[3][2] == {"version_id": "ov_rev4"}


def test_dry_run_does_not_touch_update_path(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("network used in dry run")

    monkeypatch.setattr(httpx, "Client", boom)
    assert apply_ontology.main(["--yaml", str(YAML_PATH)]) == 0


def test_activation_with_no_active_version_records_null(
    fake_client, monkeypatch, tmp_path, capsys
):
    fake_client.active_body = {}
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", tmp_path)
    args = ["--yaml", str(YAML_PATH), "--create", "--activate"]
    assert apply_ontology.main(args) == 0
    sequence = [(m, p) for m, p, _ in fake_client.calls]
    assert sequence[0] == ("GET", "/v1/ontologies/active")
    assert sequence[-1] == ("POST", "/v1/ontologies/active")
    saved = json.loads(next(tmp_path.glob("previous_active_*.json")).read_text())
    assert saved["version_id"] is None
    assert saved["about_to_activate"] == "<new>"
    out = capsys.readouterr().out
    assert "No ontology is currently active" in out
    assert "not possible" in out


def test_rollback_to_none_snapshot_is_refused_without_network(
    fake_client, tmp_path, capsys
):
    snapshot = tmp_path / "previous_active_20260101T000000Z.json"
    snapshot.write_text(json.dumps({"version_id": None}))
    for target in (str(snapshot), "none"):
        argv = ["--yaml", str(YAML_PATH), "--rollback", target]
        assert apply_ontology.main(argv) == 3
    assert fake_client.calls == []
    assert "unbind" in capsys.readouterr().err


def test_rollback_accepts_a_snapshot_file_with_a_version(
    fake_client, monkeypatch, tmp_path
):
    snapshot = tmp_path / "previous_active_20260101T000000Z.json"
    snapshot.write_text(json.dumps({"version_id": "ov_old"}))
    monkeypatch.setattr(apply_ontology, "SCRIPT_DIR", tmp_path)
    argv = ["--yaml", str(YAML_PATH), "--rollback", str(snapshot)]
    assert apply_ontology.main(argv) == 0
    assert fake_client.calls[-1] == (
        "POST",
        "/v1/ontologies/active",
        {"version_id": "ov_old"},
    )

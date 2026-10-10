import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ontology" / "measure_ingestion.py"
_spec = importlib.util.spec_from_file_location("measure_ingestion", SCRIPT)
mi = importlib.util.module_from_spec(_spec)
sys.modules["measure_ingestion"] = mi
_spec.loader.exec_module(mi)


def ents(*pairs: tuple[str, str]) -> list[dict]:
    return [{"name": n, "type": t} for n, t in pairs]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Contoso Payments Risk team", "contoso payments risk"),
        ("Synthetic Analyst 0001", "analyst 0001"),
        ("synthetic analyst 0001", "analyst 0001"),
        ("Dr Smith", "dr smith"),  # would leave one token, so left alone
        ("Dr. Jane Smith", "jane smith"),
        ("Fabrikam, Inc.", "fabrikam"),
        ("neo4j-mcp-server", "neo4j mcp server"),
        ("team", "team"),
        ("Analyst 0003", "analyst 0003"),
        ("Analyst 3", "analyst 3"),
    ],
)
def test_normalize_name(raw, expected):
    assert mi.normalize_name(raw) == expected


def test_normalize_does_not_merge_ambiguous_names():
    assert mi.normalize_name("J. Smith") != mi.normalize_name("John Smith")
    assert mi.normalize_name("Tailspin Card Services Investigations team") != (
        mi.normalize_name("Tailspin Card Services")
    )


def test_count_by_type_and_generic_share():
    e = ents(("a", "Object"), ("b", "Concept"), ("c", "Person"), ("d", "Person"))
    assert mi.count_by_type(e) == {"Person": 2, "Concept": 1, "Object": 1}
    assert mi.generic_bucket_share(e) == {"count": 2, "share": 0.5}
    assert mi.generic_bucket_share([]) == {"count": 0, "share": 0.0}


def test_duplicates_are_same_type_only_with_pole_slots():
    e = ents(
        ("Synthetic Analyst 0001", "Person"),
        ("synthetic analyst 0001", "Person"),
        ("Analyst 0001", "Person"),
        ("Fabrikam", "Organization"),
        ("Fabrikam team", "Organization"),
        ("Account", "Object"),
        ("Account", "Concept"),
    )
    d = mi.duplicate_surface_forms(e)
    assert d["by_type"]["Person"]["groups"] == 1
    assert d["by_type"]["Person"]["excess"] == 2
    assert d["by_type"]["Organization"]["groups"] == 1
    # Same name under different types is a conflict, not a duplicate.
    assert "Object" not in d["by_type"]
    assert d["groups"] == 2 and d["excess"] == 3
    assert d["by_type"]["Person"]["examples"][0]["count"] == 3
    # Default-ontology labels map to poles through the built-in table.
    assert d["by_pole"]["PERSON"]["groups"] == 1
    assert d["by_pole"]["ORGANIZATION"]["groups"] == 1


def test_duplicates_empty_still_reports_pole_slots():
    d = mi.duplicate_surface_forms([])
    assert d["by_type"] == {}
    assert d["by_pole"]["PERSON"]["groups"] == 0
    assert d["by_pole"]["ORGANIZATION"]["groups"] == 0


def test_duplicate_poles_follow_custom_ontology_types():
    # Under the custom ontology people are Analyst/Customer and orgs Team/Merchant, so
    # a Person/Organization-keyed count would read 0 and fake an improvement.
    poles = {"Analyst": "PERSON", "Customer": "PERSON", "Team": "ORGANIZATION"}
    e = ents(
        ("Maya Okafor", "Analyst"),
        ("maya okafor", "Analyst"),
        ("Contoso Payments Risk", "Team"),
        ("Contoso Payments Risk team", "Team"),
    )
    d = mi.duplicate_surface_forms(e, type_poles=poles)
    assert d["by_pole"]["PERSON"]["groups"] == 1
    assert d["by_pole"]["ORGANIZATION"]["groups"] == 1
    # Without the pole map the custom labels are unknown and the pole rows read 0.
    assert mi.duplicate_surface_forms(e)["by_pole"]["PERSON"]["groups"] == 0
    flat = mi.flatten_metrics(mi.compute_metrics(e, None, poles))
    assert flat["duplicate groups: pole PERSON"] == 1
    assert flat["duplicate groups: pole ORGANIZATION"] == 1
    assert "duplicate groups: Person" not in flat


def test_entities_expose_no_pole_type_in_real_payload():
    sample = Path(
        "/private/tmp/claude-502/-Users-ryanknight-projects-databricks-graph-on-databricks"
        "/082757c8-a77e-4a97-a3b6-acc178bf257f/scratchpad/ents_all.json"
    )
    if not sample.is_file():
        pytest.skip("scratchpad sample not present")
    entities = json.loads(sample.read_text())
    assert all("pole_type" not in e for e in entities)
    assert mi.pole_of({"type": "Person"}) == "PERSON"
    assert mi.pole_of({"type": "Analyst"}, {"Analyst": "PERSON"}) == "PERSON"
    assert mi.pole_of({"type": "Analyst"}) is None


def test_type_conflicts():
    e = ents(("Account", "Object"), ("account", "Concept"), ("Loan", "Object"))
    c = mi.type_conflicts(e)
    assert c["count"] == 1
    assert c["examples"][0] == {"key": "account", "types": {"Concept": 1, "Object": 1}}


@pytest.mark.parametrize(
    "name",
    [
        "neo4j-mcp-server-target___read_neo4j_cypher",
        "Neo4j-MCP server",
        "get_neo4j_schema",
        "HAS_PHONE relationships",
        "Table",
        "column",
        "NODE",
        "risk_score",
        "community_id",
        "HAS_ADDRESS",
    ],
)
def test_noise_positive(name):
    assert mi.noise_reason(name) is not None


@pytest.mark.parametrize(
    "name",
    ["Account", "Fabrikam Financial Crimes", "Louvain", "risk score", "Account 12"],
)
def test_noise_negative(name):
    assert mi.noise_reason(name) is None


def test_noise_entities_summary():
    e = ents(
        ("risk_score", "Object"), ("Table", "Concept"), ("Fabrikam", "Organization")
    )
    n = mi.noise_entities(e)
    assert n["count"] == 2
    assert n["share"] == pytest.approx(0.6667, abs=1e-4)
    assert n["by_reason"] == {"bare_identifier": 1, "schema_word": 1}


def test_instance_coverage_counts_distinct():
    e = ents(
        ("Account 123", "Object"),
        ("account 123", "Object"),
        ("Account 456", "Object"),
        ("Community 7", "Concept"),
        ("Identity cluster 9", "Concept"),
        ("Phone 555-123-4567", "Object"),
        ("5551234567890", "Object"),  # no dashes, not a phone
        ("case 42", "Event"),
        ("CASE-4001", "Event"),
        ("case 4001", "Event"),
        ("Accounts overview", "Concept"),
    )
    cov = mi.instance_coverage(e)
    assert cov["account"]["distinct"] == 2 and cov["account"]["entities"] == 3
    assert cov["community"]["distinct"] == 1
    assert cov["identity_cluster"]["distinct"] == 1
    assert cov["phone"]["distinct"] == 1
    # "case 42" plus CASE-4001 and case 4001 (the same case id).
    assert cov["case"]["distinct"] == 2
    assert cov["case"]["entities"] == 3


def test_case_pattern_matches_canonical_case_id():
    cov = mi.instance_coverage(ents(("CASE-4001", "Case")))
    assert cov["case"]["distinct"] == 1
    assert cov["case"]["examples"] == ["case 4001"]
    assert mi.INSTANCE_PATTERNS["case"].search("own case CASE-4001, our")
    assert not mi.INSTANCE_PATTERNS["case"].search("showcase 4001")


def test_phone_requires_exact_digit_runs():
    cov = mi.instance_coverage(ents(("1555-123-45678", "Object")))
    assert cov["phone"]["distinct"] == 0


def test_ontology_conformance():
    e = ents(("a", "Person"), ("b", "Object"), ("c", "servicetool"), ("d", "Account"))
    c = mi.ontology_conformance(e, ["Person", "Account", "ServiceTool"])
    assert c["conforming"] == 2 and c["fraction"] == 0.5
    assert mi.ontology_conformance(e, None) is None


def test_load_declared_types(tmp_path):
    f = tmp_path / "o.yaml"
    f.write_text(
        "name: x\n"
        "entity_types:\n"
        "  - label: Account\n"
        "    description: foo\n"
        "  - label: 'Person'\n"
        "relationship_types:\n"
        "  - label: TRANSFERRED_TO\n"
    )
    assert mi.load_declared_types(f) == ["Account", "Person"]
    assert mi.load_declared_types(tmp_path / "missing.yaml") is None


def test_verdict_and_compare_table():
    assert mi.verdict(1, 2) == "up"
    assert mi.verdict(2, 1) == "down"
    assert mi.verdict(1.0, 1.0) == "unchanged"
    assert mi.verdict(None, 1) == "n/a"

    before = mi.build_snapshot(
        "before",
        ents(("a", "Object"), ("b", "Concept"), ("Account 1", "Object")),
        None,
        {"version_id": "ov_a", "name": "agent-memory", "revision": 1},
        "test",
        None,
        None,
    )
    after = mi.build_snapshot(
        "after",
        ents(("Account 1", "Account"), ("Account 2", "Account")),
        ["Account"],
        {"version_id": "ov_b", "name": "finance", "revision": 3},
        "test",
        None,
        None,
    )
    text = mi.format_compare(before, after)
    lines = {ln.split("  ")[0].strip(): ln for ln in text.splitlines()}
    assert lines["total entities"].split()[-1] == "down"
    assert lines["instances distinct: account"].split()[-1] == "up"
    assert lines["ontology conformance"].split()[-1] == "n/a"
    assert lines["type count: Object"].split()[-1] == "down"
    assert "success" not in text.lower()
    assert "ontology_version_id before: ov_a" in text
    assert "ontology_version_id after:  ov_b" in text
    assert "WARNING" not in text


def test_compare_flags_identical_ontology_version_ids():
    snap = mi.build_snapshot(
        "x", ents(("a", "Object")), None, {"version_id": "ov_same"}, "t", None, None
    )
    text = mi.format_compare(snap, snap)
    assert "WARNING: both snapshots have the SAME ontology_version_id" in text
    none = mi.build_snapshot("n", [], None, None, "t", None, None)
    assert none["ontology_version_id"] == "none"
    assert "SAME" in mi.format_compare(none, none)
    old = {k: v for k, v in snap.items() if k != "ontology_version_id"}
    text = mi.format_compare(old, snap)
    assert "SAME" not in text and "predates" in text


def _mock_client(handler):
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(wrapped),
        headers={"Authorization": "Bearer secret"},
    )
    return client, seen


def test_fetch_all_entities_paginates_with_get_only():
    def handler(req):
        if req.url.params.get("cursor") == "c2":
            return httpx.Response(
                200, json={"entities": [{"id": 3}], "next_cursor": None}
            )
        return httpx.Response(
            200, json={"entities": [{"id": 1}, {"id": 2}], "next_cursor": "c2"}
        )

    client, seen = _mock_client(handler)
    assert [e["id"] for e in mi.fetch_all_entities(client)] == [1, 2, 3]
    assert {r.method for r in seen} == {"GET"}
    assert seen[0].url.params["limit"] == "200"


def test_fetch_active_ontology_reads_version_object():
    def handler(req):
        assert req.url.path == "/v1/ontologies/active"
        return httpx.Response(
            200,
            json={
                "ontology": {
                    "domain": {"id": "finance", "name": "Finance Genie"},
                    "entity_types": [
                        {"label": "Analyst", "pole_type": "PERSON"},
                        {"label": "Team", "pole_type": "ORGANIZATION"},
                    ],
                },
                "version": {"id": "ov_9", "ontology_id": "ont_1", "revision": 4},
            },
        )

    client, seen = _mock_client(handler)
    assert mi.fetch_active_ontology(client) == {
        "version_id": "ov_9",
        "ontology_id": "ont_1",
        "revision": 4,
        "name": "Finance Genie",
        "domain_id": "finance",
        "type_poles": {"Analyst": "PERSON", "Team": "ORGANIZATION"},
    }
    assert {r.method for r in seen} == {"GET"}


def test_fetch_active_ontology_without_version_is_none():
    client, _ = _mock_client(lambda req: httpx.Response(200, json={}))
    assert mi.fetch_active_ontology(client)["version_id"] == "none"
    client, _ = _mock_client(lambda req: httpx.Response(404, json={}))
    assert mi.fetch_active_ontology(client)["version_id"] == "none"


def test_fetch_relationships_uses_graph_endpoint():
    def handler(req):
        assert req.url.path == "/v1/entities/graph"
        assert req.url.params["limit"] == "1000"
        return httpx.Response(
            200,
            json={
                "nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [{"sourceId": "a", "targetId": "b", "type": "MEMBER_OF"}],
            },
        )

    client, seen = _mock_client(handler)
    edges, note = mi.fetch_relationships(client)
    assert len(edges) == 1 and note is None
    assert {r.method for r in seen} == {"GET"}

    big = {"nodes": [{"id": str(i)} for i in range(1000)], "edges": []}
    client, _ = _mock_client(lambda req: httpx.Response(200, json=big))
    assert "capped" in mi.fetch_relationships(client)[1]


def _workspace_handler(turns: int, traces: int | None = None, assistants=None):
    """Mock NAMS holding `turns` one-turn conversations."""
    traces = turns if traces is None else traces
    assistants = turns if assistants is None else assistants
    ids = [f"c{i}" for i in range(turns)]

    def handler(req):
        path = req.url.path
        if path == "/v1/conversations":
            return httpx.Response(200, json={"conversations": [{"id": i} for i in ids]})
        if path.endswith("/messages"):
            cid = path.split("/")[3]
            msgs = [{"role": "user"}]
            if ids.index(cid) < assistants:
                msgs.append({"role": "assistant"})
            return httpx.Response(200, json={"messages": msgs})
        if path.startswith("/v1/reasoning/trace/"):
            cid = path.rsplit("/", 1)[1]
            steps = [{"id": "s"}] if ids.index(cid) < traces else []
            return httpx.Response(200, json={"steps": steps, "toolCalls": []})
        if path.endswith("/extraction-status"):
            return httpx.Response(200, json={"messages": [{"status": "done"}]})
        if path == "/v1/entities":
            return httpx.Response(
                200,
                json={"entities": [{"id": "e1", "name": "Maya Okafor", "type": "Person"}]},
            )
        if path == "/v1/entities/count":
            return httpx.Response(200, json={"count": 1})
        if path == "/v1/ontologies/active":
            return httpx.Response(
                200, json={"ontology": {}, "version": {"id": "ov_1", "revision": 2}}
            )
        if path == "/v1/entities/graph":
            return httpx.Response(200, json={"nodes": [{"id": "e1"}], "edges": []})
        return httpx.Response(404, json={})

    return handler


def test_fetch_completeness_counts_and_check():
    client, seen = _mock_client(_workspace_handler(3, traces=2, assistants=2))
    counts = mi.fetch_completeness(client)
    assert counts == {
        "conversations": 3,
        "user_messages": 3,
        "assistant_messages": 2,
        "traces": 2,
    }
    assert {r.method for r in seen} == {"GET"}
    assert mi.check_completeness(counts, None) == []
    problems = mi.check_completeness(counts, 3)
    assert len(problems) == 2
    assert any("assistant messages: expected 3, found 2" in p for p in problems)
    assert any("reasoning traces" in p for p in problems)
    assert mi.check_completeness({**counts, "assistant_messages": 3, "traces": 3}, 3) == []


def _run_network_snapshot(monkeypatch, handler, argv):
    client, _ = _mock_client(handler)
    monkeypatch.setattr(mi, "resolve_settings", lambda env: ("k", "https://x.test"))
    monkeypatch.setattr(mi, "make_client", lambda key, endpoint: client)
    return mi.main(argv)


def test_snapshot_expect_turns_mismatch_exits_3_and_writes_nothing(
    monkeypatch, tmp_path, capsys
):
    out = tmp_path / "s.json"
    code = _run_network_snapshot(
        monkeypatch,
        _workspace_handler(3, assistants=2),
        ["snapshot", "--label", "t", "--out", str(out), "--expect-turns", "3"],
    )
    assert code == 3 and not out.exists()
    err = capsys.readouterr().err
    assert "assistant messages: expected 3, found 2" in err


def test_snapshot_allow_incomplete_and_full_snapshot_contents(
    monkeypatch, tmp_path
):
    out = tmp_path / "s.json"
    code = _run_network_snapshot(
        monkeypatch,
        _workspace_handler(3, assistants=2),
        [
            "snapshot", "--label", "t", "--out", str(out),
            "--expect-turns", "3", "--allow-incomplete",
        ],
    )
    assert code == 0
    snap = json.loads(out.read_text())
    assert snap["ontology_version_id"] == "ov_1"
    assert snap["ontology_revision"] == 2
    assert snap["completeness"] == {
        "conversations": 3,
        "user_messages": 3,
        "assistant_messages": 2,
        "traces": 3,
        "expected_turns": 3,
    }
    assert snap["entities"][0]["name"] == "Maya Okafor"
    assert snap["relationships"] == []


def test_snapshot_complete_workspace_passes(monkeypatch, tmp_path):
    out = tmp_path / "s.json"
    code = _run_network_snapshot(
        monkeypatch,
        _workspace_handler(2),
        ["snapshot", "--label", "t", "--out", str(out), "--expect-turns", "2"],
    )
    assert code == 0


def test_wait_for_extraction_polls_until_done():
    polls = {"n": 0}

    def handler(req):
        path = req.url.path
        if path == "/v1/conversations":
            return httpx.Response(
                200, json={"conversations": [{"id": "c1"}, {"id": "c2"}]}
            )
        if path.endswith("/c1/extraction-status"):
            polls["n"] += 1
            status = "processing" if polls["n"] < 3 else "done"
            return httpx.Response(200, json={"messages": [{"status": status}]})
        return httpx.Response(200, json={"messages": [{"status": "failed"}]})

    client, seen = _mock_client(handler)
    out = mi.wait_for_extraction(
        client, 60, 1, sleep=lambda s: None, clock=lambda: 0.0, log=lambda m: None
    )
    assert out == {"waited": True, "conversations": 2, "failed_messages": 1}
    assert {r.method for r in seen} == {"GET"}
    # c2 settled on the first poll and is not polled again.
    assert sum(1 for r in seen if r.url.path.endswith("/c2/extraction-status")) == 1


def test_wait_for_extraction_times_out():
    def handler(req):
        if req.url.path == "/v1/conversations":
            return httpx.Response(200, json={"conversations": [{"id": "c1"}]})
        return httpx.Response(200, json={"messages": [{"status": "pending"}]})

    client, _ = _mock_client(handler)
    ticks = iter(range(0, 1000, 10))
    with pytest.raises(mi.ExtractionTimeout):
        mi.wait_for_extraction(
            client,
            25,
            1,
            sleep=lambda s: None,
            clock=lambda: next(ticks),
            log=lambda m: None,
        )


def test_api_get_retries_then_fails_without_leaking_key():
    client, seen = _mock_client(lambda req: httpx.Response(500))
    with pytest.raises(SystemExit) as exc:
        mi.api_get(client, "/v1/entities", sleep=lambda s: None)
    assert "secret" not in str(exc.value)
    assert len(seen) == 4


def test_resolve_settings_env_over_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MEMORY_API_KEY=from-file\nMEMORY_ENDPOINT=https://file.test\n")
    key, endpoint = mi.resolve_settings({"MEMORY_API_KEY": "from-env"}, env_file)
    assert (key, endpoint) == ("from-env", "https://file.test")
    with pytest.raises(SystemExit):
        mi.resolve_settings({}, tmp_path / "none.env")
    assert mi.resolve_settings({"MEMORY_API_KEY": "k"}, tmp_path / "none.env")[1] == (
        "https://memory.neo4jlabs.com"
    )


def test_snapshot_and_compare_cli_from_file(tmp_path, capsys):
    src = tmp_path / "ents.json"
    src.write_text(json.dumps(ents(("Account 1", "Object"), ("risk_score", "Concept"))))
    out = tmp_path / "snap.json"
    assert (
        mi.main(
            ["snapshot", "--label", "t", "--out", str(out), "--from-file", str(src)]
        )
        == 0
    )
    snap = json.loads(out.read_text())
    assert snap["entity_count"] == 2 and snap["label"] == "t"
    assert snap["metrics"]["noise"]["count"] == 1
    assert mi.main(["compare", str(out), str(out)]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_snapshot_keeps_raw_data_and_recompute_is_offline(tmp_path, monkeypatch):
    src = tmp_path / "ents.json"
    src.write_text(
        json.dumps(
            {
                "entities": ents(("Maya Okafor", "Analyst"), ("risk_score", "Concept")),
                "relationships": [{"sourceId": "a", "targetId": "b", "type": "X"}],
            }
        )
    )
    out = tmp_path / "snap.json"
    assert (
        mi.main(["snapshot", "--label", "t", "--out", str(out), "--from-file", str(src)])
        == 0
    )
    snap = json.loads(out.read_text())
    assert len(snap["entities"]) == 2 and len(snap["relationships"]) == 1
    assert snap["ontology_version_id"] == "none"

    # Tamper with the stored metrics, then recompute with the network disabled.
    snap["metrics"]["noise"]["count"] = 99
    snap["ontology_type_poles"] = {"Analyst": "PERSON"}
    out.write_text(json.dumps(snap))

    def no_network(*a, **k):
        raise AssertionError("recompute must not touch the network")

    monkeypatch.setattr(mi, "make_client", no_network)
    monkeypatch.setattr(mi.httpx, "Client", no_network)
    out2 = tmp_path / "new.json"
    assert mi.main(["recompute", str(out), "--out", str(out2)]) == 0
    new = json.loads(out2.read_text())
    assert new["metrics"]["noise"]["count"] == 1
    assert new["metrics"]["duplicates"]["by_pole"]["PERSON"]["groups"] == 0
    assert new["entities"] == snap["entities"] and "recomputed_at" in new
    with pytest.raises(SystemExit):
        mi.recompute_snapshot({"label": "no entities"})


def test_load_declared_poles(tmp_path):
    f = tmp_path / "o.yaml"
    f.write_text(
        "entity_types:\n"
        "  - label: Analyst\n"
        "    pole_type: PERSON\n"
        "  - label: Team\n"
        "    pole_type: ORGANIZATION\n"
        "    aliases:\n"
        '      "A": ["B"]\n'
        "relationships:\n"
        "  - type: MEMBER_OF\n"
    )
    assert mi.load_declared_poles(f) == {"Analyst": "PERSON", "Team": "ORGANIZATION"}
    assert mi.load_declared_types(f) == ["Analyst", "Team"]
    assert mi.load_declared_poles(tmp_path / "none.yaml") == {}


# ---------------------------------------------------------------------------
# Gold scoring
# ---------------------------------------------------------------------------

SCENARIOS = SimpleNamespace(
    ANALYSTS=("Maya Okafor", "Daniel Reyes"),
    MANAGERS=("Rebecca Thornton", "Victor Salazar"),
    TEAMS=("Contoso Payments Risk", "Fabrikam Financial Crimes"),
    TEAM_ABBREVIATIONS=("Contoso Risk", "Fabrikam FinCrimes"),
)
PROMPTS = [
    "I am Maya Okafor on the Contoso Payments Risk team. My focus is x. "
    "I report to Rebecca Thornton. I own case CASE-4001, our investigation of "
    "Community 3040. Please remember that. Is Account 7321 near Serrano LLC?",
    "Back again, it is Maya. Continue. Which customers share 312-555-0142?",
    "Back again, this is M. Okafor. Continue. Barton Inc and Thompson-Caldwell?",
    "Back again from Contoso Risk. Continue.",
]
CUSTOM_POLES = {
    "Analyst": "PERSON",
    "Customer": "PERSON",
    "Team": "ORGANIZATION",
    "Merchant": "ORGANIZATION",
}


def test_derive_gold_from_prompts():
    gold = mi.derive_gold(PROMPTS, SCENARIOS)
    assert gold.entities["Analyst"] == ["Maya Okafor"]  # Daniel is never mentioned
    assert gold.entities["Manager"] == ["Rebecca Thornton"]
    assert gold.entities["Team"] == ["Contoso Payments Risk"]
    assert gold.entities["Case"] == ["CASE-4001"]
    assert gold.entities["Community"] == ["Community 3040"]
    assert gold.entities["Account"] == ["Account 7321"]
    assert gold.entities["Phone"] == ["312-555-0142"]
    assert gold.entities["Merchant"] == [
        "Serrano LLC",
        "Barton Inc",
        "Thompson-Caldwell",
    ]
    assert gold.aliases == [
        ("analyst_first_name", "Maya Okafor", "Maya"),
        ("analyst_initial_surname", "Maya Okafor", "M. Okafor"),
        ("team_abbreviation", "Contoso Payments Risk", "Contoso Risk"),
    ]
    assert gold.relationships == [
        ("MEMBER_OF", "Maya Okafor", "Contoso Payments Risk"),
        ("REPORTS_TO", "Maya Okafor", "Rebecca Thornton"),
        ("OWNS", "Maya Okafor", "CASE-4001"),
        ("INVESTIGATES", "CASE-4001", "Community 3040"),
    ]


def _custom_snapshot(entities, relationships=None):
    return {
        "label": "after",
        "ontology_domain_id": "finance-genie-fraud-memory",
        "ontology_type_poles": CUSTOM_POLES,
        "entities": entities,
        "relationships": relationships,
    }


def test_score_gold_custom_ontology_types_and_recall():
    entities = [
        {"id": "1", "name": "Maya Okafor", "type": "Analyst"},
        {"id": "2", "name": "Rebecca Thornton", "type": "Customer"},
        {"id": "3", "name": "Contoso Payments Risk", "type": "Object"},  # wrong type
        {"id": "4", "name": "CASE-4001", "type": "Case"},
        {"id": "5", "name": "Community 3040", "type": "Community"},
        {"id": "6", "name": "Account 7321", "type": "Account"},
        {"id": "7", "name": "Serrano LLC", "type": "Merchant"},
    ]
    gold = mi.derive_gold(PROMPTS, SCENARIOS)
    s = mi.score_gold(_custom_snapshot(entities), gold)
    assert s["ontology_kind"] == "custom"
    assert s["entities"]["Analyst"]["recall"] == 1.0
    assert s["entities"]["Manager"]["type_ok"] == 1  # Analyst-or-Customer accepted
    assert s["entities"]["Team"]["found"] == 1 and s["entities"]["Team"]["type_ok"] == 0
    assert s["entities"]["Phone"]["found"] == 0
    assert s["entities"]["Merchant"]["found"] == 1
    assert s["entities"]["Merchant"]["gold"] == 3
    assert s["overall"]["gold"] == 10 and s["overall"]["found"] == 7
    assert s["overall"]["type_ok"] == 6
    assert s["relationships"] == {
        "measurable": False,
        "reason": "snapshot has no relationships",
    }
    assert "not measurable" in mi.format_gold(s)


def test_score_gold_default_ontology_uses_pole_types():
    entities = [
        {"id": "1", "name": "Maya Okafor", "type": "Person"},
        {"id": "2", "name": "Contoso Payments Risk team", "type": "Organization"},
        {"id": "3", "name": "Account 7321", "type": "Concept"},  # OBJECT pole
        {"id": "4", "name": "Serrano LLC", "type": "Person"},  # wrong pole
    ]
    gold = mi.derive_gold(PROMPTS, SCENARIOS)
    snap = {"label": "before", "entities": entities, "relationships": None}
    s = mi.score_gold(snap, gold)
    assert s["ontology_kind"] == "default"
    assert s["entities"]["Analyst"]["type_ok"] == 1
    assert s["entities"]["Team"]["type_ok"] == 1
    assert s["entities"]["Account"]["type_ok"] == 1
    assert s["entities"]["Merchant"]["found"] == 1
    assert s["entities"]["Merchant"]["type_ok"] == 0


def test_score_gold_alias_resolution():
    gold = mi.derive_gold(PROMPTS, SCENARIOS)
    entities = [
        {"id": "1", "name": "Maya Okafor", "type": "Analyst"},
        {"id": "2", "name": "Maya", "type": "Person"},  # split alias
        {"id": "3", "name": "Contoso Payments Risk", "type": "Team"},
    ]
    a = mi.score_gold(_custom_snapshot(entities), gold)["aliases"]
    assert a["by_kind"]["analyst_first_name"]["split"] == 1
    assert a["by_kind"]["analyst_initial_surname"]["resolved"] == 1
    assert a["by_kind"]["team_abbreviation"]["resolved"] == 1
    assert (a["resolved"], a["measurable"]) == (2, 3)

    # Listed alias counts as resolved even with a separate entity present.
    entities[0]["aliases"] = ["Maya"]
    a = mi.score_gold(_custom_snapshot(entities), gold)["aliases"]
    assert a["by_kind"]["analyst_first_name"]["resolved"] == 1

    a = mi.score_gold(_custom_snapshot([]), gold)["aliases"]
    assert a["measurable"] == 0 and a["rate"] is None
    assert a["by_kind"]["team_abbreviation"]["canonical_missing"] == 1


def test_score_gold_relationships_connected_vs_typed():
    gold = mi.derive_gold(PROMPTS, SCENARIOS)
    entities = [
        {"id": "a", "name": "Maya Okafor", "type": "Analyst"},
        {"id": "t", "name": "Contoso Payments Risk", "type": "Team"},
        {"id": "m", "name": "Rebecca Thornton", "type": "Analyst"},
        {"id": "c", "name": "CASE-4001", "type": "Case"},
        {"id": "k", "name": "Community 3040", "type": "Community"},
    ]
    edges = [
        {"sourceId": "a", "targetId": "t", "type": "MEMBER_OF"},
        {"sourceId": "m", "targetId": "a", "type": "RELATES_TO"},  # wrong type, direction
        {"sourceId": "a", "targetId": "c", "type": "RELATES_TO", "predicate": "owns"},
    ]
    r = mi.score_gold(_custom_snapshot(entities, edges), gold)["relationships"]
    rows = r["by_relationship"]
    assert rows["Analyst MEMBER_OF Team"]["typed"] == 1
    assert rows["Analyst REPORTS_TO Manager"]["connected"] == 1
    assert rows["Analyst REPORTS_TO Manager"]["typed"] == 0
    assert rows["Analyst OWNS Case"]["typed"] == 1  # original name kept in predicate
    assert rows["Case INVESTIGATES Community"]["connected"] == 0
    flat = mi.flatten_gold(mi.score_gold(_custom_snapshot(entities, edges), gold))
    assert flat["gold rel typed: Analyst MEMBER_OF Team"] == 1.0
    assert flat["gold rel connected: Case INVESTIGATES Community"] == 0.0
    text = mi.format_gold(mi.score_gold(_custom_snapshot(entities, edges), gold))
    assert "Analyst MEMBER_OF Team" in text and "OVERALL" in text


def test_gold_with_real_scenarios_and_cli(tmp_path, capsys):
    ents_ = [
        {"id": "1", "name": "Maya Okafor", "type": "Analyst"},
        {"id": "2", "name": "CASE-4001", "type": "Case"},
    ]
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps(_custom_snapshot(ents_)))
    assert mi.DEFAULT_SCENARIOS.is_file()
    gold = mi.gold_for_run(mi.DEFAULT_SCENARIOS, 2, 2, 2)
    assert "CASE-4001" in gold.entities["Case"] and "CASE-4002" in gold.entities["Case"]
    assert gold.entities["Analyst"][0] == "Maya Okafor"
    code = mi.main(
        ["gold", "--snapshot", str(snap), "--users", "2", "--sessions", "2",
         "--turns", "2"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "OVERALL" in out and "alias resolution" in out


def test_compare_includes_gold_rows(tmp_path, capsys):
    before = tmp_path / "b.json"
    after = tmp_path / "a.json"
    for path, ents_, kind in (
        (before, [{"id": "1", "name": "Maya Okafor", "type": "Person"}], "d"),
        (after, [{"id": "1", "name": "Maya Okafor", "type": "Analyst"}], "c"),
    ):
        snap = mi.build_snapshot(
            kind, ents_, None, {"version_id": f"ov_{kind}", "domain_id": (
                "nams-default" if kind == "d" else "custom"
            )}, "t", None, None
        )
        path.write_text(json.dumps(snap))
    argv = ["compare", str(before), str(after), "--users", "1", "--sessions", "1",
            "--turns", "1"]
    assert mi.main(argv) == 0
    out = capsys.readouterr().out
    assert "gold recall: overall" in out and "gold alias resolution" in out
    assert "ontology_version_id before: ov_d" in out
    with pytest.raises(SystemExit):
        mi.main(["compare", str(before), str(after), "--users", "1"])

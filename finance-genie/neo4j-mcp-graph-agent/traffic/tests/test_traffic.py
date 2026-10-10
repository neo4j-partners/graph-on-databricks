import re
import threading

import pytest

from nams_traffic.client import TurnFailed
from nams_traffic.cli import main, parse_args, run_traffic
from nams_traffic.scenarios import ANALYSTS, CASES, FOCUSES, build_requests


def test_build_requests_is_deterministic_and_complete():
    first = build_requests(3, 2, 4, "abc")
    assert first == build_requests(3, 2, 4, "abc")
    assert len(first) == 3 * 2 * 4
    assert first[0].user_id == "nams-load-abc-user-0001"
    assert first[0].session_id == "nams-load-abc-u0001-s001"
    assert [r.turn for r in first[:4]] == [0, 1, 2, 3]


def test_invocation_ids_are_unique_per_turn_and_stable_per_run():
    requests = build_requests(2, 2, 3, "abc")
    ids = [r.invocation_id for r in requests]
    assert len(set(ids)) == len(ids)
    assert ids != [r.invocation_id for r in build_requests(2, 2, 3, "other")]


def test_only_a_users_first_turn_states_the_persona():
    requests = build_requests(1, 2, 2, "abc")
    first, later_turn, new_session, _ = requests
    assert f"I am {ANALYSTS[0]} on the" in first.prompt
    assert "Please remember that" in first.prompt
    assert "synthetic analyst" not in first.prompt
    assert "I am " not in later_turn.prompt
    assert "I am " not in new_session.prompt
    assert new_session.prompt.startswith("Back again")


def test_users_rotate_through_the_focuses():
    requests = build_requests(len(FOCUSES) + 1, 1, 1, "abc")
    focuses = {r.prompt.split("My focus is ")[1].split(".")[0] for r in requests}
    assert focuses == {focus for focus, *_ in FOCUSES}


def test_prompt_text_does_not_depend_on_the_run_id():
    first = build_requests(6, 3, 4, "before")
    second = build_requests(6, 3, 4, "after")
    assert [r.prompt for r in first] == [r.prompt for r in second]
    assert [r.user_id for r in first] != [r.user_id for r in second]
    assert [r.session_id for r in first] != [r.session_id for r in second]
    assert all("before" not in r.prompt and "after" not in r.prompt for r in first)


def test_first_session_states_manager_and_owned_case():
    first = build_requests(1, 1, 1, "abc")[0].prompt
    assert "I report to " in first
    assert re.search(r"I own case CASE-\d+, our investigation of Community \d+\.", first)


def test_later_sessions_refer_to_the_analyst_by_aliases():
    requests = build_requests(1, 4, 1, "abc")
    openings = [r.prompt for r in requests[1:]]
    assert "it is Maya." in openings[0]
    assert "this is M. Okafor." in openings[1]
    # User 1 is on Contoso, so the team alias appears instead of the full team name.
    assert "from Contoso Risk." in openings[2]
    assert all("Maya Okafor" not in prompt for prompt in openings)


def _alias_kind(prompt: str) -> str:
    if "Back again, it is " in prompt:
        return "first_name"
    if re.search(r"Back again, this is [A-Z]\. ", prompt):
        return "initial_surname"
    if "Back again from " in prompt:
        return "team_abbreviation"
    raise AssertionError(prompt)


def test_two_sessions_per_user_still_use_every_alias_variant():
    requests = build_requests(6, 2, 1, "abc")
    openers = [r.prompt for r in requests if r.session_id.endswith("s002")]
    assert len(openers) == 6
    assert {_alias_kind(prompt) for prompt in openers} == {
        "first_name",
        "initial_surname",
        "team_abbreviation",
    }
    assert openers == [
        r.prompt for r in build_requests(6, 2, 1, "other") if r.session_id.endswith("s002")
    ]


def test_user_prompts_contain_no_schema_identifiers():
    prompts = [r.prompt for r in build_requests(6, 2, 2, "abc")]
    snake_case = re.compile(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b")
    relationships = ("TRANSACTED_WITH", "TRANSFERRED_TO", "SIMILAR_TO")
    for prompt in prompts:
        assert not snake_case.search(prompt), prompt
        assert not any(name in prompt for name in relationships), prompt
        for word in ("risk_score", "betweenness_centrality", "identity_cluster", "similarity_score"):
            assert word not in prompt, prompt


def test_analyst_names_are_realistic_and_cycle():
    assert len(ANALYSTS) >= 8
    assert all(" " in name and "synthetic" not in name for name in ANALYSTS)
    requests = build_requests(len(ANALYSTS) + 1, 1, 1, "abc")
    assert ANALYSTS[0] in requests[0].prompt
    assert ANALYSTS[0] in requests[-1].prompt


def test_instance_questions_name_real_graph_identifiers():
    prompts = " ".join(r.prompt for r in build_requests(20, 3, 4, "abc"))
    identifiers = ("Community 3040", "Account 7890", "Account 7321", "312-555-0142", "Serrano LLC")
    for identifier in identifiers:
        assert identifier in prompts


def test_one_community_is_investigated_by_analysts_on_different_teams():
    requests = build_requests(len(CASES) + 1, 1, 1, "abc")
    owners: dict[str, set[str]] = {}
    for request in requests:
        team = re.search(r"on the (.+?) team", request.prompt).group(1)
        community = re.search(r"investigation of Community (\d+)", request.prompt).group(1)
        owners.setdefault(community, set()).add(team)
    assert any(len(teams) >= 2 for teams in owners.values())
    # The shared community is also asked about in later turns by each of its analysts.
    shared = next(c for c, teams in owners.items() if len(teams) >= 2)
    everything = build_requests(len(CASES) + 1, 1, 12, "abc")
    asking_users = {r.user_id for r in everything if f"Community {shared}" in r.prompt}
    assert len(asking_users) >= 2


def test_run_traffic_runs_every_turn_in_session_order():
    requests = build_requests(4, 2, 3, "abc")
    seen: list[tuple[str, int]] = []
    lock = threading.Lock()

    def invoke(request, stop):
        with lock:
            seen.append((request.session_id, request.turn))

    summary = run_traffic(requests, invoke, concurrency=3)
    assert (summary.ok, summary.failed, summary.skipped) == (len(requests), 0, 0)
    assert summary.exit_code == 0
    for session in {s for s, _ in seen}:
        assert [t for s, t in seen if s == session] == [0, 1, 2]


def test_a_failure_stops_the_run_by_default():
    requests = build_requests(1, 1, 4, "abc")

    def invoke(request, stop):
        if request.turn == 1:
            raise TurnFailed("boom")

    summary = run_traffic(requests, invoke, concurrency=1)
    assert (summary.ok, summary.failed, summary.skipped) == (1, 1, 2)
    assert summary.exit_code == 1


def test_continue_after_error_finishes_the_run():
    requests = build_requests(1, 1, 4, "abc")

    def invoke(request, stop):
        if request.turn == 1:
            raise TurnFailed("boom")

    summary = run_traffic(requests, invoke, concurrency=1, continue_after_error=True)
    assert (summary.ok, summary.failed, summary.skipped) == (3, 1, 0)


def test_retries_reuse_the_same_invocation_id():
    requests = build_requests(1, 1, 1, "abc")
    attempts: list[str] = []

    def invoke(request, stop):
        attempts.append(request.invocation_id)
        if len(attempts) < 2:
            raise TurnFailed("flaky")

    summary = run_traffic(requests, invoke, concurrency=1, retry_attempts=2)
    assert summary.ok == 1
    assert len(attempts) == 2 and len(set(attempts)) == 1


def test_default_is_a_single_attempt():
    requests = build_requests(1, 1, 1, "abc")
    calls = []

    def invoke(request, stop):
        calls.append(1)
        raise TurnFailed("down")

    run_traffic(requests, invoke, concurrency=1)
    assert len(calls) == 1


def test_dry_run_needs_no_app_url_and_makes_no_calls(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)
    assert main(["--dry-run", "--users", "2", "--sessions-per-user", "1"]) == 0


def test_app_url_is_required_for_a_real_run(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)
    with pytest.raises(SystemExit):
        parse_args([])
    assert parse_args(["--app-url", "https://x"]).app_url == "https://x"


def test_counts_must_be_positive():
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--users", "0"])


def test_service_principal_client_reads_credentials_from_the_scope(monkeypatch):
    import base64
    from types import SimpleNamespace

    from nams_traffic import client as client_module

    secrets = {"client-id": "the-id", "client-secret": "the-secret"}

    class FakeSecrets:
        def get_secret(self, scope, key):
            assert scope == "creds"
            return SimpleNamespace(value=base64.b64encode(secrets[key].encode()).decode())

    built = {}
    monkeypatch.setattr(
        client_module, "WorkspaceClient", lambda **kwargs: built.update(kwargs) or "sp-client"
    )
    workspace = SimpleNamespace(secrets=FakeSecrets(), config=SimpleNamespace(host="https://h"))
    assert client_module.service_principal_client(workspace, "creds") == "sp-client"
    assert built == {
        "host": "https://h",
        "client_id": "the-id",
        "client_secret": "the-secret",
        "auth_type": "oauth-m2m",
    }

import httpx

from nams_traffic import cli
from nams_traffic.cli import Summary, find_memory_settings, report
from nams_traffic.verify import (
    missing_turns,
    stored_by_session,
    verify_stored,
    wait_until_ready,
)


def conversation(session):
    return {"id": f"c-{session}", "metadata": {"client_session_id": session}}


def test_missing_turns_reports_only_incomplete_sessions():
    expected = {"run-a": 2, "run-b": 2, "run-c": 1}
    stored = {"run-a": 2, "run-b": 1}
    assert missing_turns(expected, stored) == {"run-b": 1, "run-c": 1}


def test_stored_by_session_pages_and_ignores_other_runs():
    pages = {
        "": {
            "conversations": [conversation("run-a"), conversation("other-a")],
            "next_cursor": "p2",
        },
        "p2": {"conversations": [conversation("run-a"), {"id": "no-metadata"}]},
    }

    def handler(request):
        return httpx.Response(200, json=pages[request.url.params.get("cursor", "")])

    client = httpx.Client(base_url="https://nams", transport=httpx.MockTransport(handler))
    assert stored_by_session(client, "run-") == {"run-a": 2}


def test_verify_stored_polls_until_the_write_lands(monkeypatch):
    responses = iter([[], [conversation("run-a")]])

    def handler(request):
        return httpx.Response(200, json={"conversations": next(responses)})

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    sleeps = []
    missing = verify_stored(
        {"run-a": 1}, "run-", "key", wait_seconds=60, sleep=sleeps.append
    )
    assert missing == {} and len(sleeps) == 1


def test_verify_stored_gives_up_after_the_wait(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            **kwargs,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        ),
    )
    assert verify_stored({"run-a": 2}, "run-", "key", wait_seconds=0) == {"run-a": 2}


def mock_httpx(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )


def test_wait_until_ready_needs_two_good_answers_in_a_row(monkeypatch):
    statuses = iter([424, 200, 424, 200, 200])
    mock_httpx(monkeypatch, lambda r: httpx.Response(next(statuses)))
    sleeps = []
    wait_until_ready("key", sleep=sleeps.append)
    assert len(sleeps) == 4


def test_wait_until_ready_times_out(monkeypatch):
    import pytest

    mock_httpx(monkeypatch, lambda r: httpx.Response(424))
    with pytest.raises(TimeoutError):
        wait_until_ready("key", wait_seconds=0)


def test_exit_code_is_distinct_for_short_storage():
    assert Summary(ok=2).exit_code == 0
    assert Summary(ok=1, failed=1).exit_code == cli.EXIT_TURNS_FAILED
    assert Summary(ok=1, skipped=1).exit_code == cli.EXIT_TURNS_FAILED
    assert Summary(ok=2, missing={"s": 1}).exit_code == cli.EXIT_NAMS_SHORT
    assert Summary(ok=2, missing={}).exit_code == 0


def test_report_lists_each_error_and_each_lost_turn(caplog):
    summary = Summary(ok=3, errors=["s1 turn=0: boom"], missing={"s2": 1})
    summary.ok_by_session["s2"] = 2
    with caplog.at_level("ERROR", logger="nams_traffic"):
        report(summary)
    text = caplog.text
    assert "FAILED s1 turn=0: boom" in text
    assert "NOT STORED s2: 1 of 2 turn(s)" in text


def test_memory_settings_prefer_the_environment_over_a_dotenv(tmp_path):
    (tmp_path / ".env").write_text("export MEMORY_API_KEY='from-file'\nMEMORY_ENDPOINT=https://e\n")
    assert find_memory_settings({}, [tmp_path]) == ("from-file", "https://e")
    assert find_memory_settings({"MEMORY_API_KEY": "env"}, [tmp_path])[0] == "env"
    assert find_memory_settings({}, [tmp_path / "missing"]) is None


def run_main(monkeypatch, *, ok_stored, extra=()):
    """Run main against a fake app, with NAMS holding ``ok_stored`` conversations."""
    monkeypatch.setattr(cli, "find_memory_settings", lambda env, dirs: ("key", "https://n"))

    class FakeApp:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, request, stop):
            return {}

        def close(self):
            pass

    monkeypatch.setattr(cli, "AppClient", FakeApp)
    monkeypatch.setattr(cli, "wait_until_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli,
        "verify_stored",
        lambda expected, prefix, key, endpoint: {
            s: n - ok_stored.get(s, n) for s, n in expected.items() if ok_stored.get(s, n) < n
        },
    )
    import databricks.sdk

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", lambda **kw: object())
    return cli.main(
        ["--app-url", "http://x", "--users", "1", "--sessions-per-user", "1",
         "--turns-per-session", "2", "--run-id", "r1", *extra]
    )


def test_main_exits_2_when_nams_stored_too_few_turns(monkeypatch):
    assert run_main(monkeypatch, ok_stored={"nams-load-r1-u0001-s001": 1}) == 2


def test_main_exits_0_when_every_turn_is_stored(monkeypatch):
    assert run_main(monkeypatch, ok_stored={}) == 0


def test_main_skips_the_check_with_no_verify_nams(monkeypatch):
    assert run_main(monkeypatch, ok_stored={"nams-load-r1-u0001-s001": 0},
                    extra=["--no-verify-nams"]) == 0


def test_verify_nams_without_a_key_fails(monkeypatch):
    monkeypatch.setattr(cli, "find_memory_settings", lambda env, dirs: None)
    assert cli.main(["--app-url", "http://x", "--verify-nams"]) == 1


def test_main_sends_no_turns_when_nams_is_not_ready(monkeypatch):
    monkeypatch.setattr(cli, "find_memory_settings", lambda env, dirs: ("key", "https://n"))

    def not_ready(*args, **kwargs):
        raise TimeoutError("down")

    monkeypatch.setattr(cli, "wait_until_ready", not_ready)
    assert cli.main(["--app-url", "http://x"]) == cli.EXIT_NAMS_SHORT

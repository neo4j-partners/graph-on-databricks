import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo = _load("demo")


def test_default_run_has_the_five_numbered_steps_in_order():
    assert [step.key for step in demo.select_steps(None)] == ["1", "2", "3", "4", "5"]


def test_ring_runs_only_when_asked_for():
    assert [step.key for step in demo.select_steps(["ring"])] == ["ring"]


def test_unknown_step_is_rejected():
    with pytest.raises(ValueError, match="unknown step '9'"):
        demo.select_steps(["9"])


def test_steps_one_and_three_start_new_sessions_and_four_stays_in_three():
    by_key = {step.key: step for step in demo.STEPS}

    assert by_key["1"].new_session
    assert not by_key["2"].new_session
    assert by_key["3"].new_session
    assert not by_key["4"].new_session


def test_body_carries_the_user_id_only_when_given():
    local = demo.build_body("hi", "s1", "demo-analyst", invocation_id="i1")
    cloud = demo.build_body("hi", "s1", None, invocation_id="i1")

    assert local == {
        "id": "i1",
        "session_id": "s1",
        "input": {
            "messages": [{"role": "user", "content": "hi"}],
            "user_id": "demo-analyst",
        },
    }
    assert "user_id" not in cloud["input"]


def test_answer_is_the_last_assistant_message():
    result = {
        "output": [
            {"role": "assistant", "content": "first"},
            {"role": "tool", "content": "ignored"},
            {"role": "assistant", "content": "last"},
        ]
    }

    assert demo.extract_answer(result) == "last"


def test_answer_unwraps_the_deployed_app_payload():
    result = {"output": {"output": [{"role": "assistant", "content": "wrapped"}]}}

    assert demo.extract_answer(result) == "wrapped"


def test_answer_falls_back_to_the_raw_payload():
    assert "oops" in demo.extract_answer({"error": "oops"})


def test_ask_sends_the_routing_key_and_returns_the_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["routing_key"] = request.headers["x-routing-key"]
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        return httpx.Response(
            200, json={"output": [{"role": "assistant", "content": "ok"}]}
        )

    with httpx.Client(
        base_url="http://agent", transport=httpx.MockTransport(handler)
    ) as http:
        answer = demo.ask(http, {"Authorization": "Bearer t"}, "q", "s1", None)

    assert answer == "ok"
    assert seen == {
        "routing_key": "s1",
        "auth": "Bearer t",
        "path": "/api/invocations",
    }

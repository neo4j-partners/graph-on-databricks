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
        turn = demo.ask(http, {"Authorization": "Bearer t"}, "q", "s1", None)

    assert turn.answer == "ok"
    assert turn.calls == ()
    assert seen == {
        "routing_key": "s1",
        "auth": "Bearer t",
        "path": "/api/invocations",
    }


GRAPH_THEN_GENIE = {
    "output": {
        "output": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "name": "neo4j-mcp-server-target___read_neo4j_cypher",
                        "args": {"query": "MATCH (p:Phone)<-[:HAS_PHONE]-(c) RETURN c"},
                    }
                ],
            },
            {"role": "tool", "name": "read_neo4j_cypher", "content": "[...]"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "name": "genie_ask",
                        "args": {"question": "Balances of 368 and 927?"},
                    },
                    {"name": "genie_poll", "args": {}},
                ],
            },
            {"role": "assistant", "content": "Accounts 368 and 927 ..."},
        ]
    }
}


def test_tool_calls_are_labeled_with_their_source_in_order():
    calls = demo.extract_tool_calls(GRAPH_THEN_GENIE)

    assert [(call.source, call.name) for call in calls] == [
        (demo.GRAPH, "read_neo4j_cypher"),
        (demo.LAKEHOUSE, "genie_ask"),
        (demo.LAKEHOUSE, "genie_poll"),
    ]
    assert calls[0].detail == "MATCH (p:Phone)<-[:HAS_PHONE]-(c) RETURN c"
    assert calls[1].detail == '"Balances of 368 and 927?"'


def test_answer_skips_the_empty_tool_call_messages():
    assert demo.extract_answer(GRAPH_THEN_GENIE) == "Accounts 368 and 927 ..."


def test_route_collapses_repeated_sources():
    calls = demo.extract_tool_calls(GRAPH_THEN_GENIE)

    assert demo.route_of(calls) == (demo.GRAPH, demo.LAKEHOUSE)
    assert demo.format_route(demo.route_of(calls)) == "Graph -> Lakehouse"
    assert demo.format_route(()) == "no tools"


def test_route_check_compares_sources_and_the_first_one():
    by_key = {step.key: step for step in demo.STEPS}

    assert demo.route_result(by_key["5"], (demo.GRAPH, demo.LAKEHOUSE)) == "as expected"
    assert (
        demo.route_result(by_key["5"], (demo.GRAPH, demo.LAKEHOUSE, demo.GRAPH))
        == "as expected"
    )
    assert demo.route_result(by_key["5"], (demo.GRAPH,)) == "different"
    assert demo.route_result(by_key["4"], (demo.GRAPH,)) == "different"
    assert demo.route_result(by_key["3"], ()) == "not checked"

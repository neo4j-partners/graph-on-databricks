"""Check the graph facts that the prompt and traffic scenarios hard-code. Opt-in, read-only.

This calls the MCP service in `agent.toml` with your Databricks profile and exits 1 on drift.

    uv run python scripts/check_drift.py
"""

import asyncio
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = ROOT / "traffic" / "nams_traffic" / "scenarios.py"

# Facts that scenarios.py states only in a comment, so they are copied here.
HUB_COMMUNITIES = {7321: 22341, 15741: 22341, 13914: 22341, 15940: 19766}
HUB_MAX_RANK = 25  # A hub is in the top 25 by betweenness, as in the prompt's hub example.
SHARED_PHONES = ("312-555-0142", "312-555-0143")
MERCHANT_CATEGORIES = {"Serrano LLC": "gaming", "Gutierrez PLC": "online",
                       "Barton Inc": "travel", "Thompson-Caldwell": "retail"}

_NODE_RE = re.compile(r"^- (\w+) \{(.*?)\}", re.MULTILINE | re.DOTALL)
_REL_RE = re.compile(r"\((\w+)\)-\[:(\w+)(?: \{([^}]*)\})?\]->\((\w+)\)")
_NOTE_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")


@dataclass
class Schema:
    nodes: dict[str, set[str]]  # label -> property names
    rels: dict[tuple[str, str, str], set[str]]  # (start label, type, end label) -> properties


def _names(text: str) -> set[str]:
    """Property names from a `{a, b (note), c [x|y]}` body."""
    return {name.strip() for name in _NOTE_RE.sub("", text).split(",") if name.strip()}


def prompt_schema(prompt: str) -> Schema:
    """Parse the GRAPH SCHEMA block of the system prompt."""
    block = prompt.split("GRAPH SCHEMA", 1)[1].split("RULES", 1)[0]
    nodes_text, rels_text = block.split("Relationships:", 1)
    nodes = {label: _names(body) for label, body in _NODE_RE.findall(nodes_text)}
    rels = {
        (start, rel_type, end): _names(props)
        for start, rel_type, props, end in _REL_RE.findall(rels_text)
    }
    return Schema(nodes, rels)


def live_schema(payload: dict[str, Any]) -> Schema:
    """Parse the JSON that the MCP `get_neo4j_schema` tool returns."""
    nodes: dict[str, set[str]] = {}
    rels: dict[tuple[str, str, str], set[str]] = {}
    for label, entry in payload.items():
        if entry.get("type") != "node":
            continue
        nodes[label] = set(entry.get("properties", {}))
        for rel_type, rel in entry.get("relationships", {}).items():
            for other in rel.get("labels", []):
                outgoing = rel["direction"] == "out"
                key = (label, rel_type, other) if outgoing else (other, rel_type, label)
                rels.setdefault(key, set()).update(rel.get("properties", {}))
    return Schema(nodes, rels)


def schema_drift(expected: Schema, live: Schema) -> list[str]:
    """What the prompt names that the live graph does not have. Extra live items are fine."""
    problems = []
    for label, props in expected.nodes.items():
        if label not in live.nodes:
            problems.append(f"label {label} is missing")
        else:
            problems += [f"{label}.{p} is missing" for p in sorted(props - live.nodes[label])]
    for (start, rel_type, end), props in expected.rels.items():
        name = f"({start})-[:{rel_type}]->({end})"
        if (start, rel_type, end) not in live.rels:
            problems.append(f"relationship {name} is missing")
        else:
            missing = props - live.rels[(start, rel_type, end)]
            problems += [f"{name} property {p} is missing" for p in sorted(missing)]
    return problems


def load_scenarios() -> ModuleType:
    """Import scenarios.py by path. It belongs to the separate traffic project."""
    spec = importlib.util.spec_from_file_location("drift_scenarios", SCENARIOS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up while it loads
    spec.loader.exec_module(module)
    return module


def named_ids(scenarios: ModuleType) -> tuple[list[int], list[int]]:
    """Every "Account N" and "Community N" in the scenario questions and cases."""
    text = " ".join(q for _, generic, instance in scenarios.FOCUSES for q in generic + instance)
    accounts = {int(n) for n in re.findall(r"Account (\d+)", text)}
    communities = {int(n) for n in re.findall(r"Community (\d+)", text)}
    for case in scenarios.CASES:
        accounts.update(case.top_accounts)
        communities.add(case.community_id)
    return sorted(accounts), sorted(communities)


def fact_checks(scenarios: ModuleType) -> list[tuple[str, str, dict[str, Any]]]:
    """(description, query, params). Each query returns rows only for facts that fail."""
    accounts, communities = named_ids(scenarios)
    checks = [
        (
            "named accounts exist",
            "UNWIND $ids AS id OPTIONAL MATCH (a:Account {account_id: id}) "
            "WITH id, a WHERE a IS NULL RETURN id",
            {"ids": accounts},
        ),
        (
            "named communities exist",
            "UNWIND $ids AS c OPTIONAL MATCH (a:Account {community_id: c}) "
            "WITH c, count(a) AS members WHERE members = 0 RETURN c",
            {"ids": communities},
        ),
        (
            "hub accounts are in their community and in the top 25 by betweenness",
            "UNWIND keys($hubs) AS key "
            "OPTIONAL MATCH (h:Account {account_id: toInteger(key)}) "
            "OPTIONAL MATCH (o:Account) "
            "WHERE o.betweenness_centrality > h.betweenness_centrality "
            "WITH key, h, $hubs[key] AS expected, count(o) AS rank "
            "WHERE h IS NULL OR h.community_id <> expected OR rank >= $max_rank "
            "RETURN key AS account_id, h.community_id, expected, rank",
            {"hubs": {str(k): v for k, v in HUB_COMMUNITIES.items()}, "max_rank": HUB_MAX_RANK},
        ),
        (
            "phones are shared by several customers",
            "UNWIND $phones AS number "
            "OPTIONAL MATCH (c:Customer)-[:HAS_PHONE]->(:Phone {number: number}) "
            "WITH number, count(DISTINCT c) AS customers WHERE customers < 2 "
            "RETURN number, customers",
            {"phones": list(SHARED_PHONES)},
        ),
        (
            "merchants exist with their category",
            "UNWIND keys($merchants) AS name OPTIONAL MATCH (m:Merchant {merchant_name: name}) "
            "WITH name, $merchants[name] AS expected, collect(m.category) AS found "
            "WHERE NOT expected IN found RETURN name, expected, found",
            {"merchants": MERCHANT_CATEGORIES},
        ),
    ]
    for case in scenarios.CASES:
        checks.append((
            f"case Community {case.community_id} is a ring candidate holding its top accounts",
            "MATCH (a:Account {community_id: $c}) "
            "WITH count(a) AS members, avg(a.risk_score) AS avg_risk, collect(a.account_id) AS ids "
            "WHERE NOT (50 <= members <= 200 AND avg_risk >= 1.0) "
            "OR any(x IN $accounts WHERE NOT x IN ids) RETURN members, avg_risk",
            {"c": case.community_id, "accounts": list(case.top_accounts)},
        ))
    return checks


async def main() -> int:
    from agents.mcp import MCPServerManager
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    from agent.prompt import SYSTEM_PROMPT
    from databricks_agentkit.openai import mcp_servers

    async with MCPServerManager(await mcp_servers()) as manager:
        if not manager.active_servers:
            raise SystemExit(f"No MCP server connected: {dict(manager.errors)}")
        server = manager.active_servers[0]
        tools = {t.name.rpartition("___")[2]: t.name for t in await server.list_tools()}

        async def call(tool: str, arguments: dict[str, Any]) -> Any:
            result = await server.call_tool(tools[tool], arguments)
            return json.loads("".join(getattr(c, "text", "") for c in result.content))

        live = live_schema(await call("get_neo4j_schema", {}))
        drift = schema_drift(prompt_schema(SYSTEM_PROMPT), live)
        results = [("prompt schema matches the live graph", drift)]
        for description, query, params in fact_checks(load_scenarios()):
            rows = await call("read_neo4j_cypher", {"query": query, "params": params})
            results.append((description, rows))
    for description, found in results:
        print(f"{'FAIL' if found else 'ok  '} {description}")
        for item in found:
            print(f"     {item}")
    failures = sum(bool(found) for _, found in results)
    print(f"{failures} check(s) failed" if failures else "no drift")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

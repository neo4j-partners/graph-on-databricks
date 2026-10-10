# Reference

## Configuration

| Setting | Where to change it | Default |
| --- | --- | --- |
| NAMS key | `MEMORY_API_KEY` env var, or the `nams-api-key` app resource when deployed | Unset, so memory is off |
| NAMS endpoint and workspace | Optional `MEMORY_ENDPOINT` and `MEMORY_WORKSPACE_ID` env vars | The NAMS defaults |
| MCP service | `agent.toml` `[[tools]]` | `graph-on-databricks.finance_genie.finance_genie_mcp` |
| Model | `LLM_MODEL` env var | `system.ai.claude-sonnet-5-5` |
| Judge model | `JUDGE_MODEL` env var | `databricks:/databricks-claude-sonnet-5-5` |
| Session store | `agent.toml` `[session_store]` | `neo4j-mcp-graph-agent-sessions` |
| Tracing experiment | `agent.toml` `[tracing]` | `/Shared/agentbricks_traces/neo4j-mcp-graph-agent` |
| Traffic credentials scope | `credentials_scope` job parameter | `nams-traffic` |

- **Other MCP service:** Edit the `service` value in `agent.toml`, or run `agentbricks tools add mcp <service> --auth app`. Then deploy again.

## Agent, runtime, and guardrails

- **Runtime:** The app runs on Agent Bricks. It uses the OpenAI Agents SDK for the agent loop and `DurableAgentServer` for sync, streaming, and background calls with crash recovery.
- **History:** Agent Bricks keeps the session history for multi-turn chats and the MLflow traces.
- **Deploy grants:** `agentbricks deploy` creates the app and its stores. It also grants the app service principal `EXECUTE` on the MCP service, plus `USE_SCHEMA` and `USE_CATALOG` on its parents.
- **Graph tools:** The agent has two read-only graph tools, `get_neo4j_schema` and `read_neo4j_cypher`. Guardrails reject write Cypher, cut results at 8000 characters, and stop a run after 20 steps.
- **Cypher guardrail:** The Cypher guardrail also rejects admin clauses such as `GRANT`, `ALTER`, `USE`, and `STOP DATABASE`. It allows `CALL` only for subqueries and a short list of schema procedures: `db.labels`, `db.relationshipTypes`, `db.propertyKeys`, `db.schema.*`, and `apoc.meta.*`. The guardrail is a text check, so it is defense in depth and not the read-only boundary.
- **Genie tools:** The Genie tools are function tools, so the MCP allowlist and the Cypher guardrail do not apply to them. Genie is read-only.

Two files hold the agent logic. `agent/agent.py` builds the agent, loads the MCP server from `agent.toml`, and applies the guardrails. `agent/guardrails.py` defines them. `agent.toml` declares the MCP service and the Genie space as app-identity tools, a session store for multi-turn history, and the MLflow tracing experiment. The `runtime/` folder serves the agent at `/api/invocations`.

## Evaluate

```bash
uv run agent-evaluate
```

- **What it runs:** The agent answers the questions in `agent/evaluate.py`. MLflow scorers grade the answers.
- **Judges:** The judges use a Databricks-hosted model, set by `JUDGE_MODEL`. They use no external API key.
- **Graph and Genie question:** One question needs both the graph and Genie. Its scorer, `graph_and_genie_called`, checks only that both sources were called. It does not check Genie's answer.
- **Pass rule:** The run fails unless every case passes the safety and no-write checks.
- **NAMS:** The run never writes to NAMS.
- **Drift check:** Run `uv run python scripts/check_drift.py` after the graph is re-seeded. It compares the prompt's graph schema and the traffic scenarios' named accounts, communities, phones, and merchants with the live graph. It only reads, and it exits 1 on drift. It is not part of `pytest`.

## Develop and test

Run the tests and the CLI check from `neo4j-mcp-graph-agent/`.

```bash
uv sync
MLFLOW_DISABLE_AGENT_HINT=1 uv run pytest
agentbricks doctor .
```

## Delete the agent

```bash
agentbricks --profile "$DATABRICKS_CONFIG_PROFILE" deployments delete agent-bricks-neo4j-graph-agent
```

- **What it deletes:** The command deletes the app and, when managed provisioning is on, its runtime store.
- **What it keeps:** The grants on the MCP service and the MLflow tracing experiment stay in place.
- **Stop only:** Run `agentbricks deployments stop agent-bricks-neo4j-graph-agent` to stop the app without deleting it.

## Layout

```
agent.toml          MCP binding, session store, tracing
app.yaml            App start command and environment, such as MEMORY_TRUSTED_CALLERS
setup_secrets.sh    Writes the .env secrets to a Databricks secret scope
docs/               diagrams and the guides that the README links to
agent/              agent, system prompt, guardrails, NAMS memory, evaluation
runtime/            DurableAgentServer entrypoint, adapter, and memory identity middleware
tests/              guardrail, runtime and identity, memory, ontology, and drift check tests
traffic/            synthetic analyst traffic CLI and its Databricks Job bundle
ontology/           NAMS ontology, loader, measurement, and transcript replay scripts
scripts/            drift check of the prompt and scenarios against the live graph
```

## Notes

- **Beta CLI:** The Agent Bricks CLI is in Beta. Its README documents the grant behavior.
- **Grant fails:** If deploy cannot grant on the MCP service, grant by hand in Catalog Explorer. Open Permissions on the MCP service. Give the app's service principal `EXECUTE`, plus `USE_CATALOG` and `USE_SCHEMA` on its parents.
- **Backing resources:** The MCP service must be allowed to reach whatever backs it. Agent Bricks does not grant access to those resources.
- **Invocation ids across callers:** The memory identity is part of the saved request. So when a second caller reuses an invocation id, the app returns 409. This is expected.
- **Reading another caller's result:** The status and events routes, `GET /api/invocations/{id}` and `/events`, do not check who started the invocation. Any caller with `CAN_USE` on the app who knows another caller's invocation UUID can read that result. UUIDs are hard to guess. This is framework behavior in `databricks_agentkit`.
- **Responses API:** The agent calls the model through the Responses API. Chat completions streaming breaks on Claude 5 reasoning deltas in openai-agents 0.23.1.

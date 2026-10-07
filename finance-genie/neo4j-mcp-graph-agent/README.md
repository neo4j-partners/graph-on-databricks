# neo4j-mcp-graph-agent

A Databricks App agent that answers questions about the finance-genie fraud graph. It calls the
Unity Catalog MCP service `graph-on-databricks.finance_genie.finance_genie_mcp`, which fronts
Neo4j, as the app's own service principal.

It is built on the Agent Bricks runtime: the OpenAI Agents SDK for the agent loop, and
`DurableAgentServer` for sync, streaming, and background invocations with crash recovery.

## How it works

- `agent.toml` declares the MCP service as an app-identity tool, a session store for
  multi-turn history, and the MLflow tracing experiment.
- `agent/agent.py` builds the agent, loads the MCP server from `agent.toml`, and applies the
  guardrails in `agent/guardrails.py`: only `get_neo4j_schema` and `read_neo4j_cypher` are exposed, write
  Cypher is rejected, results are truncated at 8000 characters, and runs stop after 20 steps.
- `runtime/` serves the agent at `/api/invocations`.
- `agentbricks deploy` creates the app, creates the declared stores, and grants the app service
  principal `EXECUTE` on the MCP service plus `USE_SCHEMA` and `USE_CATALOG` on its parents.
  No manual grant is needed for the MCP service.

## Prerequisites

- Python 3.11+, [uv](https://docs.astral.sh/uv/), and the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install)
- The Agent Bricks CLI (Beta): `pip install databricks-agentbricks`, or run it with
  `uvx --from databricks-agentbricks agentbricks ...`
- A workspace with Databricks Apps and Unity Catalog AI Gateway enabled
- The MCP service `graph-on-databricks.finance_genie.finance_genie_mcp`, exposing the tools
  `get_neo4j_schema` and `read_neo4j_cypher`. TODO: link the MCP service creation doc.
- You need the right to grant `EXECUTE` on the MCP service (owner or `MANAGE`), since deploy
  grants it on behalf of the app

## Quick start

1. Install the Agent Bricks CLI with uv and confirm it runs:

   ```bash
   uv tool install databricks-agentbricks
   agentbricks --help
   ```

2. Create the profile environment variable first, then authenticate. Every command below that
   takes a profile uses this variable:

   ```bash
   databricks auth profiles                      # list your profiles
   export DATABRICKS_CONFIG_PROFILE=<your-profile>
   agentbricks login --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

3. Install and run the local checks:

   ```bash
   uv sync
   MLFLOW_DISABLE_AGENT_HINT=1 uv run pytest
   agentbricks doctor .
   ```

4. Run locally and ask a question. Use two terminal windows, because the server keeps running.

   In window 1, start the server:

   ```bash
   cp .env.example .env        # set DATABRICKS_CONFIG_PROFILE to the same value
   agentbricks dev             # serves http://localhost:8000
   ```

   In window 2, from this directory with `DATABRICKS_CONFIG_PROFILE` exported, ask a question:

   ```bash
   agentbricks endpoint invoke --url http://localhost:8000 --path /api/invocations \
     --json '{"id":"'$(uuidgen)'","session_id":"demo-1","input":[{"role":"user","content":"Which communities look like fraud ring candidates?"}]}'
   ```

5. Deploy. Databricks app names cap at 30 characters including the `agent-bricks-` prefix, so the
   deploy name must be 17 characters or fewer:

   ```bash
   agentbricks deploy neo4j-graph-agent
   agentbricks deployments get agent-bricks-neo4j-graph-agent   # URL and status
   ```

6. Test the deployed app:

   ```bash
   SESSION_ID=$(uuidgen)
   agentbricks --profile "$DATABRICKS_CONFIG_PROFILE" endpoint invoke agent-bricks-neo4j-graph-agent \
     --path /api/invocations --routing-key "$SESSION_ID" \
     --json '{"id":"'$(uuidgen)'","session_id":"'$SESSION_ID'","input":[{"role":"user","content":"What does the SIMILAR_TO relationship mean?"}]}'
   agentbricks deployments logs agent-bricks-neo4j-graph-agent
   ```

   Use a new `id` for every request and reuse `session_id` to continue a conversation.

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| MCP service | `agent.toml` `[[tools]]` | `graph-on-databricks.finance_genie.finance_genie_mcp` |
| Model | `LLM_MODEL` env var (`app.yaml` `env` when deployed) | `system.ai.claude-sonnet-5-5` |
| Session store | `agent.toml` `[session_store]` | `neo4j-mcp-graph-agent-sessions` |
| Tracing experiment | `agent.toml` `[tracing]` | `/Shared/agentbricks_traces/neo4j-mcp-graph-agent` |

To point at a different MCP service, edit the `service` value in `agent.toml` (or run
`agentbricks tools add mcp <service> --auth app`) and redeploy.

## Evaluate

```bash
uv run agent-evaluate
```

Runs the agent against the questions in `agent/evaluate.py` with MLflow scorers. The LLM judges
use a Databricks-hosted model (`JUDGE_MODEL`, default `databricks:/databricks-claude-sonnet-5-5`),
so no external API key is needed. The run fails
unless every case passes the safety and no-write checks.

## Delete the agent

```bash
agentbricks --profile "$DATABRICKS_CONFIG_PROFILE" deployments delete agent-bricks-neo4j-graph-agent
```

This deletes the app and, when managed provisioning is enabled, its runtime store. Use
`agentbricks deployments stop agent-bricks-neo4j-graph-agent` to stop it without deleting.
Grants on the MCP service and the MLflow tracing experiment are not removed by this command.

## Layout

```
agent.toml          MCP binding, session store, tracing
app.yaml            App start command
agent/              agent, system prompt, guardrails, evaluation
runtime/            DurableAgentServer entrypoint and adapter
tests/              guardrail and adapter tests
```

## Notes

- The Agent Bricks CLI is Beta and the grant behavior is documented in its README. If deploy
  reports that it cannot grant on the MCP service, grant manually in Catalog Explorer
  (Permissions on the MCP service) to the app's service principal: `EXECUTE`, plus `USE_CATALOG`
  and `USE_SCHEMA` on its parents.
- The MCP service must be allowed to reach whatever backs it. Agent Bricks does not grant access
  to resources an MCP service wraps.

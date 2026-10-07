# neo4j-mcp-graph-agent

Databricks App agent (OpenAI Agents SDK on the Agent Bricks runtime, `DurableAgentServer`).
See `README.md` for run and deploy.

- Runs as the app service principal. The MCP tool binding in `agent.toml` uses `auth = "app"`.
  Do not add on-behalf-of-user auth.
- The MCP service replaces the old UC HTTP connection. No AgentCore credentials or secrets
  belong in this project.
- `agent.toml` is the source of truth for the MCP binding, session store, and tracing.
  `app.yaml` holds the start command. There is no `databricks.yml`.
- The read-only and allowlist guardrails are safety controls, applied to the MCP server in
  `agent/guardrails.py` (`apply_mcp_guardrails`). Keep `tests/test_guardrails.py` passing.
- Do not run `databricks` or `agentbricks` commands that contact a workspace until the user has
  chosen a profile.
- Verify with `MLFLOW_DISABLE_AGENT_HINT=1 uv run pytest` and `agentbricks doctor .`.

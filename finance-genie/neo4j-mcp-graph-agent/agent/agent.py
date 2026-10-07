import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from agents import Agent, Runner, RunResultStreaming
from agents.mcp import MCPServerManager
from databricks_openai import AsyncDatabricksOpenAI

from agent.guardrails import MAX_AGENT_STEPS, apply_mcp_guardrails
from agent.prompt import SYSTEM_PROMPT
from databricks_agentkit import workspace_client, workspace_headers
from databricks_agentkit.openai import (
    configure_tracing,
    mcp_servers,
    session_store,
    start_trace,
)

logger = logging.getLogger(__name__)

# A Unity Catalog AI Gateway model service from the `system.ai` schema. Override with LLM_MODEL.
MODEL = os.environ.get("LLM_MODEL", "system.ai.claude-sonnet-4-5")


def configure() -> None:
    """Wire up global state; call once at server startup (not at import)."""
    from agents import set_default_openai_api, set_default_openai_client

    set_default_openai_client(
        AsyncDatabricksOpenAI(
            workspace_client=workspace_client(),
            default_headers=workspace_headers() or None,
            use_ai_gateway=True,
        )
    )
    set_default_openai_api("chat_completions")
    configure_tracing()


def create_agent(servers: list[Any]) -> Agent:
    return Agent(
        name="neo4j-mcp-graph-agent",
        instructions=SYSTEM_PROMPT,
        model=MODEL,
        mcp_servers=servers,
    )


@asynccontextmanager
async def run_agent(
    agent_input: list[Any], *, session_id: str
) -> AsyncIterator[RunResultStreaming]:
    """Run the agent and expose its native streaming result.

    The MCP servers come from `agent.toml`; each gets the allowlist and guardrails.
    """
    servers = await mcp_servers()
    for server in servers:
        apply_mcp_guardrails(server)
    async with MCPServerManager(servers) as manager:
        if not manager.active_servers:
            raise RuntimeError(f"No MCP server connected: {dict(manager.errors)}")
        agent = create_agent(list(manager.active_servers))
        with start_trace(name="invoke", inputs=agent_input, session_id=session_id) as span:
            result = Runner.run_streamed(
                agent,
                agent_input,
                session=session_store(session_id, session_id),
                max_turns=MAX_AGENT_STEPS,
            )
            yield result
            if span is not None:
                span.set_outputs({"output": result.final_output})

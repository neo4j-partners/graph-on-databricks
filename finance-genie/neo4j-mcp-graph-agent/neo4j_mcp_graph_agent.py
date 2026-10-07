"""Neo4j MCP tool-calling LangGraph agent for Databricks Model Serving."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Sequence
from typing import Any

import anyio
import httpx
import mlflow
import nest_asyncio
from databricks.sdk import WorkspaceClient
from databricks_langchain import (
    ChatDatabricks,
    DatabricksMCPServer,
    DatabricksMultiServerMCPClient,
)
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.tools import BaseTool, ToolException
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

nest_asyncio.apply()

LLM_ENDPOINT_NAME = os.environ.get("LLM_ENDPOINT_NAME", "databricks-claude-sonnet-5-5")
CONNECTION_NAME = os.environ.get("UC_CONNECTION_NAME", "neo4j_agentcore_mcp")
MCP_SERVER_NAME = os.environ.get("MCP_SERVER_NAME", "neo4j-mcp")
MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "20"))
TOOL_RESULT_MAX_CHARS = int(os.environ.get("TOOL_RESULT_MAX_CHARS", "8000"))
ALLOWED_TOOLS = frozenset(
    name.strip()
    for name in os.environ.get("ALLOWED_MCP_TOOLS", "get-schema,read-cypher").split(",")
    if name.strip()
)
READ_CYPHER_TOOL = "read-cypher"
TRUNCATION_MARKER = "[truncated]"

SYSTEM_PROMPT = """
You are a Neo4j MCP graph agent for a financial-fraud graph. Your only external
data source is the Neo4j MCP server exposed through the Databricks Unity Catalog
external connection. Use read-only Cypher only. Always add a LIMIT.

GRAPH SCHEMA
Nodes:
- Account {account_id, account_hash, account_name, account_type
  [checking|savings|business], region, balance, opened_date, holder_age,
  risk_score (PageRank over TRANSFERRED_TO), community_id (Louvain over
  TRANSFERRED_TO; fraud rings are dense communities), betweenness_centrality
  (high = broker/hub), similarity_score, identity_cluster_id,
  identity_cluster_size, shared_phone_count, shared_address_count}
- Merchant {merchant_id, merchant_name, category, region}
- Customer {customer_id, name, email, identity_cluster_id,
  identity_cluster_size, shared_phone_count, shared_address_count}
- Phone {number}
- Address {address}
Relationships:
- (Account)-[:TRANSFERRED_TO]->(Account)
- (Account)-[:TRANSACTED_WITH]->(Merchant)   (parallel edges are possible)
- (Account)-[:SIMILAR_TO {similarity_score}]->(Account)
- (Customer)-[:OWNS]->(Account)
- (Customer)-[:HAS_PHONE]->(Phone)
- (Customer)-[:HAS_ADDRESS]->(Address)

RULES
- Relationships have NO amount or timestamp properties. Never filter on them.
- There is no fraud label. A ring candidate is a community with 50 to 200
  members and average risk_score >= 1.0. Treat these as signals, not verdicts.
- If a label, relationship, or property is unclear, call get-schema before
  writing Cypher.
- Keep queries small and focused, explain results directly, and say when the
  graph does not contain enough evidence to answer.

EXAMPLES
Q: Which communities are the top ring candidates?
MATCH (a:Account) WHERE a.community_id IS NOT NULL
WITH a.community_id AS community_id, count(*) AS members,
     avg(a.risk_score) AS avg_risk
WHERE members >= 50 AND members <= 200 AND avg_risk >= 1.0
RETURN community_id, members, avg_risk ORDER BY avg_risk DESC LIMIT 10

Q: Which accounts act as hubs or brokers?
MATCH (a:Account) WHERE a.betweenness_centrality IS NOT NULL
WITH a ORDER BY a.betweenness_centrality DESC LIMIT 25
OPTIONAL MATCH (b:Account)-[r:TRANSFERRED_TO]->(a)
RETURN a.account_id, a.betweenness_centrality, count(DISTINCT b) AS senders,
       count(r) AS inbound_transfers
ORDER BY a.betweenness_centrality DESC

Q: Which account pairs look alike?
MATCH (a:Account)-[s:SIMILAR_TO]->(b:Account)
RETURN a.account_id, b.account_id, s.similarity_score,
       a.community_id = b.community_id AS same_community
ORDER BY s.similarity_score DESC LIMIT 10

Q: Which phone numbers are shared by several customers?
MATCH (c:Customer)-[:HAS_PHONE]->(p:Phone)
WITH p, collect(DISTINCT c.name) AS customers
WHERE size(customers) > 1
RETURN p.number AS phone, customers LIMIT 20
"""

RECURSION_MESSAGE = (
    "I reached the step limit before finishing, so I could not complete this "
    "analysis. Try a narrower question, such as one community, account, or "
    "relationship type."
)

_STRING_OR_COMMENT = re.compile(
    r"""
    '(?:[^'\\]|\\.)*'      # single-quoted string
    | "(?:[^"\\]|\\.)*"    # double-quoted string
    | `[^`]*`              # backtick identifier
    | //[^\n]*             # line comment
    | /\*.*?\*/            # block comment
    """,
    re.VERBOSE | re.DOTALL,
)
_WRITE_PATTERN = re.compile(
    r"""
    (?<![\w.])(?:
        CREATE | MERGE | DELETE | DETACH | SET | REMOVE | DROP | FOREACH
        | LOAD\s+CSV
        | CALL\s*\{(?:[^{}]|\{[^{}]*\})*?\b(?:CREATE|MERGE|DELETE|DETACH|SET|REMOVE)\b
        | CALL\s+apoc\.(?:create|merge|refactor|periodic|trigger|cypher\.do|
                          cypher\.run|nodes\.delete|do)\w*
    )(?![\w])
    """,
    re.IGNORECASE | re.VERBOSE,
)

TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    EOFError,
    httpx.TransportError,
    httpx.HTTPStatusError,
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
)
INPUT_ERRORS: tuple[type[BaseException], ...] = (ToolException, ValueError, TypeError)


def is_read_only_cypher(query: str) -> bool:
    """Return True when the Cypher text contains no write clauses.

    String literals, backtick identifiers, and comments are ignored.
    """
    stripped = _STRING_OR_COMMENT.sub(" ", query)
    return _WRITE_PATTERN.search(stripped) is None


def truncate_text(text: str, limit: int) -> str:
    """Cut text to at most `limit` characters and append a truncation marker."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n{TRUNCATION_MARKER}"


def _matches_tool(name: str, allowed: str) -> bool:
    if name == allowed:
        return True
    return name.endswith(allowed) and not name[-len(allowed) - 1].isalnum()


def is_tool_allowed(name: str, allowed: frozenset[str] = ALLOWED_TOOLS) -> bool:
    return any(_matches_tool(name, tool) for tool in allowed)


def is_transport_error(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return any(is_transport_error(inner) for inner in exc.exceptions)
    return isinstance(exc, TRANSPORT_ERRORS) and not isinstance(exc, INPUT_ERRORS)


class GuardrailMiddleware(AgentMiddleware):
    """Tool allowlist, read-only Cypher check, error conversion, and truncation."""

    def __init__(
        self,
        allowed_tools: frozenset[str] = ALLOWED_TOOLS,
        max_chars: int = TOOL_RESULT_MAX_CHARS,
    ) -> None:
        super().__init__()
        self.allowed_tools = allowed_tools
        self.max_chars = max_chars

    def _rejection(self, request: ToolCallRequest) -> ToolMessage | None:
        call = request.tool_call
        name = call["name"]
        if not is_tool_allowed(name, self.allowed_tools):
            return self._error(call, f"Tool '{name}' is not permitted.")
        if _matches_tool(name, READ_CYPHER_TOOL):
            query = (call.get("args") or {}).get("query", "")
            if not isinstance(query, str) or not is_read_only_cypher(query):
                return self._error(
                    call, "Only read-only Cypher is permitted. Rewrite without writes."
                )
        return None

    @staticmethod
    def _error(call: dict[str, Any], text: str) -> ToolMessage:
        return ToolMessage(
            content=f"Error: {text}",
            name=call["name"],
            tool_call_id=call["id"],
            status="error",
        )

    def _finish(self, result: ToolMessage | Command) -> ToolMessage | Command:
        if isinstance(result, ToolMessage) and isinstance(result.content, str):
            result.content = truncate_text(result.content, self.max_chars)
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if (rejected := self._rejection(request)) is not None:
            return rejected
        try:
            return self._finish(handler(request))
        except INPUT_ERRORS as exc:
            return self._error(request.tool_call, str(exc))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if (rejected := self._rejection(request)) is not None:
            return rejected
        try:
            return self._finish(await handler(request))
        except INPUT_ERRORS as exc:
            return self._error(request.tool_call, str(exc))


def build_agent(tools: Sequence[BaseTool], llm: BaseChatModel | None = None):
    """Compile the tool-calling agent graph over the allowlisted tools."""
    if llm is None:
        llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME)
    allowed = [tool for tool in tools if is_tool_allowed(tool.name)]
    return create_agent(
        llm,
        allowed,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            GuardrailMiddleware(),
            ModelCallLimitMiddleware(run_limit=MAX_AGENT_STEPS, exit_behavior="end"),
        ],
    )


def _get_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


async def _discover_tools() -> list[BaseTool]:
    workspace_client = WorkspaceClient()
    host = workspace_client.config.host.rstrip("/")
    external_mcp_url = f"{host}/api/2.0/mcp/external/{CONNECTION_NAME}"
    mcp_client = DatabricksMultiServerMCPClient(
        [
            DatabricksMCPServer(
                name=MCP_SERVER_NAME,
                url=external_mcp_url,
                workspace_client=workspace_client,
            )
        ]
    )
    tools = await mcp_client.get_tools()
    if not tools:
        raise RuntimeError(f"No MCP tools discovered from {external_mcp_url}")
    return tools


class LangGraphResponsesAgent(ResponsesAgent):
    def __init__(self, agent=None) -> None:
        self.agent = agent
        self._lock = threading.Lock()

    def _get_agent(self):
        with self._lock:
            if self.agent is None:
                tools = _get_loop().run_until_complete(_discover_tools())
                self.agent = build_agent(tools)
            return self.agent

    def _reset_agent(self) -> None:
        with self._lock:
            self.agent = None

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done" or event.type == "error"
        ]
        return ResponsesAgentResponse(
            output=outputs, custom_outputs=request.custom_inputs
        )

    async def _predict_stream_async(
        self,
        agent,
        request: ResponsesAgentRequest,
    ) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        async for mode, data in agent.astream(
            {"messages": cc_msgs},
            config={"recursion_limit": MAX_AGENT_STEPS * 4 + 10},
            stream_mode=["updates", "messages"],
        ):
            if mode == "updates":
                for node_data in data.values():
                    if not isinstance(node_data, dict):
                        continue
                    messages = node_data.get("messages") or []
                    if not messages:
                        continue
                    for msg in messages:
                        if isinstance(msg, ToolMessage) and not isinstance(
                            msg.content, str
                        ):
                            msg.content = json.dumps(msg.content)
                    for item in output_to_responses_items_stream(messages):
                        yield item
            elif mode == "messages":
                chunk = data[0]
                if (
                    isinstance(chunk, AIMessageChunk)
                    and isinstance(chunk.content, str)
                    and chunk.content
                ):
                    yield ResponsesAgentStreamEvent(
                        **self.create_text_delta(delta=chunk.content, item_id=chunk.id)
                    )

    def predict_stream(
        self,
        request: ResponsesAgentRequest,
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        try:
            agent = self._get_agent()
            loop = _get_loop()
            iterator = self._predict_stream_async(agent, request).__aiter__()
            while True:
                try:
                    yield loop.run_until_complete(iterator.__anext__())
                except StopAsyncIteration:
                    break
        except GraphRecursionError:
            yield ResponsesAgentStreamEvent(
                type="response.output_item.done",
                item=self.create_text_output_item(RECURSION_MESSAGE, str(uuid.uuid4())),
            )
        except Exception as exc:
            if is_transport_error(exc):
                self._reset_agent()
            raise


mlflow.langchain.autolog()
AGENT = LangGraphResponsesAgent()
mlflow.models.set_model(AGENT)

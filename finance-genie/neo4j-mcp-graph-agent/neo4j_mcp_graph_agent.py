"""Neo4j MCP tool-calling LangGraph agent for Databricks Model Serving."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator, Generator, Sequence
from typing import Annotated, Any, TypedDict

import mlflow
import nest_asyncio
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks, DatabricksMCPServer
from databricks_langchain import DatabricksMultiServerMCPClient
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.messages.tool import ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt.tool_node import ToolNode
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

nest_asyncio.apply()

LLM_ENDPOINT_NAME = os.environ.get(
    "LLM_ENDPOINT_NAME", "databricks-claude-sonnet-4-6"
)
CONNECTION_NAME = os.environ.get("UC_CONNECTION_NAME", "neo4j_agentcore_mcp")

SYSTEM_PROMPT = """
You are a Neo4j MCP graph agent. Your only external data source is the Neo4j
MCP server exposed through the Databricks Unity Catalog external connection.

Use schema discovery before writing Cypher when the relevant labels,
relationships, or properties are unclear. Use only read-only Cypher. Keep
queries small and focused, explain results directly, and say when the graph
does not contain enough evidence to answer.
"""


class AgentState(TypedDict):
    messages: Annotated[Sequence[AnyMessage], add_messages]
    custom_inputs: dict[str, Any] | None
    custom_outputs: dict[str, Any] | None


def create_tool_calling_agent(
    model: LanguageModelLike,
    tools: ToolNode | Sequence[BaseTool],
    system_prompt: str | None = None,
):
    model = model.bind_tools(tools)

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "continue"
        return "end"

    if system_prompt:
        preprocessor = RunnableLambda(
            lambda state: [{"role": "system", "content": system_prompt}]
            + state["messages"]
        )
    else:
        preprocessor = RunnableLambda(lambda state: state["messages"])

    model_runnable = preprocessor | model

    def call_model(state: AgentState, config: RunnableConfig) -> dict[str, list[AnyMessage]]:
        response = model_runnable.invoke(state, config)
        return {"messages": [response]}

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", RunnableLambda(call_model))
    workflow.add_node("tools", ToolNode(tools))
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"continue": "tools", "end": END},
    )
    workflow.add_edge("tools", "agent")
    return workflow.compile()


class LangGraphResponsesAgent(ResponsesAgent):
    def __init__(self, agent) -> None:
        self.agent = agent

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done" or event.type == "error"
        ]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)

    async def _predict_stream_async(
        self,
        request: ResponsesAgentRequest,
    ) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        async for event in self.agent.astream(
            {"messages": cc_msgs},
            config={"recursion_limit": 20},
            stream_mode=["updates", "messages"],
        ):
            if event[0] == "updates":
                for node_data in event[1].values():
                    messages = node_data.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, ToolMessage) and not isinstance(
                            msg.content, str
                        ):
                            msg.content = json.dumps(msg.content)
                    for item in output_to_responses_items_stream(messages):
                        yield item
            elif event[0] == "messages":
                chunk = event[1][0]
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield ResponsesAgentStreamEvent(
                        **self.create_text_delta(delta=chunk.content, item_id=chunk.id)
                    )

    def predict_stream(
        self,
        request: ResponsesAgentRequest,
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        agen = self._predict_stream_async(request)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        iterator = agen.__aiter__()
        while True:
            try:
                yield loop.run_until_complete(iterator.__anext__())
            except StopAsyncIteration:
                break


def initialize_agent() -> LangGraphResponsesAgent:
    workspace_client = WorkspaceClient()
    host = workspace_client.config.host.rstrip("/")
    external_mcp_url = f"{host}/api/2.0/mcp/external/{CONNECTION_NAME}"
    mcp_client = DatabricksMultiServerMCPClient(
        [
            DatabricksMCPServer(
                name="neo4j-mcp",
                url=external_mcp_url,
                workspace_client=workspace_client,
            )
        ]
    )
    tools = asyncio.run(mcp_client.get_tools())
    if not tools:
        raise RuntimeError(f"No MCP tools discovered from {external_mcp_url}")
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME)
    return LangGraphResponsesAgent(
        create_tool_calling_agent(llm, tools, SYSTEM_PROMPT)
    )


mlflow.langchain.autolog()
AGENT = initialize_agent()
mlflow.models.set_model(AGENT)

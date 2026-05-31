"""
Router agent — classifies a user question as SQL or Graph and delegates.

Uses Claude Opus 4.6 with adaptive thinking + tool use.
The router never answers directly; it always calls one of two tools:
  route_to_sql   → SQLAgent
  route_to_graph → GraphAgent
"""
import logging
from typing import Any

import anthropic

from .cache import AnswerCache
from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .graph_agent import GraphAgent
from .prompts import ROUTER_SYSTEM, ROUTER_TOOLS
from .sql_agent import SQLAgent

logger = logging.getLogger(__name__)


class RouterAgent:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._cache = AnswerCache()
        self._sql_agent = SQLAgent()
        self._graph_agent = GraphAgent()

    def ask(self, question: str) -> dict[str, Any]:
        """
        Route a question to the appropriate agent and return an answer dict.

        Return shape:
        {
            "question": str,
            "route": "sql" | "graph",
            "result": <agent result>,
            "from_cache": bool,
        }
        """
        # 1. Check answer cache first
        cached = self._cache.get(question)
        if cached:
            logger.info("Cache HIT for question: %s", question[:80])
            return {
                "question": question,
                "route": cached.get("route", "unknown"),
                "result": cached.get("result"),
                "from_cache": True,
            }

        # 2. Ask the router to classify
        route, tool_input = self._classify(question)
        logger.info("Routed to: %s | subgraph=%s tables=%s",
                    route,
                    tool_input.get("subgraph_type"),
                    tool_input.get("relevant_tables"))

        # 3. Delegate to the appropriate agent
        if route == "sql":
            result = self._sql_agent.answer(
                question=question,
                relevant_tables=tool_input.get("relevant_tables", []),
            )
        else:
            result = self._graph_agent.answer(
                question=question,
                subgraph_type=tool_input.get("subgraph_type", "full_network"),
            )

        # 4. Write to cache
        payload = {"route": route, "result": result}
        self._cache.put(
            question=question,
            result=payload,
            query_type=route,
            subgraph_type=tool_input.get("subgraph_type"),
        )

        return {
            "question": question,
            "route": route,
            "result": result,
            "from_cache": False,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _classify(self, question: str) -> tuple[str, dict]:
        """Call Claude to pick route_to_sql or route_to_graph."""
        response = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=ROUTER_SYSTEM,
            tools=ROUTER_TOOLS,
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": question}],
        )

        # Extract the tool use block
        for block in response.content:
            if block.type == "tool_use":
                route = "sql" if block.name == "route_to_sql" else "graph"
                return route, block.input

        # Fallback — should never happen given tool_choice="any"
        logger.warning("Router returned no tool call; defaulting to SQL")
        return "sql", {"question": question, "relevant_tables": []}

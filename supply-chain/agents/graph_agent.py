"""
Graph Agent — projects Delta gold tables into Neo4j AuraDB on demand,
then answers relationship/network questions using Cypher queries.

Uses Claude Opus 4.6 with adaptive thinking + tool use.
"""
import json
import logging
from typing import Any

import anthropic

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .prompts import GRAPH_AGENT_SYSTEM, GRAPH_AGENT_TOOLS
from neo4j_graph.connector import Neo4jConnector

logger = logging.getLogger(__name__)

_MAX_ITERS = 8


class GraphAgent:
    def __init__(self) -> None:
        self._claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._neo4j = Neo4jConnector()
        # Track which subgraphs have already been projected this session
        self._projected: set[str] = set()

    def close(self) -> None:
        self._neo4j.close()

    # ── Public API ─────────────────────────────────────────────────────────────

    def answer(self, question: str, subgraph_type: str) -> dict[str, Any]:
        """
        Project a subgraph if needed, then answer the question with Cypher.

        Returns:
        {
            "answer": str,
            "cypher_queries": [...],
            "subgraph_type": str,
            "nodes_projected": int | None,
        }
        """
        messages = [{"role": "user", "content": question}]
        cypher_queries: list[dict] = []
        nodes_projected: int | None = None

        for _ in range(_MAX_ITERS):
            response = self._claude.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=GRAPH_AGENT_SYSTEM,
                tools=GRAPH_AGENT_TOOLS,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                answer_text = self._extract_text(response.content)
                return {
                    "answer": answer_text,
                    "cypher_queries": cypher_queries,
                    "subgraph_type": subgraph_type,
                    "nodes_projected": nodes_projected,
                }

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    if block.name == "project_subgraph":
                        sg = block.input.get("subgraph_type", subgraph_type)
                        try:
                            count = self._project(sg)
                            nodes_projected = count
                            result_str = json.dumps({
                                "status": "projected",
                                "subgraph_type": sg,
                                "nodes_created": count,
                            })
                        except Exception as exc:
                            result_str = json.dumps({"error": str(exc)})
                            logger.error("Projection failed: %s", exc)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                    elif block.name == "run_cypher":
                        cypher = block.input.get("cypher", "")
                        desc = block.input.get("description", "")
                        logger.debug("Graph Agent running Cypher: %s", desc)
                        try:
                            rows = self._neo4j.query(cypher)
                            cypher_queries.append({"cypher": cypher, "description": desc, "rows": rows})
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(rows[:50]),
                            })
                        except Exception as exc:
                            error_msg = f"Cypher error: {exc}"
                            logger.warning(error_msg)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": error_msg,
                                "is_error": True,
                            })

                messages.append({"role": "user", "content": tool_results})
            else:
                break

        return {
            "answer": "Could not produce a complete answer within the iteration limit.",
            "cypher_queries": cypher_queries,
            "subgraph_type": subgraph_type,
            "nodes_projected": nodes_projected,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _project(self, subgraph_type: str) -> int:
        """Project a subgraph from Delta into Neo4j; return node count created."""
        if subgraph_type in self._projected:
            logger.debug("Subgraph '%s' already projected this session.", subgraph_type)
            return 0

        count = self._neo4j.project_subgraph(subgraph_type)
        self._projected.add(subgraph_type)
        logger.info("Projected subgraph '%s': %d nodes/rels created.", subgraph_type, count)
        return count

    @staticmethod
    def _extract_text(content: list) -> str:
        parts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                parts.append(block.text)
        return "\n".join(parts).strip()

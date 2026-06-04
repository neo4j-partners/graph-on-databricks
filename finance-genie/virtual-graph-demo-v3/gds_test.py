"""Probe whether the Neo4j Virtual Graph supports the GDS calls in the guide.

The steps mirror ``workshop/aura_gds_guide.md``: project the transfer graph,
run PageRank / Louvain, project the bipartite graph, run Node Similarity, and
clean up. Each GDS procedure call is attempted against the Virtual Graph engine
named in the parent ``finance-genie/.env`` and the outcome (success or the
Neo4j error code) is printed. The guide claims GDS does not run on the Virtual
Graph; this script tests that claim empirically.

Usage:
    uv run gds_test.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"


@dataclass(frozen=True)
class Step:
    title: str
    cypher: str


# Ordered exactly as the guide runs them. A projection must succeed before the
# algorithms that read it can be tested, so order matters here.
STEPS: list[Step] = [
    Step(
        "gds availability: list functions",
        "RETURN gds.version() AS version",
    ),
    Step(
        "Step 2: project account_transfers (Account / TRANSFERRED_TO)",
        """
CALL gds.graph.project(
  'account_transfers',
  'Account',
  {TRANSFERRED_TO: {orientation: 'UNDIRECTED'}}
)
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
""",
    ),
    Step(
        "Step 2 check: gds.graph.list()",
        """
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
""",
    ),
    Step(
        "Step 3: gds.pageRank.write -> risk_score",
        """
CALL gds.pageRank.write(
  'account_transfers',
  {maxIterations: 20, dampingFactor: 0.85, writeProperty: 'risk_score'}
)
YIELD nodePropertiesWritten, ranIterations, didConverge
RETURN nodePropertiesWritten, ranIterations, didConverge
""",
    ),
    Step(
        "Step 4: gds.louvain.write -> community_id",
        """
CALL gds.louvain.write('account_transfers', {writeProperty: 'community_id'})
YIELD communityCount, modularity, nodePropertiesWritten
RETURN communityCount, modularity, nodePropertiesWritten
""",
    ),
    Step(
        "Step 6: project account_merchants (Account+Merchant / TRANSACTED_WITH)",
        """
CALL gds.graph.project(
  'account_merchants',
  ['Account', 'Merchant'],
  {TRANSACTED_WITH: {orientation: 'NATURAL'}}
)
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
""",
    ),
    Step(
        "Step 7: gds.nodeSimilarity.write -> SIMILAR_TO",
        """
CALL gds.nodeSimilarity.write(
  'account_merchants',
  {
    similarityMetric: 'JACCARD',
    topK: 5,
    similarityCutoff: 0.3,
    writeRelationshipType: 'SIMILAR_TO',
    writeProperty: 'similarity_score'
  }
)
YIELD nodesCompared, relationshipsWritten
RETURN nodesCompared, relationshipsWritten
""",
    ),
    Step(
        "Cleanup: drop account_transfers",
        "CALL gds.graph.drop('account_transfers', false) YIELD graphName RETURN graphName",
    ),
    Step(
        "Cleanup: drop account_merchants",
        "CALL gds.graph.drop('account_merchants', false) YIELD graphName RETURN graphName",
    ),
]


def load_connection() -> tuple[str, tuple[str, str]]:
    """Read Neo4j credentials from the parent .env and return (uri, auth)."""
    if not PARENT_ENV.is_file():
        sys.exit(f"Could not find parent env file at {PARENT_ENV}")
    load_dotenv(PARENT_ENV)

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    missing = [
        name
        for name, value in (
            ("NEO4J_URI", uri),
            ("NEO4J_USERNAME", username),
            ("NEO4J_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Missing required variables in {PARENT_ENV}: {', '.join(missing)}")
    return uri, (username, password)


def run_step(driver: Driver, step: Step) -> bool:
    """Run one GDS step; print its result or the error. Return True on success."""
    print(f"\n{'=' * 78}\n{step.title}\n{'=' * 78}")
    try:
        records, _, _ = driver.execute_query(step.cypher)
    except Neo4jError as exc:
        print(f"  FAIL: {exc.code}\n  {exc.message}")
        return False
    rows = [record.data() for record in records]
    print(f"  OK ({len(rows)} row(s))")
    for row in rows[:10]:
        print(f"    {row}")
    return True


def main() -> None:
    uri, auth = load_connection()
    print(f"Connecting to {uri} ...")
    results: list[tuple[str, bool]] = []
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        print(f"Connected. Running {len(STEPS)} GDS step(s).")
        for step in STEPS:
            ok = run_step(driver, step)
            results.append((step.title, ok))

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    for title, ok in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {title}")


if __name__ == "__main__":
    main()

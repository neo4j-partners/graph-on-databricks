"""Deterministic synthetic analysts, sessions, and prompts for the finance-genie graph agent.

Each user is an analyst with a team and a focus. The first turn of a user's first session states
who they are, so NAMS has people, organizations, and topics to extract. Later sessions do not
restate it ("back again, continue where we left off"), so an answer that reflects the focus shows
memory recall working.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

TEAMS = (
    "Northwind Bank Fraud Operations",
    "Contoso Payments Risk",
    "Fabrikam Financial Crimes",
    "Tailspin Card Services Investigations",
)

# (focus, questions). Questions only use signals the graph holds: communities, risk_score,
# betweenness_centrality, SIMILAR_TO, and shared phones and addresses.
FOCUSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "fraud ring candidate communities",
        (
            "Which communities are the top ring candidates, using 50 to 200 members and an "
            "average risk_score of at least 1.0?",
            "For the highest-risk of those communities, which accounts have the highest "
            "risk_score?",
            "Do any ring candidate communities share merchants through TRANSACTED_WITH?",
            "How many accounts in the top ring candidate community belong to an identity "
            "cluster larger than one?",
        ),
    ),
    (
        "broker and hub accounts",
        (
            "Which accounts act as hubs or brokers, based on betweenness_centrality?",
            "For the top hub accounts, how many distinct accounts transfer to them?",
            "Which communities do the top hub accounts belong to?",
            "Are any hub accounts also in communities with a high average risk_score?",
        ),
    ),
    (
        "shared phone numbers and addresses",
        (
            "Which phone numbers are shared by several customers?",
            "Which addresses are shared by several customers?",
            "Which identity clusters have the largest identity_cluster_size?",
            "Do customers who share a phone number also share an address?",
        ),
    ),
    (
        "lookalike account pairs",
        (
            "Which account pairs look alike according to SIMILAR_TO similarity_score?",
            "Which of those similar pairs are in the same community?",
            "What does the SIMILAR_TO relationship mean?",
            "Which merchants do the most similar account pairs have in common?",
        ),
    ),
)

_ID_NAMESPACE = uuid.UUID("6f1c5a5e-3c1e-4a8e-9a57-0d6a6a0f2b11")


@dataclass(frozen=True)
class TurnRequest:
    run_id: str
    user_id: str
    session_id: str
    turn: int
    prompt: str

    @property
    def invocation_id(self) -> str:
        """Stable per turn, so a retry or rerun of the same run id is idempotent."""
        return str(uuid.uuid5(_ID_NAMESPACE, f"{self.run_id}/{self.session_id}/{self.turn}"))


def build_requests(
    users: int, sessions_per_user: int, turns_per_session: int, run_id: str
) -> list[TurnRequest]:
    """Return every turn in a stable order: user, then session, then turn."""
    requests: list[TurnRequest] = []
    for user_number in range(1, users + 1):
        focus, questions = FOCUSES[user_number % len(FOCUSES)]
        team = TEAMS[user_number % len(TEAMS)]
        user_id = f"nams-load-{run_id}-user-{user_number:04d}"
        prompt_number = 0
        for session_number in range(1, sessions_per_user + 1):
            session_id = f"nams-load-{run_id}-u{user_number:04d}-s{session_number:03d}"
            for turn in range(turns_per_session):
                question = questions[prompt_number % len(questions)]
                prompt_number += 1
                requests.append(
                    TurnRequest(
                        run_id=run_id,
                        user_id=user_id,
                        session_id=session_id,
                        turn=turn,
                        prompt=_prompt(
                            user_number, team, focus, question, session_number, turn
                        ),
                    )
                )
    return requests


def _prompt(
    user_number: int, team: str, focus: str, question: str, session_number: int, turn: int
) -> str:
    if turn == 0 and session_number == 1:
        return (
            f"I am synthetic analyst {user_number:04d} on the {team} team. My focus is "
            f"{focus}. Please remember that. {question}"
        )
    if turn == 0:
        return f"Back again. Continue where we left off on my usual focus. {question}"
    return f"Continue the investigation and cite the graph evidence. {question}"

"""Deterministic synthetic analysts, sessions, and prompts for the finance-genie graph agent.

Each user is an analyst with a realistic full name, a team, a manager, a focus, and an owned
case on one ring-candidate community. The first turn of a user's first session states all of
that and asks the agent to remember it, so memory has people, organizations, relationships, and
topics to extract. Later sessions do not restate it: they open with a variant of the analyst's
or the team's name (first name, "N. Surname", team abbreviation) so alias resolution has visible
work, then ask for the usual focus and "my case" without naming them.

Questions mix three kinds, interleaved: generic graph questions per focus, instance questions
per focus that name fixed accounts, merchants, and phones, and case questions about the
analyst's own community and its top-risk accounts. Instance entities recur across turns and
across analysts, and communities are assigned round-robin so analysts on different teams
investigate the same community.

The prompt text for a given (user_number, session, turn) never depends on run_id, so a run
before and a run after an ontology is activated ask identical questions and can be compared.
Only user_id, session_id, and invocation_id carry the run id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from itertools import zip_longest

TEAMS = (
    "Northwind Bank Fraud Operations",
    "Contoso Payments Risk",
    "Fabrikam Financial Crimes",
    "Tailspin Card Services Investigations",
)

# Aligned with TEAMS. Later sessions refer to the team by these shortened forms.
TEAM_ABBREVIATIONS = (
    "Northwind Fraud Ops",
    "Contoso Risk",
    "Fabrikam FinCrimes",
    "Tailspin Card Investigations",
)

# Aligned with TEAMS. The analyst states "I report to <manager>" in the first session.
MANAGERS = (
    "Rebecca Thornton",
    "Victor Salazar",
    "Naomi Eriksen",
    "Andrew Kowalski",
)

# Fictional full names, cycled by user number.
ANALYSTS = (
    "Maya Okafor",
    "Daniel Reyes",
    "Priya Nair",
    "Tomas Lindqvist",
    "Grace Whitfield",
    "Samuel Adeyemi",
    "Chloe Brennan",
    "Hiro Tanaka",
    "Elena Marchetti",
    "Marcus Hale",
    "Aisha Rahman",
    "Lucas Ferreira",
)


@dataclass(frozen=True)
class Case:
    community_id: int
    top_accounts: tuple[int, int]


# Graph facts below come from the seeded finance-genie domain graph (25,000 Account nodes) and
# must be refreshed if the graph is re-seeded. Each case is a ring-candidate community (50 to
# 200 members, average risk_score >= 1.0) with two of its highest-risk accounts.
#
# Cases are assigned to analysts round-robin by user number. With 5 cases and 4 teams, analysts
# that share a community land on different teams (user 1 and user 6, for example), so one
# community is linked to several analysts from different teams.
CASES = (
    Case(3040, (7890, 11847)),
    Case(24683, (3949, 21782)),
    Case(23301, (1676, 23681)),
    Case(19731, (11724, 2890)),
    Case(14347, (2104, 15324)),
)

# (focus, generic questions, instance questions). Questions only use signals the graph holds:
# communities, risk_score, betweenness_centrality, SIMILAR_TO, shared phones and addresses,
# and merchants. Instance questions name entities that exist in the seeded graph (see the
# facts note above): hub accounts 7321, 15741, 13914 (community 22341) and 15940 (community
# 19766); shared phones 312-555-0142 and 312-555-0143; merchants Serrano LLC (gaming),
# Gutierrez PLC (online), Barton Inc (travel), Thompson-Caldwell (retail).
FOCUSES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "fraud ring candidate communities",
        (
            "Which communities are the top ring candidates, using 50 to 200 members and an "
            "average risk score of at least 1.0?",
            "For the highest-risk of those communities, which accounts have the highest "
            "risk score?",
            "Do any ring candidate communities share merchants through their transactions "
            "with them?",
            "How many accounts in the top ring candidate community belong to an identity "
            "cluster larger than one?",
        ),
        (
            "Is Community 24683 larger than Community 3040, and which has the higher average "
            "risk score?",
            "Which accounts in Community 19731 transact with Serrano LLC?",
            "Do Community 23301 and Community 14347 share any merchants through their "
            "transactions with them?",
            "How many accounts transact with Barton Inc, and which communities are they in?",
        ),
    ),
    (
        "broker and hub accounts",
        (
            "Which accounts act as hubs or brokers, based on betweenness?",
            "For the top hub accounts, how many distinct accounts transfer to them?",
            "Which communities do the top hub accounts belong to?",
            "Are any hub accounts also in communities with a high average risk score?",
        ),
        (
            "How many distinct accounts transfer to Account 7321?",
            "Is Account 15741 in the same community as Account 13914?",
            "Which community is Account 15940 in, and is it a ring candidate?",
            "Which accounts does Account 7321 have transfer links to?",
        ),
    ),
    (
        "shared phone numbers and addresses",
        (
            "Which phone numbers are shared by several customers?",
            "Which addresses are shared by several customers?",
            "Which identity clusters have the largest identity cluster size?",
            "Do customers who share a phone number also share an address?",
        ),
        (
            "Which customers share the phone number 312-555-0142?",
            "Which accounts are owned by the customers who share 312-555-0143?",
            "Do the customers on 312-555-0142 also share an address with each other?",
            "Which communities are the accounts of the 312-555-0143 customers in?",
        ),
    ),
    (
        "lookalike account pairs",
        (
            "Which account pairs look alike, according to their similarity score?",
            "Which of those similar pairs are in the same community?",
            "What does it mean when two accounts look alike?",
            "Which merchants do the most similar account pairs have in common?",
        ),
        (
            "Which accounts look most like Account 7890, according to the similarity score?",
            "Which merchants does Account 3949 transact with?",
            "What category and region is the merchant Gutierrez PLC, and which accounts "
            "transact with it?",
            "Which accounts transact with Thompson-Caldwell, and which communities are they "
            "in?",
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
        focus, generic, instance = FOCUSES[user_number % len(FOCUSES)]
        team_index = user_number % len(TEAMS)
        case = CASES[(user_number - 1) % len(CASES)]
        questions = _question_pool(generic, instance, case)
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
                            user_number, team_index, focus, case, question, session_number, turn
                        ),
                    )
                )
    return requests


def _question_pool(
    generic: tuple[str, ...], instance: tuple[str, ...], case: Case
) -> list[str]:
    """Interleave generic, case, and instance questions so each kind appears early and often."""
    community = case.community_id
    first, second = case.top_accounts
    case_questions = (
        f"What is the average risk score of Community {community}, and how many members does "
        "it have?",
        f"Which accounts in Community {community} have the highest risk score?",
        f"Are Account {first} and Account {second} connected through transfer links or "
        "do they look alike?",
        f"Which merchants does Account {first} transact with?",
        f"Which customer owns Account {second}, and do they share a phone number or address?",
    )
    pool: list[str] = []
    for group in zip_longest(generic, case_questions, instance):
        pool.extend(question for question in group if question is not None)
    return pool


def _prompt(
    user_number: int,
    team_index: int,
    focus: str,
    case: Case,
    question: str,
    session_number: int,
    turn: int,
) -> str:
    name = ANALYSTS[(user_number - 1) % len(ANALYSTS)]
    if turn == 0 and session_number == 1:
        return (
            f"I am {name} on the {TEAMS[team_index]} team. My focus is {focus}. "
            f"I report to {MANAGERS[team_index]}. I own case CASE-{4000 + user_number}, "
            f"our investigation of Community {case.community_id}. Please remember that. "
            f"{question}"
        )
    if turn == 0:
        opening = _alias_opening(
            name, TEAM_ABBREVIATIONS[team_index], user_number, session_number
        )
        return (
            f"{opening} Continue where we left off on my usual focus and my case. {question}"
        )
    return f"Continue the investigation and cite the graph evidence. {question}"


def _alias_opening(
    name: str, team_abbreviation: str, user_number: int, session_number: int
) -> str:
    """Refer to the analyst or team by a variant.

    Rotating by user number plus session number keeps every variant in use even when each
    user has only two sessions.
    """
    first, surname = name.split(" ", 1)
    variants = (
        f"Back again, it is {first}.",
        f"Back again, this is {first[0]}. {surname}.",
        f"Back again from {team_abbreviation}.",
    )
    return variants[(user_number + session_number) % len(variants)]

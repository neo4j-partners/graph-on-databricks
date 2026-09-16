from typing import Literal

from pydantic import BaseModel, Field

from .. import __version__


class VersionOut(BaseModel):
    version: str

    @classmethod
    def from_metadata(cls):
        return cls(version=__version__)


# --- Search ---------------------------------------------------------------

SignalType = Literal["fraud_rings", "risk_scores", "central_accounts"]
Risk = Literal["H", "M", "L"]
Topology = Literal["star", "mesh", "chain"]
Band = Literal["Low", "Medium", "High"]


class GraphNode(BaseModel):
    id: str
    risk: Risk
    is_hub: bool


class GraphEdge(BaseModel):
    source: str
    target: str


class Graph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RingOut(BaseModel):
    ring_id: str
    nodes: int
    volume: int
    shared_identifiers: list[str]
    risk: Risk
    risk_score: float
    topology: Topology
    graph: Graph


class RiskAccountOut(BaseModel):
    account_id: str
    risk_score: float
    velocity: Band
    merchant_diversity: Band
    account_age_days: int


class HubAccountOut(BaseModel):
    account_id: str
    betweenness: float
    shortest_paths: int
    neighbors: int


# --- Load -----------------------------------------------------------------


class LoadIn(BaseModel):
    ring_ids: list[str] = Field(default_factory=list)
    risk_account_ids: list[str] = Field(default_factory=list)
    central_account_ids: list[str] = Field(default_factory=list)


class LoadStep(BaseModel):
    label: str
    status: Literal["done", "now", "todo"]
    detail: str | None = None


class QualityCheck(BaseModel):
    name: str
    passed: bool


class LoadOut(BaseModel):
    target_tables: list[str]
    steps: list[LoadStep]
    row_counts: dict[str, int]
    quality_checks: list[QualityCheck]


# --- Genie ----------------------------------------------------------------


class AskIn(BaseModel):
    question: str
    conversation_id: str | None = None


class AnswerTable(BaseModel):
    headers: list[str]
    rows: list[list[str]]


class AskOut(BaseModel):
    conversation_id: str
    message_id: str
    text: str
    table: AnswerTable | None = None
    summary: str | None = None

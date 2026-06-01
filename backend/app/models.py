"""
Pydantic contracts — shared by sources, orchestrator, scoring, and LLM output.
Build and stabilise these before touching anything else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Query / entity resolution
# ---------------------------------------------------------------------------


class CompanyQuery(BaseModel):
    company_name: str | None = None
    registration_number: str | None = None
    jurisdiction: str = "GB"

    @model_validator(mode="after")
    def at_least_one(self) -> "CompanyQuery":
        if not self.company_name and not self.registration_number:
            raise ValueError("Provide company_name, registration_number, or both.")
        return self


class EntityCandidate(BaseModel):
    registration_number: str
    name: str
    status: str
    match_confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    address: str | None = None


class ResolvedEntity(BaseModel):
    registration_number: str
    name: str
    status: str
    match_confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    address: str | None = None


# ---------------------------------------------------------------------------
# Risk signals & source results
# ---------------------------------------------------------------------------


class RiskSignal(BaseModel):
    code: str
    severity: Literal["info", "low", "medium", "high"]
    score_contribution: Annotated[float, Field(ge=0.0, le=100.0)]
    explanation: str
    source: str
    evidence: dict | None = None


class SourceResult(BaseModel):
    source_name: str
    status: Literal["pending", "ok", "partial", "error", "timeout"]
    latency_ms: int
    signals: list[RiskSignal] = Field(default_factory=list)
    raw: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Final assessment
# ---------------------------------------------------------------------------


class CompanyRiskAssessment(BaseModel):
    query: CompanyQuery
    resolved_entity: ResolvedEntity | None = None
    candidates: list[EntityCandidate] = Field(default_factory=list)
    overall_risk_score: Annotated[float, Field(ge=0.0, le=100.0)]
    risk_band: Literal["low", "medium", "high"]
    sources: list[SourceResult] = Field(default_factory=list)
    completeness: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    generated_at: datetime
    prompt_version: str


# ---------------------------------------------------------------------------
# SSE event envelope — typed union used by orchestrator and SSE endpoint
# ---------------------------------------------------------------------------


class EntityResolvedEvent(BaseModel):
    type: Literal["entity_resolved"] = "entity_resolved"
    entity: ResolvedEntity


class SourceResultEvent(BaseModel):
    type: Literal["source_result"] = "source_result"
    result: SourceResult


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    assessment: CompanyRiskAssessment


class NeedsDisambiguationEvent(BaseModel):
    type: Literal["needs_disambiguation"] = "needs_disambiguation"
    candidates: list[EntityCandidate]


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


AssessmentEvent = (
    EntityResolvedEvent
    | SourceResultEvent
    | FinalEvent
    | NeedsDisambiguationEvent
    | ErrorEvent
)

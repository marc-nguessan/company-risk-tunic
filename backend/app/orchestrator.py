"""
Orchestrator: fan-out to sources, stream events via async generator.

Phase 1: entity resolution is stubbed (no real CH lookup yet).
Phase 2: replace _resolve_entity() with real Companies House search.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import cast

from app.models import (
    AssessmentEvent,
    CompanyQuery,
    CompanyRiskAssessment,
    EntityResolvedEvent,
    FinalEvent,
    ResolvedEntity,
    SourceResult,
    SourceResultEvent,
)
from app.scoring import aggregate_and_score
from app.sources.base import DataSource

# ---------------------------------------------------------------------------
# Source registry — adding a source is one class + one entry here
# ---------------------------------------------------------------------------

from app.sources.stub_companies_info import StubCompaniesInfoSource
from app.sources.stub_director_network import StubDirectorNetworkSource

_SOURCES: list[DataSource] = [
    StubCompaniesInfoSource(),
    StubDirectorNetworkSource(),
]

PROMPT_VERSION = "stub_v1"


# ---------------------------------------------------------------------------
# Stub entity resolution (Phase 1)
# ---------------------------------------------------------------------------


def _stub_resolve(query: CompanyQuery) -> ResolvedEntity:
    """Return a synthetic entity so the stream works before real CH is wired."""
    return ResolvedEntity(
        registration_number=query.registration_number or "00000000",
        name=query.company_name or f"Company {query.registration_number}",
        status="active",
        match_confidence=1.0,
        address=None,
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _compute_completeness(results: list[SourceResult]) -> float:
    ok_count = sum(1 for r in results if r.status in ("ok", "partial"))
    return round(ok_count / len(results), 2) if results else 0.0


def _compute_confidence(results: list[SourceResult]) -> float:
    ok_count = sum(1 for r in results if r.status == "ok")
    return round(ok_count / len(results), 2) if results else 0.0


# ---------------------------------------------------------------------------
# Main assessment generator
# ---------------------------------------------------------------------------


async def assess(query: CompanyQuery) -> AsyncIterator[AssessmentEvent]:
    # Phase 1: resolve entity without real API call.
    entity = _stub_resolve(query)
    yield EntityResolvedEvent(entity=entity)

    # Fan-out: launch all sources concurrently; yield each result as it lands.
    results: list[SourceResult] = []
    tasks = {asyncio.ensure_future(src.safe_fetch(entity)): src for src in _SOURCES}

    pending = set(tasks.keys())
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for fut in done:
            result = cast(SourceResult, fut.result())
            results.append(result)
            yield SourceResultEvent(result=result)

    # Aggregate deterministically.
    all_signals = [sig for r in results for sig in r.signals]
    score, band = aggregate_and_score(all_signals)

    assessment = CompanyRiskAssessment(
        query=query,
        resolved_entity=entity,
        candidates=[],
        overall_risk_score=score,
        risk_band=band,
        sources=results,
        completeness=_compute_completeness(results),
        confidence=_compute_confidence(results),
        generated_at=datetime.now(timezone.utc),
        prompt_version=PROMPT_VERSION,
    )
    yield FinalEvent(assessment=assessment)

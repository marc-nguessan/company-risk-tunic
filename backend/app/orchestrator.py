"""
Orchestrator: resolve entity → fan-out sources → stream events → final assessment.

Adding a source: one new class + one registry entry in _SOURCES. That's it.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import cast

from app import entity_resolution
from app.models import (
    AssessmentEvent,
    CompanyQuery,
    CompanyRiskAssessment,
    EntityResolvedEvent,
    ErrorEvent,
    FinalEvent,
    NeedsDisambiguationEvent,
    SourceResult,
    SourceResultEvent,
)
from app.scoring import aggregate_and_score, compute_completeness
from app.sources.adverse_media import AdverseMediaSource
from app.sources.base import DataSource
from app.sources.companies_house import CompaniesHouseSource
from app.sources.director_network import DirectorNetworkSource

# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

_SOURCES: list[DataSource] = [
    CompaniesHouseSource(),
    DirectorNetworkSource(),
    AdverseMediaSource(),
]

PROMPT_VERSION = "adverse_media_v1"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _compute_confidence(results: list[SourceResult]) -> float:
    """
    Confidence is derived from source health, NOT from the risk score.
    'Low risk' and 'we couldn't find enough to tell' are different outcomes —
    a fraud analyst needs to see which one they're looking at.
    """
    if not results:
        return 0.0
    ok = sum(1 for r in results if r.status == "ok")
    return round(ok / len(results), 2)


# ---------------------------------------------------------------------------
# Main assessment generator
# ---------------------------------------------------------------------------


async def assess(query: CompanyQuery) -> AsyncIterator[AssessmentEvent]:
    # Step 1: entity resolution.
    entity, candidates = await entity_resolution.resolve_entity(query)

    if entity is None:
        if candidates:
            yield NeedsDisambiguationEvent(candidates=candidates)
        else:
            yield ErrorEvent(message="No matching company found.")
        return

    yield EntityResolvedEvent(entity=entity)

    # Step 2: fan-out — launch all sources concurrently; yield each result as it lands.
    results: list[SourceResult] = []
    tasks = {asyncio.ensure_future(src.safe_fetch(entity)): src for src in _SOURCES}

    pending = set(tasks.keys())
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for fut in done:
            result = cast(SourceResult, fut.result())
            results.append(result)
            yield SourceResultEvent(result=result)

    # Step 3: deterministic aggregate.
    all_signals = [sig for r in results for sig in r.signals]
    score, band = aggregate_and_score(all_signals)

    assessment = CompanyRiskAssessment(
        query=query,
        resolved_entity=entity,
        candidates=candidates,
        overall_risk_score=score,
        risk_band=band,
        sources=results,
        completeness=compute_completeness(results),
        confidence=_compute_confidence(results),
        generated_at=datetime.now(timezone.utc),
        prompt_version=PROMPT_VERSION,
    )
    yield FinalEvent(assessment=assessment)

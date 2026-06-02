"""
Source-level tests.

1. respx-backed test of the CompaniesHouseSource LIVE path: mock the HTTP
   transport with a recorded-shape Companies House response and assert the
   source parses it into the correct signals — fully offline, no real API key.

2. Graceful degradation: a source that raises inside fetch() is wrapped by
   safe_fetch into an error SourceResult, and the orchestrator still completes
   the assessment with a final event rather than crashing.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app import config
from app.models import CompanyQuery, ResolvedEntity, SourceResult
from app.sources.base import DataSource
from app.sources.companies_house import CompaniesHouseSource

_CH_BASE = "https://api.company-information.service.gov.uk"


# ---------------------------------------------------------------------------
# 1. respx-backed live-path source test
# ---------------------------------------------------------------------------

# Recorded-shape Companies House responses (mirror the real Public Data API).
# A dissolved company that still returns HTTP 200 with a full body — the exact
# gotcha the source must handle by branching on company_status, not status code.
_DISSOLVED_PROFILE = {
    "company_name": "RECORDED DISSOLVED LTD",
    "company_number": "99887766",
    "company_status": "liquidation",
    "company_status_detail": "voluntary-liquidation",
    "type": "ltd",
    "date_of_creation": "2012-06-01",
    "accounts": {
        "next_accounts": {"due_on": "2024-03-31", "overdue": False},
        "last_accounts": {"made_up_to": "2022-06-30"},
    },
    "confirmation_statement": {"next_due": "2024-06-14", "overdue": False},
}

_FILING_HISTORY = {
    "filing_history_status": "filing-history-available",
    "total_count": 2,
    "items": [
        {"category": "gazette", "date": "2023-11-01", "type": "GAZ1", "description": "gazette"},
        {"category": "accounts", "date": "2022-09-15", "type": "AA", "description": "accounts"},
    ],
}


@pytest.fixture
def live_mode(monkeypatch):
    """Force the live (non-fixture) retrieval path and provide a dummy key."""
    monkeypatch.setattr(config, "CH_USE_FIXTURES", False)
    monkeypatch.setattr(config, "CH_API_KEY", "test-key")


@respx.mock
async def test_companies_house_live_path_parses_recorded_response(live_mode):
    """The live HTTP path parses a recorded CH response into the right signals."""
    num = "99887766"
    respx.get(f"{_CH_BASE}/company/{num}").mock(
        return_value=httpx.Response(200, json=_DISSOLVED_PROFILE)
    )
    respx.get(f"{_CH_BASE}/company/{num}/filing-history").mock(
        return_value=httpx.Response(200, json=_FILING_HISTORY)
    )

    entity = ResolvedEntity(
        registration_number=num,
        name="RECORDED DISSOLVED LTD",
        status="liquidation",
        match_confidence=1.0,
    )
    result = await CompaniesHouseSource().fetch(entity)

    assert result.status == "ok"
    codes = {s.code for s in result.signals}
    # liquidation status must produce DISSOLVED_OR_LIQUIDATION despite HTTP 200.
    assert "DISSOLVED_OR_LIQUIDATION" in codes
    # The liquidation signal carries provenance + evidence.
    liq = next(s for s in result.signals if s.code == "DISSOLVED_OR_LIQUIDATION")
    assert liq.source == "companies_house"
    assert liq.evidence is not None
    assert liq.evidence["company_status"] == "liquidation"


@respx.mock
async def test_companies_house_live_path_http_error_degrades(live_mode):
    """A 500 from the upstream degrades to an error SourceResult, never raises."""
    num = "50050050"
    respx.get(f"{_CH_BASE}/company/{num}").mock(return_value=httpx.Response(500))

    entity = ResolvedEntity(
        registration_number=num, name="X", status="unknown", match_confidence=1.0
    )
    # Go through safe_fetch — this is the robustness boundary.
    result = await CompaniesHouseSource().safe_fetch(entity)
    assert result.status == "error"
    assert result.error is not None


# ---------------------------------------------------------------------------
# 2. Graceful degradation — one bad source never crashes the run
# ---------------------------------------------------------------------------


class _ExplodingSource(DataSource):
    name = "exploding_source"
    timeout_s = 5.0

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        raise RuntimeError("simulated upstream failure")


async def test_safe_fetch_wraps_exception_into_error_result():
    """safe_fetch must convert a raising fetch() into status='error', not raise."""
    entity = ResolvedEntity(
        registration_number="14999001", name="NEWCO DIGITAL LTD",
        status="active", match_confidence=1.0,
    )
    result = await _ExplodingSource().safe_fetch(entity)
    assert result.status == "error"
    assert "simulated upstream failure" in (result.error or "")


async def test_orchestrator_completes_despite_failing_source(monkeypatch):
    """
    With a deliberately broken source in the registry, assess() must still
    stream a final assessment — the broken source shows as an error card.
    """
    from app import orchestrator

    # Patch the registry to a real source + an exploding one.
    monkeypatch.setattr(
        orchestrator,
        "_SOURCES",
        [CompaniesHouseSource(), _ExplodingSource()],
    )
    # Use fixture mode so CompaniesHouse resolves offline.
    monkeypatch.setattr(config, "CH_USE_FIXTURES", True)

    events = [ev async for ev in orchestrator.assess(CompanyQuery(registration_number="14999001"))]

    types = [e.type for e in events]
    assert "entity_resolved" in types
    assert "final" in types  # assessment completed despite the failure

    final = next(e for e in events if e.type == "final")
    statuses = {s.source_name: s.status for s in final.assessment.sources}
    assert statuses["exploding_source"] == "error"      # degraded, not crashed
    assert statuses["companies_house"] == "ok"           # healthy source still ran
    # Confidence reflects the degraded source health.
    assert final.assessment.confidence < 1.0

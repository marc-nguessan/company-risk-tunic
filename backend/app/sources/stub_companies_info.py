"""Stub for Phase 1 — replaced by CompaniesHouseSource in Phase 2."""

import asyncio

from app.models import ResolvedEntity, RiskSignal, SourceResult
from app.sources.base import DataSource


class StubCompaniesInfoSource(DataSource):
    name = "stub_companies_info"
    timeout_s = 5.0

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        await asyncio.sleep(0.5)
        signals = [
            RiskSignal(
                code="RECENTLY_INCORPORATED",
                severity="medium",
                score_contribution=40.0,
                explanation=f"{entity.name} was incorporated 8 months ago (stub data).",
                source=self.name,
                evidence={"date_of_creation": "2025-10-01", "months_old": 8},
            )
        ]
        return SourceResult(
            source_name=self.name,
            status="ok",
            latency_ms=500,
            signals=signals,
            raw={"stub": True, "company_number": entity.registration_number},
        )

"""Stub for Phase 1 — replaced by DirectorNetworkSource in Phase 2."""

import asyncio

from app.models import ResolvedEntity, RiskSignal, SourceResult
from app.sources.base import DataSource


class StubDirectorNetworkSource(DataSource):
    name = "stub_director_network"
    timeout_s = 5.0

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        await asyncio.sleep(1.2)
        signals = [
            RiskSignal(
                code="DIRECTOR_MULTIPLE_APPOINTMENTS",
                severity="low",
                score_contribution=15.0,
                explanation="Director J. Smith holds 18 active appointments (stub data).",
                source=self.name,
                evidence={"director": "J. Smith", "active_appointments": 18},
            )
        ]
        return SourceResult(
            source_name=self.name,
            status="ok",
            latency_ms=1200,
            signals=signals,
            raw={"stub": True, "company_number": entity.registration_number},
        )

"""
AdverseMediaSource — Phase 3 stub.

Phase 3 will replace this with:
  - Mocked retrieval: loads fixture text blobs from fixtures/adverse_media/
  - Real LLM structuring: OpenRouter json_schema response_format → AdverseMediaFinding
  - Validation-then-retry guardrail

The clean seam: swap this class for the real implementation; the DataSource interface
and orchestrator registry entry require no other changes.
"""

import asyncio

from app.models import ResolvedEntity, SourceResult
from app.sources.base import DataSource


class AdverseMediaSource(DataSource):
    name = "adverse_media"
    timeout_s = 15.0

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        await asyncio.sleep(0.1)
        return SourceResult(
            source_name=self.name,
            status="ok",
            latency_ms=100,
            signals=[],
            raw={"stub": True, "note": "Phase 3: real LLM structuring will go here"},
        )

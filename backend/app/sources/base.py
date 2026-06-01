"""
DataSource ABC — every source implements fetch(); safe_fetch() wraps it with
timeout and exception handling so a flaky source never crashes the orchestrator.
"""

import asyncio
import time
from abc import ABC, abstractmethod

from app.models import ResolvedEntity, SourceResult


class DataSource(ABC):
    name: str
    timeout_s: float = 5.0

    @abstractmethod
    async def fetch(self, entity: ResolvedEntity) -> SourceResult: ...

    async def safe_fetch(self, entity: ResolvedEntity) -> SourceResult:
        """Never raises. Returns timeout/error SourceResult on failure."""
        start = time.monotonic()
        try:
            return await asyncio.wait_for(self.fetch(entity), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return SourceResult(
                source_name=self.name,
                status="timeout",
                latency_ms=latency_ms,
                error=f"Timed out after {self.timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - start) * 1000)
            return SourceResult(
                source_name=self.name,
                status="error",
                latency_ms=latency_ms,
                error=str(exc),
            )

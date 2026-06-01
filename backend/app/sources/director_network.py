"""
DirectorNetworkSource — fetches officers + per-officer appointment counts.

CH_USE_FIXTURES=true  → fixtures/companies_house/{company_number}/officers.json
                         fixtures/companies_house/officers/{officer_id}/appointments.json
CH_USE_FIXTURES=false → calls /company/{number}/officers then /officers/{id}/appointments

Real-API gotcha: the API returns ALL appointments (active + resigned) with no server-side
filter.  We count active appointments ourselves: an appointment is active when resigned_on
is absent, EVEN when the appointed_to company has since been dissolved.
The company's dissolution does not implicitly resign the officer.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app import config
from app.models import ResolvedEntity, RiskSignal, SourceResult
from app.sources.base import DataSource

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "companies_house"
_CH_BASE = "https://api.company-information.service.gov.uk"

_MEDIUM_THRESHOLD = 15
_HIGH_THRESHOLD = 30


class DirectorNetworkSource(DataSource):
    name = "director_network"
    timeout_s = 10.0

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        t0 = time.monotonic()
        num = entity.registration_number

        try:
            officers = await self._get_officers(num)
        except (FileNotFoundError, OSError) as exc:
            return SourceResult(
                source_name=self.name,
                status="error",
                latency_ms=_ms(t0),
                error=f"Officers fixture not found for {num}: {exc}",
            )
        except httpx.HTTPError as exc:
            return SourceResult(
                source_name=self.name,
                status="error",
                latency_ms=_ms(t0),
                error=f"HTTP error fetching officers: {exc}",
            )

        signals: list[RiskSignal] = []

        for officer in officers.get("items", []):
            # Skip officers who have already left this company.
            if officer.get("resigned_on"):
                continue

            officer_id = _extract_officer_id(officer)
            if not officer_id:
                continue

            try:
                appointments = await self._get_appointments(officer_id)
            except (FileNotFoundError, OSError):
                # Missing appointments fixture → degrade gracefully, skip this officer.
                continue
            except httpx.HTTPError:
                continue

            # Count active appointments: no resigned_on, regardless of company status.
            # A director of a dissolved company who never formally resigned still holds
            # an active appointment from the API's perspective.
            active_count = sum(
                1 for appt in appointments.get("items", [])
                if not appt.get("resigned_on")
            )

            if active_count <= _MEDIUM_THRESHOLD:
                continue

            severity = "high" if active_count > _HIGH_THRESHOLD else "medium"
            score = 70.0 if active_count > _HIGH_THRESHOLD else 40.0

            signals.append(
                RiskSignal(
                    code="DIRECTOR_MULTIPLE_APPOINTMENTS",
                    severity=severity,
                    score_contribution=score,
                    explanation=(
                        f"{officer['name']} holds {active_count} active "
                        f"directorship(s) across separate companies."
                    ),
                    source=self.name,
                    evidence={
                        "officer_name": officer["name"],
                        "officer_role": officer.get("officer_role"),
                        "active_appointments": active_count,
                        "total_results": appointments.get("total_results", 0),
                    },
                )
            )

        return SourceResult(
            source_name=self.name,
            status="ok",
            latency_ms=_ms(t0),
            signals=signals,
            raw={
                "company_number": num,
                "active_officer_count": officers.get("active_count", 0),
            },
        )

    # ------------------------------------------------------------------
    # Retrieval — only these methods differ between fixture/live paths
    # ------------------------------------------------------------------

    async def _get_officers(self, company_number: str) -> dict:
        if config.CH_USE_FIXTURES:
            path = _FIXTURE_DIR / company_number / "officers.json"
            return json.loads(path.read_text())
        async with _ch_client() as client:
            r = await client.get(f"/company/{company_number}/officers")
            r.raise_for_status()
            return r.json()

    async def _get_appointments(self, officer_id: str) -> dict:
        if config.CH_USE_FIXTURES:
            path = _FIXTURE_DIR / "officers" / officer_id / "appointments.json"
            return json.loads(path.read_text())
        async with _ch_client() as client:
            r = await client.get(f"/officers/{officer_id}/appointments")
            r.raise_for_status()
            return r.json()


def _extract_officer_id(officer: dict) -> str:
    """
    Extract officer ID from the appointments link.
    Real API path: /officers/{officer_id}/appointments
    """
    path: str = (
        officer.get("links", {}).get("officer", {}).get("appointments", "") or ""
    )
    # Strip leading slash, split on '/'
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "officers" and parts[2] == "appointments":
        return parts[1]
    return ""


def _ch_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=_CH_BASE, auth=(config.CH_API_KEY, ""))


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)

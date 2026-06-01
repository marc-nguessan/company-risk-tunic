"""
CompaniesHouseSource — fetches company profile + filing history from Companies House.

CH_USE_FIXTURES=true  → loads from backend/fixtures/companies_house/{company_number}/
CH_USE_FIXTURES=false → calls https://api.company-information.service.gov.uk (HTTP Basic auth)

The parsing, signal-generation, and scoring logic is identical on both paths.
Only the two private _load_*/_fetch_* methods differ.

Real-API gotchas handled here:
  1. A dissolved company returns HTTP 200 — never assume 200 means active.
     Branch on company_status, not the status code.
  2. date_of_creation can be missing or "" (e.g. CIOs) — handle gracefully.
  3. /search/companies and /company/{number} return different field subsets —
     always fetch the full profile; never rely on search-result fields here.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from app import config
from app.models import ResolvedEntity, RiskSignal, SourceResult
from app.sources.base import DataSource

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "companies_house"
_CH_BASE = "https://api.company-information.service.gov.uk"

# Statuses that are NOT operating — a payment to one of these is high risk.
_RISK_STATUSES = {"dissolved", "liquidation", "administration", "receivership", "voluntary-arrangement"}


class CompaniesHouseSource(DataSource):
    name = "companies_house"
    timeout_s = 8.0

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        t0 = time.monotonic()
        num = entity.registration_number

        try:
            if config.CH_USE_FIXTURES:
                profile, filing_history = self._load_fixtures(num)
            else:
                profile, filing_history = await self._fetch_live(num)
        except (FileNotFoundError, OSError) as exc:
            return SourceResult(
                source_name=self.name,
                status="error",
                latency_ms=_ms(t0),
                error=f"Fixture not found for {num}: {exc}",
            )
        except httpx.HTTPError as exc:
            return SourceResult(
                source_name=self.name,
                status="error",
                latency_ms=_ms(t0),
                error=f"HTTP error: {exc}",
            )

        signals = [
            *self._check_status(profile),
            *self._check_incorporation_date(profile),
            *self._check_accounts(profile),
            *self._check_filing_history(filing_history, profile),
        ]

        return SourceResult(
            source_name=self.name,
            status="ok",
            latency_ms=_ms(t0),
            signals=signals,
            raw={
                "company_number": num,
                "company_name": profile.get("company_name"),
                "company_status": profile.get("company_status"),
                "date_of_creation": profile.get("date_of_creation"),
            },
        )

    # ------------------------------------------------------------------
    # Retrieval — only these two methods differ between fixture/live paths
    # ------------------------------------------------------------------

    def _load_fixtures(self, company_number: str) -> tuple[dict, dict]:
        base = _FIXTURE_DIR / company_number
        profile = json.loads((base / "profile.json").read_text())
        filing_history = json.loads((base / "filing_history.json").read_text())
        return profile, filing_history

    async def _fetch_live(self, company_number: str) -> tuple[dict, dict]:
        async with httpx.AsyncClient(
            base_url=_CH_BASE,
            auth=(config.CH_API_KEY, ""),
            timeout=self.timeout_s,
        ) as client:
            profile_r = await client.get(f"/company/{company_number}")
            profile_r.raise_for_status()
            history_r = await client.get(f"/company/{company_number}/filing-history")
            history_r.raise_for_status()
            return profile_r.json(), history_r.json()

    # ------------------------------------------------------------------
    # Signal generation — deterministic, no I/O
    # ------------------------------------------------------------------

    def _check_status(self, profile: dict) -> list[RiskSignal]:
        """
        Dissolved/liquidation companies return HTTP 200 with a full body.
        We MUST check company_status, never assume 200 means active.
        """
        status = profile.get("company_status", "")
        if status not in _RISK_STATUSES:
            return []

        detail = profile.get("company_status_detail")
        suffix = f" — {detail}" if detail else ""

        return [
            RiskSignal(
                code="DISSOLVED_OR_LIQUIDATION",
                severity="high",
                score_contribution=80.0,
                explanation=f"Company status is '{status}'{suffix}.",
                source=self.name,
                evidence={
                    "company_status": status,
                    "company_status_detail": detail,
                },
            )
        ]

    def _check_incorporation_date(self, profile: dict) -> list[RiskSignal]:
        """
        date_of_creation can be missing or "" for some entity types (e.g. CIOs).
        Handle the absence gracefully — return no signal rather than crashing.
        """
        date_str: str = profile.get("date_of_creation") or ""
        if not date_str:
            return []

        try:
            incorporation_date = date.fromisoformat(date_str)
        except ValueError:
            return []

        days_old = (date.today() - incorporation_date).days
        months_old = days_old / 30.44

        if months_old >= 12:
            return []

        severity, score = ("high", 70.0) if months_old < 3 else ("medium", 40.0)

        return [
            RiskSignal(
                code="RECENTLY_INCORPORATED",
                severity=severity,
                score_contribution=score,
                explanation=(
                    f"Company incorporated {months_old:.0f} month(s) ago "
                    f"({date_str})."
                ),
                source=self.name,
                evidence={"date_of_creation": date_str, "days_old": days_old},
            )
        ]

    def _check_accounts(self, profile: dict) -> list[RiskSignal]:
        accounts = profile.get("accounts", {})
        next_accounts = accounts.get("next_accounts", {})
        confirmation = profile.get("confirmation_statement", {})

        accounts_overdue = bool(next_accounts.get("overdue"))
        cs_overdue = bool(confirmation.get("overdue"))

        if not accounts_overdue and not cs_overdue:
            return []

        parts: list[str] = []
        if accounts_overdue:
            parts.append(f"annual accounts (due {next_accounts.get('due_on', '?')})")
        if cs_overdue:
            parts.append(f"confirmation statement (due {confirmation.get('next_due', '?')})")

        return [
            RiskSignal(
                code="OVERDUE_ACCOUNTS",
                severity="medium",
                score_contribution=35.0,
                explanation=f"Overdue: {' and '.join(parts)}.",
                source=self.name,
                evidence={
                    "accounts_overdue": accounts_overdue,
                    "accounts_due_on": next_accounts.get("due_on"),
                    "confirmation_overdue": cs_overdue,
                    "confirmation_next_due": confirmation.get("next_due"),
                },
            )
        ]

    def _check_filing_history(self, filing_history: dict, profile: dict) -> list[RiskSignal]:
        """
        Skip this check for recently-incorporated companies (<12 months old) —
        sparse filing is expected and not a risk signal for new companies.
        """
        date_str: str = profile.get("date_of_creation") or ""
        if date_str:
            try:
                months_old = (date.today() - date.fromisoformat(date_str)).days / 30.44
                if months_old < 12:
                    return []
            except ValueError:
                pass

        cutoff = date.today() - timedelta(days=365)
        recent = 0
        for item in filing_history.get("items", []):
            try:
                if date.fromisoformat(item.get("date", "")) >= cutoff:
                    recent += 1
            except ValueError:
                pass

        if recent >= 3:
            return []

        severity = "low" if recent > 0 else "medium"
        score = 20.0 if recent > 0 else 30.0

        return [
            RiskSignal(
                code="SPARSE_FILING_HISTORY",
                severity=severity,
                score_contribution=score,
                explanation=f"Only {recent} filing(s) in the past 12 months.",
                source=self.name,
                evidence={
                    "recent_filing_count": recent,
                    "total_count": filing_history.get("total_count", 0),
                },
            )
        ]


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)

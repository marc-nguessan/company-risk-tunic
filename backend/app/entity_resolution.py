"""
Entity resolution: turn a CompanyQuery into a ResolvedEntity.

Fixture mode:  filesystem lookup under backend/fixtures/companies_house/
Live mode:     GET /search/companies → candidates, then pick or disambiguate.

Only the retrieval step differs. The candidate-selection logic is shared.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app import config
from app.models import CompanyQuery, EntityCandidate, ResolvedEntity

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "companies_house"
_CH_BASE = "https://api.company-information.service.gov.uk"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def resolve_entity(
    query: CompanyQuery,
    client: httpx.AsyncClient | None = None,
) -> tuple[ResolvedEntity | None, list[EntityCandidate]]:
    """
    Returns (entity, candidates).

    - entity is not None → resolved; proceed with assessment.
    - entity is None and candidates non-empty → need disambiguation; stop and ask user.
    - entity is None and candidates empty → nothing found; surface as error.
    """
    if query.registration_number:
        # Direct lookup — no ambiguity possible.
        profile = await _get_profile(query.registration_number, client)
        if profile:
            entity = _profile_to_resolved(profile)
        else:
            # Unknown number: construct a minimal entity so sources can try to fetch it.
            entity = ResolvedEntity(
                registration_number=query.registration_number,
                name=query.company_name or query.registration_number,
                status="unknown",
                match_confidence=1.0,
            )
        return entity, []

    # Name search.
    candidates = await _search(query.company_name or "", client)

    if not candidates:
        return None, []

    if len(candidates) == 1:
        return ResolvedEntity(**candidates[0].model_dump()), candidates

    # Exact name match short-circuits disambiguation.
    q_upper = (query.company_name or "").upper()
    exact = [c for c in candidates if c.name.upper() == q_upper]
    if len(exact) == 1:
        return ResolvedEntity(**exact[0].model_dump()), candidates

    # Multiple plausible candidates → caller yields NeedsDisambiguationEvent.
    return None, candidates


# ---------------------------------------------------------------------------
# Profile fetch (shared by entity resolution and, implicitly, CH source)
# ---------------------------------------------------------------------------


async def _get_profile(number: str, client: httpx.AsyncClient | None) -> dict | None:
    if config.CH_USE_FIXTURES:
        return _fixture_profile(number)
    assert client is not None, "httpx client required in live mode"
    resp = await client.get(f"/company/{number}", auth=(config.CH_API_KEY, ""))
    return resp.json() if resp.status_code == 200 else None


def _fixture_profile(number: str) -> dict | None:
    path = _FIXTURE_DIR / number / "profile.json"
    return json.loads(path.read_text()) if path.exists() else None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def _search(query: str, client: httpx.AsyncClient | None) -> list[EntityCandidate]:
    if config.CH_USE_FIXTURES:
        return _fixture_search(query)
    assert client is not None, "httpx client required in live mode"
    return await _live_search(query, client)


def _fixture_search(query: str) -> list[EntityCandidate]:
    """Substring match across all fixture profiles; sorted by match quality."""
    q_upper = query.upper()
    results: list[EntityCandidate] = []

    for company_dir in sorted(_FIXTURE_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        profile_path = company_dir / "profile.json"
        if not profile_path.exists():
            continue
        profile = json.loads(profile_path.read_text())
        name: str = profile.get("company_name", "").upper()
        number: str = profile.get("company_number", "")

        if q_upper in name or q_upper in number:
            confidence = 1.0 if name == q_upper else (0.8 if name.startswith(q_upper) else 0.5)
            results.append(_profile_to_candidate(profile, confidence))

    return sorted(results, key=lambda c: -c.match_confidence)


async def _live_search(query: str, client: httpx.AsyncClient) -> list[EntityCandidate]:
    # Note: /search/companies returns a subset of fields — do NOT assume it contains
    # everything that /company/{number} does. We use it only for candidate discovery.
    resp = await client.get(
        "/search/companies",
        params={"q": query, "items_per_page": 5},
        auth=(config.CH_API_KEY, ""),
    )
    if resp.status_code != 200:
        return []

    data = resp.json()
    candidates: list[EntityCandidate] = []
    for i, item in enumerate(data.get("items", [])):
        addr = item.get("address", {})
        address_str = ", ".join(
            p for p in [
                addr.get("premises"),
                addr.get("address_line_1"),
                addr.get("locality"),
                addr.get("postal_code"),
            ]
            if p
        )
        # CH search does not return a confidence score; use rank as a proxy.
        confidence = round(max(0.3, 0.95 - i * 0.1), 2)
        candidates.append(
            EntityCandidate(
                registration_number=item["company_number"],
                name=item["company_name"],
                status=item.get("company_status", "unknown"),
                match_confidence=confidence,
                address=address_str or None,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_to_candidate(profile: dict, confidence: float) -> EntityCandidate:
    addr = profile.get("registered_office_address", {})
    address_str = ", ".join(
        p for p in [
            addr.get("address_line_1"),
            addr.get("locality"),
            addr.get("postal_code"),
        ]
        if p
    )
    return EntityCandidate(
        registration_number=profile["company_number"],
        name=profile["company_name"],
        status=profile.get("company_status", "unknown"),
        match_confidence=confidence,
        address=address_str or None,
    )


def _profile_to_resolved(profile: dict) -> ResolvedEntity:
    c = _profile_to_candidate(profile, confidence=1.0)
    return ResolvedEntity(**c.model_dump())

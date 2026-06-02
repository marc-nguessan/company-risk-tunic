"""
Pure deterministic scoring. No LLM, no I/O.
score = min(100, weighted_sum(signal.score_contribution * weight[code]))
"""

from app.models import RiskSignal, SourceResult

# Tunable weights per signal code. Extend when adding new signal types.
SIGNAL_WEIGHTS: dict[str, float] = {
    "RECENTLY_INCORPORATED": 1.0,
    "DISSOLVED_OR_LIQUIDATION": 1.2,
    "SPARSE_FILING_HISTORY": 0.8,
    "OVERDUE_ACCOUNTS": 0.7,
    "DIRECTOR_MULTIPLE_APPOINTMENTS": 0.9,
    "ADVERSE_MEDIA_MENTION": 1.1,
}
_DEFAULT_WEIGHT = 1.0

LOW_THRESHOLD = 30.0
HIGH_THRESHOLD = 65.0


def aggregate_and_score(signals: list[RiskSignal]) -> tuple[float, str]:
    """Return (overall_risk_score 0-100, risk_band)."""
    if not signals:
        return 0.0, "low"

    raw = sum(
        s.score_contribution * SIGNAL_WEIGHTS.get(s.code, _DEFAULT_WEIGHT)
        for s in signals
    )
    score = round(min(100.0, raw), 2)

    if score < LOW_THRESHOLD:
        band = "low"
    elif score < HIGH_THRESHOLD:
        band = "medium"
    else:
        band = "high"

    return score, band


# ---------------------------------------------------------------------------
# Data-coverage completeness
# ---------------------------------------------------------------------------

# Expected raw-dict keys per source name.
# These are the fields that should carry non-empty data when a source has
# gathered a full picture of the company. Declaring them here makes the
# expectation explicit and keeps the completeness function a plain table lookup.
#
# "Populated" means: non-None, non-empty string/list/dict, and > 0 for
# numeric counts. A source that runs cleanly but returns zero articles or
# zero active officers is healthy (high confidence) but sparse (low completeness).
_SOURCE_EXPECTED_FIELDS: dict[str, list[str]] = {
    "companies_house": [
        "company_status",    # always populated on a successful profile fetch
        "date_of_creation",  # empty string for some entity types (e.g. CIOs)
        "company_name",      # always populated on a successful profile fetch
    ],
    "director_network": [
        "active_officer_count",  # 0 when the company has no active officers
    ],
    "adverse_media": [
        "article_count",  # 0 when no articles were retrieved for this company
        "findings",       # absent/empty when no articles were processed
    ],
}


def _is_populated(value: object) -> bool:
    """True when the field carries real, non-trivial data."""
    if value is None:
        return False
    if isinstance(value, str):
        return len(value) > 0
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value > 0
    return bool(value)


def compute_completeness(results: list[SourceResult]) -> float:
    """
    Data-coverage completeness: (populated expected fields) / (total expected fields).

    Measures how much data we actually gathered, independent of source health.
    Confidence answers "can we trust the result?"; completeness answers "how
    thoroughly was the company profiled?".

    A source that returns ok but finds sparse data — e.g. a CIO with no
    date_of_creation, a dormant company with zero active officers, or a company
    with no adverse-media articles — contributes to high confidence but LOW
    completeness. That divergence is the point: it lets an analyst distinguish
    "low risk" from "we didn't gather enough data to be sure".

    Sources not in _SOURCE_EXPECTED_FIELDS (e.g. stubs) contribute nothing to
    the denominator, so they don't inflate or deflate the ratio.
    """
    total = 0
    populated = 0

    for result in results:
        expected = _SOURCE_EXPECTED_FIELDS.get(result.source_name, [])
        raw: dict = result.raw or {}
        total += len(expected)
        populated += sum(1 for field in expected if _is_populated(raw.get(field)))

    if total == 0:
        return 1.0  # no declared expectations → trivially complete

    return round(populated / total, 2)

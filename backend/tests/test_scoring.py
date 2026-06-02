"""
Tests for scoring.py — completeness and aggregate_and_score.

The key property under test: completeness (data coverage) and confidence
(source health) are independent. Both start at the same value when all
sources are healthy AND fully populated. They diverge when sources are
healthy but return sparse data — that divergence is the feature.
"""

from app.models import RiskSignal, SourceResult
from app.scoring import aggregate_and_score, compute_completeness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(source_name: str, raw: dict | None) -> SourceResult:
    return SourceResult(source_name=source_name, status="ok", latency_ms=50, raw=raw)


def _err(source_name: str) -> SourceResult:
    return SourceResult(
        source_name=source_name, status="error", latency_ms=100, raw=None, error="timed out"
    )


def _signal(code: str, severity: str, contribution: float) -> RiskSignal:
    return RiskSignal(
        code=code,
        severity=severity,
        score_contribution=contribution,
        explanation="test",
        source="test",
    )


# ---------------------------------------------------------------------------
# compute_completeness
# ---------------------------------------------------------------------------


def test_all_fields_populated_gives_1():
    """All three sources ok, every expected field carries real data → 1.0."""
    results = [
        _ok("companies_house", {
            "company_number": "14999001",
            "company_name": "NEWCO DIGITAL LTD",
            "company_status": "active",
            "date_of_creation": "2026-03-10",   # non-empty ✓
        }),
        _ok("director_network", {
            "company_number": "14999001",
            "active_officer_count": 2,            # > 0 ✓
        }),
        _ok("adverse_media", {
            "article_count": 3,                   # > 0 ✓
            "findings": [{"source": "art_01", "finding": {"is_adverse": True}}],  # non-empty ✓
        }),
    ]
    assert compute_completeness(results) == 1.0


def test_ok_sources_sparse_data_diverges_from_confidence():
    """
    All three sources return ok → confidence = 1.0 (source health is full).
    But several expected fields are empty:
      - date_of_creation is "" (CIO with no creation date)
      - active_officer_count is 0 (company has no active officers)
      - article_count is 0 and 'findings' is absent (no media articles found)

    Completeness must be materially lower than confidence, proving the two
    metrics are independent — not just different names for the same ratio.
    """
    results = [
        _ok("companies_house", {
            "company_number": "00000042",
            "company_name": "HOPEFUL COMMUNITIES CIO",
            "company_status": "active",
            "date_of_creation": "",               # empty string — CIO edge case ✗
        }),
        _ok("director_network", {
            "company_number": "00000042",
            "active_officer_count": 0,            # zero — no active officers ✗
        }),
        _ok("adverse_media", {
            "article_count": 0,                   # zero — no articles retrieved ✗
            # 'findings' key absent (as the source emits when no articles loaded)
        }),
    ]

    completeness = compute_completeness(results)
    confidence = 1.0  # all sources returned ok — health is perfect

    # Divergence: source health is full but data coverage is sparse.
    assert completeness < confidence, (
        f"Expected completeness ({completeness}) < confidence ({confidence}); "
        "they must be independent metrics"
    )
    # Exactly 2 of 6 expected fields are populated: company_status and company_name.
    assert completeness == round(2 / 6, 2), f"Got {completeness}, expected {round(2/6, 2)}"


def test_errored_sources_reduce_completeness():
    """
    One source ok (all fields populated), two sources error.
    Completeness = populated / total-expected = 3 / (3+1+2) = 0.5.
    """
    results = [
        _ok("companies_house", {
            "company_name": "EXAMPLE LTD",
            "company_status": "active",
            "date_of_creation": "2020-01-01",
        }),
        _err("director_network"),   # raw=None → 0 of 1 expected fields populated
        _err("adverse_media"),      # raw=None → 0 of 2 expected fields populated
    ]
    assert compute_completeness(results) == round(3 / 6, 2)


def test_unknown_source_names_do_not_affect_ratio():
    """
    Stub sources or unknown names have no expected fields — they must not
    inflate or deflate the ratio, and must not trigger division-by-zero.
    """
    results = [
        _ok("stub_companies_info", {"stub": True}),
        _ok("stub_director_network", {"stub": True}),
    ]
    # No declared expectations → trivially complete
    assert compute_completeness(results) == 1.0


def test_empty_result_list():
    """Edge case: empty results → 1.0 (nothing expected, nothing missing)."""
    assert compute_completeness([]) == 1.0


# ---------------------------------------------------------------------------
# aggregate_and_score (table-driven)
# ---------------------------------------------------------------------------


def test_no_signals_scores_zero_low():
    assert aggregate_and_score([]) == (0.0, "low")


def test_single_medium_signal():
    signals = [_signal("RECENTLY_INCORPORATED", "medium", 40.0)]
    score, band = aggregate_and_score(signals)
    assert score == 40.0
    assert band == "medium"


def test_high_band_threshold():
    # DISSOLVED_OR_LIQUIDATION weight=1.2, contribution=80 → 96 → high
    signals = [_signal("DISSOLVED_OR_LIQUIDATION", "high", 80.0)]
    score, band = aggregate_and_score(signals)
    assert score == round(min(100.0, 80.0 * 1.2), 2)
    assert band == "high"


def test_score_capped_at_100():
    # Multiple large signals should never exceed 100
    signals = [
        _signal("RECENTLY_INCORPORATED", "high", 70.0),
        _signal("DISSOLVED_OR_LIQUIDATION", "high", 80.0),
        _signal("ADVERSE_MEDIA_MENTION", "high", 70.0),
    ]
    score, _ = aggregate_and_score(signals)
    assert score <= 100.0


def test_band_thresholds():
    assert aggregate_and_score([_signal("X", "low", 10.0)])[1] == "low"    # < 30
    assert aggregate_and_score([_signal("X", "medium", 45.0)])[1] == "medium"  # 30–65
    assert aggregate_and_score([_signal("X", "high", 70.0)])[1] == "high"  # > 65

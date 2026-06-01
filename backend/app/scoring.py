"""
Pure deterministic scoring. No LLM, no I/O.
score = min(100, weighted_sum(signal.score_contribution * weight[code]))
"""

from app.models import RiskSignal

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

"""
AdverseMediaSource — mocked retrieval, real LLM processing.

Retrieval (MOCKED):
    Loads fixture article text blobs from backend/fixtures/adverse_media/{company_number}/.
    In production, replace _load_fixture_articles() with a call to a news API
    (GDELT, Dow Jones Factiva, LexisNexis) or a sanctions list (OpenSanctions, OFAC).
    The clean seam is the private method boundary — everything downstream is unchanged.

Processing (REAL):
    Each article is classified by the LLM (OpenRouter, json_schema structured output)
    into a validated AdverseMediaFinding. Only findings with is_adverse=True generate
    a RiskSignal, with score contribution scaled to the finding's severity.

Failure contract:
    A single article failure is logged and skipped; the remaining articles are still
    processed. If ALL articles fail, status="partial" is returned. A missing API key
    raises through safe_fetch and becomes status="error" — never a crash.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.llm.client import LLMValidationError, classify_adverse_media
from app.models import AdverseMediaFinding, ResolvedEntity, RiskSignal, SourceResult
from app.sources.base import DataSource

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "adverse_media"
_LOG = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

# Score contribution per severity level — same scale as other signals.
_SEVERITY_SCORE: dict[str, float] = {
    "high": 70.0,
    "medium": 45.0,
    "low": 20.0,
    "info": 5.0,
}


class AdverseMediaSource(DataSource):
    name = "adverse_media"
    timeout_s = 30.0  # LLM latency can be significant; allow more headroom

    async def fetch(self, entity: ResolvedEntity) -> SourceResult:
        t0 = time.monotonic()

        # ── Retrieval (MOCKED) ─────────────────────────────────────────────
        # Production seam: swap this call for a live news/sanctions API query.
        articles = self._load_fixture_articles(entity.registration_number)

        if not articles:
            return SourceResult(
                source_name=self.name,
                status="ok",
                latency_ms=_ms(t0),
                signals=[],
                raw={
                    "article_count": 0,
                    "prompt_version": PROMPT_VERSION,
                    "note": "No fixture articles for this registration number.",
                },
            )

        # ── Processing (REAL) ──────────────────────────────────────────────
        signals: list[RiskSignal] = []
        raw_findings: list[dict] = []
        failed_articles: list[str] = []

        for label, article_text in articles:
            try:
                finding: AdverseMediaFinding = await classify_adverse_media(
                    company_name=entity.name,
                    registration_number=entity.registration_number,
                    source_label=label,
                    article_text=article_text,
                    prompt_version=PROMPT_VERSION,
                )
                raw_findings.append({"source": label, "finding": finding.model_dump()})

                if finding.is_adverse:
                    signals.append(
                        RiskSignal(
                            code="ADVERSE_MEDIA_MENTION",
                            severity=finding.severity,
                            score_contribution=_SEVERITY_SCORE.get(finding.severity, 20.0),
                            explanation=(
                                f"[{finding.category}] {finding.summary}"
                            ),
                            source=f"{self.name}:{label}",
                            evidence={
                                "source_label": label,
                                "category": finding.category,
                                "severity": finding.severity,
                                "summary": finding.summary,
                                "prompt_version": PROMPT_VERSION,
                            },
                        )
                    )
                else:
                    _LOG.debug(
                        "Article %s classified NOT_ADVERSE for %s (%s) — no signal emitted.",
                        label, entity.name, entity.registration_number,
                    )

            except LLMValidationError as exc:
                _LOG.warning("LLM validation failed for %s / %s: %s", entity.registration_number, label, exc)
                raw_findings.append({"source": label, "error": str(exc)})
                failed_articles.append(label)
            except Exception as exc:  # noqa: BLE001
                _LOG.error("Unexpected error classifying %s / %s: %s", entity.registration_number, label, exc)
                raw_findings.append({"source": label, "error": str(exc)})
                failed_articles.append(label)

        # Determine status: partial if some (not all) articles failed.
        all_failed = len(failed_articles) == len(articles)
        status = "partial" if all_failed or failed_articles else "ok"

        return SourceResult(
            source_name=self.name,
            status=status,
            latency_ms=_ms(t0),
            signals=signals,
            raw={
                "article_count": len(articles),
                "processed": len(articles) - len(failed_articles),
                "failed": len(failed_articles),
                "prompt_version": PROMPT_VERSION,
                "findings": raw_findings,
            },
            error=f"Classification failed for: {failed_articles}" if failed_articles else None,
        )

    # ── Retrieval (MOCKED) ─────────────────────────────────────────────────
    # Production: replace this method with live API retrieval.
    # The DataSource interface, signal generation, and scoring are unchanged.

    def _load_fixture_articles(self, registration_number: str) -> list[tuple[str, str]]:
        """Load fixture text blobs for this company. Returns [(label, text), ...]."""
        company_dir = _FIXTURE_DIR / registration_number
        if not company_dir.exists():
            return []
        return [
            (path.stem, path.read_text(encoding="utf-8"))
            for path in sorted(company_dir.glob("*.txt"))
        ]


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)

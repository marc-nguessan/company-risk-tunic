#!/usr/bin/env python3
"""
backend/evals/run_evals.py — offline regression harness.

Run from backend/:
    python evals/run_evals.py
    # or with uv
    uv run python evals/run_evals.py

Does NOT require OPENROUTER_API_KEY.  The LLM is replaced with deterministic
stubs whose verdicts represent the correct output for each fixture article.
Only the signal-extraction and scoring logic runs for real.

How to use this for prompt regression:
  1. Before changing a prompt:  run this script, note the coverage table.
  2. Change prompts/adverse_media_v2.txt (new version).
  3. Re-run with a live key to collect actual model verdicts.
  4. Update _LLM_STUBS to match new expected verdicts, bump STUB_VERSION.
  5. Re-run offline to confirm signal extraction still passes.

The prompt version under test is printed in the header so diffs between
before/after runs are unambiguous.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

# Allow `from app.xxx import yyy` when run from backend/ or repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("CH_USE_FIXTURES", "true")

from app.models import AdverseMediaFinding, ResolvedEntity
from app.orchestrator import PROMPT_VERSION as ORCHESTRATOR_VERSION
from app.sources.adverse_media import PROMPT_VERSION as AM_PROMPT_VERSION
from app.sources.adverse_media import AdverseMediaSource
from app.sources.companies_house import CompaniesHouseSource
from app.sources.director_network import DirectorNetworkSource

# Version string for this stub set — bump when stubs are updated to track a
# new prompt version, so before/after comparisons remain interpretable.
STUB_VERSION = "stubs_v1"

# ---------------------------------------------------------------------------
# Stubbed LLM verdicts
# Keyed by (registration_number, source_label).
# These represent what the model SHOULD produce for each fixture article.
# If a prompt change produces different verdicts, update these stubs after
# collecting live-model output and re-run to confirm signal extraction passes.
# ---------------------------------------------------------------------------

_STUBS: dict[tuple[str, str], dict] = {
    # SC987654 article 01 — NCA investigation → ADVERSE
    ("SC987654", "article_01_nca_investigation"): {
        "is_adverse": True,
        "category": "MONEY_LAUNDERING",
        "severity": "medium",
        "summary": (
            "NCA investigation alleges company bank accounts were used to receive "
            "and disperse APP fraud proceeds targeting UK consumers."
        ),
    },
    # SC987654 article 02 — VICTIM of invoice fraud → NOT_ADVERSE
    # Critical edge case: company named prominently but is the victim, not perpetrator.
    ("SC987654", "article_02_victim_invoice_fraud"): {
        "is_adverse": False,
        "category": "NOT_ADVERSE",
        "severity": "info",
        "summary": (
            "Company was the victim of an invoice fraud; criminals impersonated a supplier. "
            "Not adverse — company is the wronged party."
        ),
    },
    # SC987654 article 03 — German GmbH decoy → NOT_ADVERSE
    # Critical edge case: different legal entity with a similar name.
    ("SC987654", "article_03_german_decoy"): {
        "is_adverse": False,
        "category": "NOT_ADVERSE",
        "severity": "info",
        "summary": (
            "Article concerns Mule Network Consulting GmbH (Frankfurt, HRB 88997), "
            "a German entity explicitly stated to be unrelated to any UK companies."
        ),
    },
    # 14999001 article 01 — FCA consumer warning → ADVERSE
    ("14999001", "article_01_fca_consumer_warning"): {
        "is_adverse": True,
        "category": "REGULATORY_ACTION",
        "severity": "high",
        "summary": (
            "FCA issued a formal consumer warning naming the company by registration "
            "number as an unregistered investment operator."
        ),
    },
}

_DEFAULT = {
    "is_adverse": False,
    "category": "NOT_ADVERSE",
    "severity": "info",
    "summary": "No adverse media finding.",
}


async def _stub_classify(
    company_name: str,
    registration_number: str,
    source_label: str,
    article_text: str,
    prompt_version: str = "v1",
) -> AdverseMediaFinding:
    """Drop-in replacement for classify_adverse_media — deterministic, no API calls."""
    payload = _STUBS.get((registration_number, source_label), _DEFAULT)
    return AdverseMediaFinding(**payload)


# ---------------------------------------------------------------------------
# Eval cases
# ---------------------------------------------------------------------------


@dataclass
class EvalCase:
    company_number: str
    company_name: str
    description: str
    must_contain: list[str] = field(default_factory=list)     # codes that MUST appear
    must_not_contain: list[str] = field(default_factory=list) # codes that must NOT appear
    # Expected is_adverse verdict per article label (adverse-media hard cases)
    am_expected: dict[str, bool] = field(default_factory=dict)


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        company_number="14999001",
        company_name="NEWCO DIGITAL LTD",
        description="Recently incorporated (2026-03-10) + director mule network + FCA consumer warning",
        must_contain=["RECENTLY_INCORPORATED", "DIRECTOR_MULTIPLE_APPOINTMENTS", "ADVERSE_MEDIA_MENTION"],
        am_expected={"article_01_fca_consumer_warning": True},
    ),
    EvalCase(
        company_number="09123456",
        company_name="DISSOLVED VENTURES LTD",
        description="Dissolved company — must emit DISSOLVED_OR_LIQUIDATION",
        must_contain=["DISSOLVED_OR_LIQUIDATION"],
        must_not_contain=["RECENTLY_INCORPORATED"],
    ),
    EvalCase(
        company_number="06789012",
        company_name="DELINQUENT ACCOUNTS LTD",
        description="Overdue accounts + overdue confirmation statement",
        must_contain=["OVERDUE_ACCOUNTS"],
    ),
    EvalCase(
        company_number="00000042",
        company_name="HOPEFUL COMMUNITIES CIO",
        description=(
            "CIO with missing date_of_creation — must handle gracefully, "
            "must NOT emit RECENTLY_INCORPORATED"
        ),
        must_not_contain=["RECENTLY_INCORPORATED"],
    ),
    EvalCase(
        company_number="SC987654",
        company_name="MULE NETWORK CONSULTING LTD",
        description=(
            "High director network (34 active appts → HIGH) + "
            "adverse media with victim + same-name-decoy filtering"
        ),
        must_contain=["DIRECTOR_MULTIPLE_APPOINTMENTS", "ADVERSE_MEDIA_MENTION"],
        am_expected={
            "article_01_nca_investigation":   True,   # adverse
            "article_02_victim_invoice_fraud": False,  # NOT_ADVERSE: company is the victim
            "article_03_german_decoy":         False,  # NOT_ADVERSE: different legal entity
        },
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_case(case: EvalCase) -> dict:
    entity = ResolvedEntity(
        registration_number=case.company_number,
        name=case.company_name,
        status="unknown",
        match_confidence=1.0,
    )

    ch_result, dn_result, am_result = await asyncio.gather(
        CompaniesHouseSource().safe_fetch(entity),
        DirectorNetworkSource().safe_fetch(entity),
        AdverseMediaSource().safe_fetch(entity),
    )

    all_signals = [*ch_result.signals, *dn_result.signals, *am_result.signals]
    actual_codes = {s.code for s in all_signals}

    missing   = [c for c in case.must_contain     if c not in actual_codes]
    forbidden = [c for c in case.must_not_contain if c in actual_codes]

    # Collect per-article is_adverse verdicts from raw findings.
    raw_findings = (am_result.raw or {}).get("findings", [])
    am_verdicts: dict[str, bool] = {
        f["source"]: f["finding"]["is_adverse"]
        for f in raw_findings
        if "finding" in f
    }
    am_mismatches = {
        label: f"expected is_adverse={expected}, got {am_verdicts.get(label, 'not in results')}"
        for label, expected in case.am_expected.items()
        if am_verdicts.get(label) != expected
    }

    passed = not missing and not forbidden and not am_mismatches
    return {
        "case": case,
        "passed": passed,
        "actual_codes": sorted(actual_codes),
        "missing": missing,
        "forbidden": forbidden,
        "am_verdicts": am_verdicts,
        "am_mismatches": am_mismatches,
        "statuses": {
            "companies_house": ch_result.status,
            "director_network": dn_result.status,
            "adverse_media": am_result.status,
        },
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

W = 72


def _print_results(results: list[dict]) -> int:
    print(f"\n{'='*W}")
    print("Company Risk Assessment — Eval Harness")
    print(f"  Adverse-media prompt : {AM_PROMPT_VERSION}  (stubs: {STUB_VERSION})")
    print(f"  Orchestrator version : {ORCHESTRATOR_VERSION}")
    print(f"  CH_USE_FIXTURES      : {os.environ.get('CH_USE_FIXTURES', 'true')}")
    print(f"{'='*W}\n")

    passed_count  = 0
    expected_total = 0
    caught_total   = 0

    for i, r in enumerate(results, 1):
        case = r["case"]
        tag  = "PASS ✓" if r["passed"] else "FAIL ✗"
        print(f"Case {i}/{len(results)}: {case.company_name} ({case.company_number})")
        print(f"  {case.description}")
        print(f"  Sources : {', '.join(f'{k}={v}' for k, v in r['statuses'].items())}")
        print(f"  Signals : {', '.join(r['actual_codes']) or '(none)'}")

        for code in case.must_contain:
            ok = code in r["actual_codes"]
            print(f"  {'✓' if ok else '✗'} expected  : {code}")

        for code in case.must_not_contain:
            ok = code not in r["actual_codes"]
            print(f"  {'✓' if ok else '✗'} forbidden : {code} {'absent' if ok else 'PRESENT — should not be'}")

        for label, expected in case.am_expected.items():
            actual  = r["am_verdicts"].get(label, "?")
            ok      = actual == expected
            print(f"  {'✓' if ok else '✗'} media [{label}]: is_adverse={expected} (got {actual})")

        print(f"  → {tag}")
        print()

        if r["passed"]:
            passed_count += 1
        expected_total += len(case.must_contain)
        caught_total   += sum(1 for c in case.must_contain if c in r["actual_codes"])

    print(f"{'='*W}")
    print(f"Cases   : {passed_count}/{len(results)} passed")
    if expected_total:
        pct = int(caught_total / expected_total * 100)
        print(f"Signals : {caught_total}/{expected_total} expected signals caught ({pct}%)")
    print(f"{'='*W}\n")

    return 0 if passed_count == len(results) else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _main() -> int:
    # Patch classify_adverse_media for the duration of all eval cases.
    with patch("app.sources.adverse_media.classify_adverse_media", side_effect=_stub_classify):
        results = list(await asyncio.gather(*[run_case(c) for c in EVAL_CASES]))
    return _print_results(results)


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))

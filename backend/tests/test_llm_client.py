"""
Targeted tests for the LLM client's validate-and-retry guardrail.

No live API calls — _call_llm and _get_client are mocked at the boundary.
The prompt-loading functions are also mocked so tests don't depend on file
paths (the prompts are tested through the real classify_adverse_media call
only when running with live keys, not in CI).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.client import LLMValidationError, classify_adverse_media, clear_cache

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_VALID_PAYLOAD = {
    "is_adverse": True,
    "category": "FRAUD_OR_SCAM",
    "severity": "high",
    "summary": "The company was alleged to have operated a payment fraud scheme targeting retail customers.",
}

_INVALID_JSON = "{this is not valid json ←"

_NOT_ADVERSE_PAYLOAD = {
    "is_adverse": False,
    "category": "NOT_ADVERSE",
    "severity": "info",
    "summary": "The article describes the company as a victim of fraud, not a perpetrator.",
}


def _fake_response(content: str) -> MagicMock:
    """Build a minimal mock that looks like an openai ChatCompletion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# Shared mock context — patches _load_prompt, _get_client, and _call_llm
# so no filesystem I/O or HTTP calls happen.
# ---------------------------------------------------------------------------

_PATCH_LOAD = "app.llm.client._load_prompt"
_PATCH_CLIENT = "app.llm.client._get_client"
_PATCH_CALL = "app.llm.client._call_llm"


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the in-memory cache before and after every test."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Core guardrail tests
# ---------------------------------------------------------------------------


async def test_first_attempt_fails_retry_succeeds():
    """
    First LLM response is malformed JSON; retry returns valid JSON.
    Expects: valid AdverseMediaFinding returned, _call_llm called exactly twice.
    """
    with (
        patch(_PATCH_LOAD, return_value="mock prompt text"),
        patch(_PATCH_CLIENT, return_value=MagicMock()),
        patch(_PATCH_CALL, new_callable=AsyncMock) as mock_call,
    ):
        mock_call.side_effect = [
            _INVALID_JSON,           # first attempt: bad JSON
            json.dumps(_VALID_PAYLOAD),  # retry: valid JSON
        ]

        finding = await classify_adverse_media(
            company_name="ACME TEST LTD",
            registration_number="11111111",
            source_label="article_retry_test",
            article_text="Unique article text for retry-succeeds test.",
        )

    assert finding.is_adverse is True
    assert finding.category == "FRAUD_OR_SCAM"
    assert finding.severity == "high"
    assert mock_call.call_count == 2

    # On retry, the messages should include the failed response + error (3-turn conversation).
    _first_call_messages = mock_call.call_args_list[0][0][1]   # positional arg 1 = messages
    _retry_call_messages = mock_call.call_args_list[1][0][1]
    assert len(_retry_call_messages) == len(_first_call_messages) + 2  # assistant + user appended


async def test_both_attempts_fail_raises_llm_validation_error():
    """
    Both LLM responses are malformed. Expects LLMValidationError raised
    (not a bare JSON error), and _call_llm called exactly twice.
    """
    with (
        patch(_PATCH_LOAD, return_value="mock prompt text"),
        patch(_PATCH_CLIENT, return_value=MagicMock()),
        patch(_PATCH_CALL, new_callable=AsyncMock) as mock_call,
    ):
        mock_call.return_value = _INVALID_JSON  # both attempts return bad JSON

        with pytest.raises(LLMValidationError) as exc_info:
            await classify_adverse_media(
                company_name="ACME TEST LTD",
                registration_number="22222222",
                source_label="article_fail_test",
                article_text="Unique article text for double-failure test.",
            )

    assert mock_call.call_count == 2
    assert "failed after retry" in str(exc_info.value).lower()


async def test_valid_first_response_no_retry():
    """
    First LLM response is valid. Expects exactly one call — no unnecessary retry.
    """
    with (
        patch(_PATCH_LOAD, return_value="mock prompt text"),
        patch(_PATCH_CLIENT, return_value=MagicMock()),
        patch(_PATCH_CALL, new_callable=AsyncMock) as mock_call,
    ):
        mock_call.return_value = json.dumps(_VALID_PAYLOAD)

        finding = await classify_adverse_media(
            company_name="ACME TEST LTD",
            registration_number="33333333",
            source_label="article_valid",
            article_text="Unique article for single-call test.",
        )

    assert finding.is_adverse is True
    assert mock_call.call_count == 1


async def test_cache_prevents_second_llm_call():
    """
    Same (model, prompt_version, registration_number, article_text) → cache hit on
    the second call. _call_llm must be invoked only once across both invocations.
    """
    article_text = "Unique stable text for same-company cache test."

    with (
        patch(_PATCH_LOAD, return_value="mock prompt text"),
        patch(_PATCH_CLIENT, return_value=MagicMock()),
        patch(_PATCH_CALL, new_callable=AsyncMock) as mock_call,
    ):
        mock_call.return_value = json.dumps(_NOT_ADVERSE_PAYLOAD)

        finding1 = await classify_adverse_media(
            company_name="CACHE CO LTD",
            registration_number="44444444",
            source_label="cache_article",
            article_text=article_text,
        )
        # Second call — identical registration_number + article_text → cache hit.
        finding2 = await classify_adverse_media(
            company_name="CACHE CO LTD",
            registration_number="44444444",
            source_label="cache_article",
            article_text=article_text,
        )

    assert finding1.is_adverse == finding2.is_adverse
    assert mock_call.call_count == 1


async def test_different_registration_numbers_do_not_collide():
    """
    Same article text, different registration numbers → two distinct cache keys →
    two separate LLM calls, never a cached collision.

    Motivation: the same-name fixture shows that identical article text can produce
    different findings for different companies (adverse for the Frankfurt GmbH,
    NOT_ADVERSE for SC987654). Without registration_number in the key, the second
    company would silently receive the first company's cached classification.
    """
    article_text = "Shared article text that could be assessed for multiple companies."

    with (
        patch(_PATCH_LOAD, return_value="mock prompt text"),
        patch(_PATCH_CLIENT, return_value=MagicMock()),
        patch(_PATCH_CALL, new_callable=AsyncMock) as mock_call,
    ):
        # Simulate: first company finds the article adverse, second does not.
        mock_call.side_effect = [
            json.dumps(_VALID_PAYLOAD),       # company A → ADVERSE
            json.dumps(_NOT_ADVERSE_PAYLOAD), # company B → NOT_ADVERSE (same article!)
        ]

        finding_a = await classify_adverse_media(
            company_name="COMPANY A LTD",
            registration_number="66666666",   # different registration number
            source_label="shared_article",
            article_text=article_text,
        )
        finding_b = await classify_adverse_media(
            company_name="COMPANY B LTD",
            registration_number="77777777",   # different registration number
            source_label="shared_article",
            article_text=article_text,
        )

    # Each company must produce its own LLM call — no cross-company cache hit.
    assert mock_call.call_count == 2
    assert finding_a.is_adverse is True
    assert finding_b.is_adverse is False


async def test_not_adverse_finding_is_valid():
    """
    A NOT_ADVERSE response is still a valid AdverseMediaFinding — is_adverse=False.
    """
    with (
        patch(_PATCH_LOAD, return_value="mock prompt text"),
        patch(_PATCH_CLIENT, return_value=MagicMock()),
        patch(_PATCH_CALL, new_callable=AsyncMock) as mock_call,
    ):
        mock_call.return_value = json.dumps(_NOT_ADVERSE_PAYLOAD)

        finding = await classify_adverse_media(
            company_name="VICTIM CO LTD",
            registration_number="55555555",
            source_label="victim_article",
            article_text="Unique article about a victim company.",
        )

    assert finding.is_adverse is False
    assert finding.category == "NOT_ADVERSE"
    assert finding.severity == "info"

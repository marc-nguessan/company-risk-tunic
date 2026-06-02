"""
OpenRouter LLM client — wraps the openai SDK pointed at OpenRouter's API.

Only two jobs are allowed to call this module:
  1. Entity-disambiguation tie-breaking (Phase 2+ entity_resolution)
  2. Adverse-media structuring (AdverseMediaSource)

Everything else in the pipeline is deterministic and LLM-free by design.

Guarantees:
  - Structured output via response_format json_schema (schema generated FROM
    the Pydantic model so they can't drift)
  - temperature=0, pinned model, max_tokens cap (determinism + budget guardrail)
  - Validate → retry-once → LLMValidationError (never silently returns garbage)
  - Markdown-fence stripping before JSON parse (defensive, belt-and-suspenders)
  - In-memory cache keyed by sha256(model:prompt_version:input_text)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app import config

_PROMPT_DIR = Path(__file__).parent / "prompts"
_LOG = logging.getLogger(__name__)

# In-memory result cache.
# Key: sha256(model:prompt_version:article_text)
# Value: validated Pydantic model instance
# Rationale: LLMs are not bit-reproducible even at temperature=0, so caching
# by input hash is the only way to get true run-to-run reproducibility.
_cache: dict[str, BaseModel] = {}


def clear_cache() -> None:
    """Purge the in-memory cache. Primarily used in tests."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Singleton async client
# ---------------------------------------------------------------------------

# Using AsyncOpenAI because all DataSource.fetch() methods are async.
# CLAUDE.md shows the sync OpenAI client for illustration; AsyncOpenAI is the
# correct choice when running inside an asyncio event loop.
_openai_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Set it in .env to enable LLM features."
            )
        _openai_client = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            default_headers={
                # OpenRouter attribution headers (optional, harmless to include)
                "HTTP-Referer": "https://github.com/company-risk-assessment",
                "X-Title": "Company Risk Assessment",
            },
        )
    return _openai_client


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _load_prompt(name: str, version: str) -> str:
    """Load backend/app/llm/prompts/{name}_{version}.txt."""
    path = _PROMPT_DIR / f"{name}_{version}.txt"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    """
    Remove markdown code fences before JSON parsing.
    Even with json_schema response_format, some models occasionally wrap output
    in ``` blocks. Fail-closed: strip defensively, never parse the fence itself.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _cache_key(model: str, prompt_version: str, text: str) -> str:
    """Deterministic cache key — identical inputs always map to the same key."""
    payload = f"{model}:{prompt_version}:{text}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Core LLM call (separated to make mocking in tests clean)
# ---------------------------------------------------------------------------


async def _call_llm(
    client: AsyncOpenAI,
    messages: list[dict[str, str]],
    response_format: dict[str, Any],
) -> str:
    """Single chat-completion call. Returns the raw string content."""
    response = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,  # type: ignore[arg-type]
        response_format=response_format,  # type: ignore[arg-type]
        temperature=0,
        max_tokens=512,  # budget guardrail
    )
    return response.choices[0].message.content or ""


def _parse_and_validate(content: str, model_cls: type[BaseModel]) -> BaseModel:
    """
    Strip fences → parse JSON → validate against Pydantic model.
    Logs and re-raises on any failure so callers know exactly what failed.
    """
    cleaned = _strip_fences(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        _LOG.error(
            "JSON parse error after fence-stripping: %s | raw (first 300 chars): %.300s",
            exc,
            cleaned,
        )
        raise
    return model_cls.model_validate(data)


# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------


class LLMValidationError(Exception):
    """Raised when LLM output fails Pydantic validation even after one retry."""


# ---------------------------------------------------------------------------
# Adverse-media classification
# ---------------------------------------------------------------------------


async def classify_adverse_media(
    company_name: str,
    registration_number: str,
    source_label: str,
    article_text: str,
    prompt_version: str = "v1",
) -> "AdverseMediaFinding":  # noqa: F821 — imported lazily to avoid circular import
    """
    Classify whether article_text contains adverse media about the named company.

    Returns a validated AdverseMediaFinding.
    Retries exactly once on validation failure, appending the error to the
    conversation so the model can self-correct.
    Raises LLMValidationError if both attempts fail.
    """
    # Import here to keep the circular-import surface minimal.
    from app.models import AdverseMediaFinding

    key = _cache_key(config.LLM_MODEL, prompt_version, article_text)
    if key in _cache:
        _LOG.debug("Cache hit: %s / %s", registration_number, source_label)
        return _cache[key]  # type: ignore[return-value]

    system_prompt = _load_prompt("adverse_media", prompt_version)
    user_template = _load_prompt("adverse_media_user", prompt_version)

    user_message = user_template.format(
        company_name=company_name,
        registration_number=registration_number,
        source_label=source_label,
        article_text=article_text,
    )

    # Generate the schema FROM the Pydantic model so they can't drift.
    schema = AdverseMediaFinding.model_json_schema()
    response_format: dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": "AdverseMediaFinding",
            "strict": True,
            "schema": schema,
        },
    }

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    client = _get_client()

    # ── First attempt ────────────────────────────────────────────────────────
    content = await _call_llm(client, messages, response_format)
    first_err_str: str | None = None
    try:
        finding = _parse_and_validate(content, AdverseMediaFinding)
        _cache[key] = finding
        return finding  # type: ignore[return-value]
    except (json.JSONDecodeError, ValidationError) as exc:
        # Capture the error message before the except block ends — Python
        # deletes the exception variable when the except clause exits.
        first_err_str = str(exc)
        _LOG.warning(
            "First LLM attempt failed for %s / %s: %s — retrying once.",
            registration_number,
            source_label,
            first_err_str,
        )

    # ── Retry: append failed response + error so model can self-correct ──────
    retry_messages: list[dict[str, str]] = [
        *messages,
        {"role": "assistant", "content": content},
        {
            "role": "user",
            "content": (
                f"Your previous response failed schema validation: {first_err_str}\n"
                "Please return a corrected JSON object that exactly matches the "
                "required schema. Do not wrap it in markdown code fences."
            ),
        },
    ]
    content2 = await _call_llm(client, retry_messages, response_format)
    try:
        finding = _parse_and_validate(content2, AdverseMediaFinding)
        _cache[key] = finding
        return finding  # type: ignore[return-value]
    except (json.JSONDecodeError, ValidationError) as second_err:
        _LOG.error(
            "LLM retry also failed for %s / %s: %s",
            registration_number,
            source_label,
            second_err,
        )
        raise LLMValidationError(
            f"adverse-media classification failed after retry "
            f"({registration_number}/{source_label}): {second_err}"
        ) from second_err

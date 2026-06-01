# Claude Code Kickoff Prompt

> Paste the block below as your first message to Claude Code, from inside the repo root
> (the directory that contains `CLAUDE.md`). It drives the build in five vertical phases and
> tells Claude Code to checkpoint with you between phases so you stay in control and within the
> 3–4 hour box. After phase 1, you can let it run more autonomously if you're happy with the shape.

---

You are pairing with me as a senior engineer on a take-home exercise. The full specification and
all binding architectural decisions are in `CLAUDE.md` in this repo — read it completely before
writing anything, and treat it as the source of truth. If you ever want to deviate from it, stop
and flag the trade-off first.

Context that matters: this is graded on (1) end-to-end correctness incl. non-functional
requirements, (2) core software engineering — structure, tests, error handling, observability,
(3) LLM integration — schema enforcement, prompt structure, evaluation, versioning, guardrails
against non-determinism, and (4) product instincts. The LLM is a small, fenced-off subsystem, not
the centrepiece. The risk score must be deterministic and must not depend on LLM randomness.

Work in the five phases defined in CLAUDE.md's "Build order", **building a thin vertical slice
first**. After each phase, stop, give me a 3–4 line summary of what you built and any decisions or
trade-offs you made, and wait for me to say continue. Do not jump ahead.

Phase 1 — the skeleton must stream end-to-end before any real data:
- Create the repo layout from CLAUDE.md.
- Implement `backend/app/models.py` (the Pydantic contracts) first and get them right.
- Implement `sources/base.py` (the `DataSource` ABC with `safe_fetch` timeout/exception wrapping).
- Implement the orchestrator with TWO STUBBED sources that return canned `SourceResult`s after a
  short artificial delay, streamed over an SSE `POST /assess` endpoint in `main.py`.
- Scaffold the Vite + React + TS frontend with a `useAssessment` hook that consumes the SSE stream
  and renders source cards transitioning pending → ok.
- Add `.env.example`, `pyproject.toml`, ruff/mypy config, and a README stub.
- Give me exact run instructions and confirm the stream works before moving on.

Then stop and wait for me.

General working rules for the whole exercise:
- Keep code basic and readable; clarity over cleverness. This is a prototype, not production.
- Every `RiskSignal` carries provenance (`source` + `evidence`).
- No secrets in code. Read config from env via `config.py`.
- Tests are targeted, not exhaustive: scoring table tests, one respx-backed source test, one
  LLM-validation-retry test. Don't chase coverage.
- Record real Companies House responses into `backend/fixtures/` so tests run offline.
- When you use the LLM, go through OpenRouter using the `openai` Python SDK (OpenAI-compatible,
  base_url `https://openrouter.ai/api/v1`). Enforce structured output with
  `response_format={"type":"json_schema","json_schema":{...,"strict":true,
  "schema": <PydanticModel>.model_json_schema()}}`, `temperature=0`, a pinned configurable model
  (`LLM_MODEL`, an OpenRouter `provider/model` slug), versioned prompt files, and a
  validate-then-retry-once guardrail with a `max_tokens` cap and a defensive fence-stripping parser.
- Commit at the end of each phase with a clear message.

Start with Phase 1 now.

---

## Tips while running it

- **Get the Companies House key first** (free): register at developer.company-information.service.gov.uk,
  create an application, copy the key into `.env` as `CH_API_KEY`. Auth is HTTP Basic with the key
  as username and a blank password.
- Put the **reviewers' OpenRouter API key** in `.env` as `OPENROUTER_API_KEY`, set
  `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`, and set `LLM_MODEL` to the OpenRouter
  `provider/model` slug they specified (e.g. `anthropic/claude-sonnet-4`). Confirm that model
  supports structured outputs on OpenRouter's models page.
- If Claude Code drifts from CLAUDE.md, just say: "re-read CLAUDE.md section X and correct."
- Between phases, eyeball the diff yourself — for a senior role, being able to say in interview
  *why* each decision was made matters more than the line count.
- Good real test companies: a very new company (high recency risk), a dissolved one, and a
  director with many appointments — pick these so your eval set shows real signal variation.

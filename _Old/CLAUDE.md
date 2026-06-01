# CLAUDE.md — Company Risk Assessment

> This file is the source of truth for how this project is built. Read it fully before writing
> any code, and re-read the relevant section before each task. Do not deviate from these
> decisions without flagging the trade-off explicitly.

## What this is

A prototype that gathers and structures information about a company so it can be risk-assessed
as a **payment beneficiary** (the recipient of a payment). This is a take-home exercise for a
Senior Software Engineer role at Tunic Pay, a fraud-prevention fintech that scores payment
beneficiaries in real time to stop Authorised Push Payment (APP) scams.

A beneficiary is riskier if it: was incorporated recently / files sparsely, has directors who
are directors of many other companies (mule-network signal), or appears in scam reports /
adverse media.

## Guiding thesis (keep this in mind for every decision)

This is a **fan-out aggregation problem with an unreliable last mile.** The architecture is a set
of independent, individually-degradable data sources that stream into a normalized risk model.
The LLM is used surgically — only for fuzzy entity resolution and for turning unstructured
adverse-media text into structured signals — and is fenced off everywhere else with schemas,
timeouts, determinism controls, and validation+retry. The **risk score itself is fully
deterministic and never depends on LLM randomness.**

## Hard constraints

- **Languages:** Python (backend) + TypeScript/React (frontend) only. No other languages.
- **Time box:** This is a 3–4 hour exercise. Favour a thin, polished, end-to-end vertical slice
  over broad-but-broken coverage. Clarity over cleverness.
- **Mocking is allowed and expected** for data-source *retrieval* — but the *processing* must be
  real. Mock the network, not the logic.
- **Never crash the whole assessment because one source failed.** Degrade gracefully.
- **Every risk signal must carry provenance** (which source produced it + supporting evidence).
  This is a compliance/fraud product; auditability is a feature, not a nicety.
- Do not commit secrets. Use `.env`; ship `.env.example`.

## Stack (do not substitute without flagging)

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn |
| Async / HTTP | asyncio, httpx.AsyncClient |
| Validation / schema | Pydantic v2 (the schema IS the contract) |
| LLM | Anthropic Python SDK, using **tool use** for structured output |
| Frontend | Vite + React + TypeScript (NOT Next.js, NOT Streamlit) |
| Streaming | Server-Sent Events (SSE) via EventSource |
| Backend tests | pytest, pytest-asyncio, respx (mock httpx at the transport layer) |
| Frontend tests | Vitest |
| Tooling | ruff + mypy (Python), eslint + tsc (TS), uv for dependency management |

## Architecture

```
React UI (Vite+TS)  --POST /assess (SSE stream)-->  FastAPI Orchestrator
                                                       1. resolve entity
                                                       2. fan-out sources (asyncio)
                                                       3. stream each result as it lands
                                                       4. deterministic score + aggregate
        sources implement a common DataSource ABC:
          - CompaniesHouseSource  (REAL  — free official UK API)
          - DirectorNetworkSource (REAL  — officers + appointments)
          - AdverseMediaSource    (MOCKED retrieval, REAL LLM structuring)
```

## Data model (build this FIRST, in `backend/app/models.py`)

These Pydantic models are the contract shared by the LLM output, the API response, and the
scoring function. Get them right before anything else.

- `CompanyQuery`: `company_name: str | None`, `registration_number: str | None`, `jurisdiction: str = "GB"`.
  At least one of name/number is present.
- `EntityCandidate`: `registration_number`, `name`, `status`, `match_confidence: float`, `address: str | None`.
- `ResolvedEntity`: the single chosen candidate the assessment runs against.
- `RiskSignal`:
  - `code: str` (e.g. `"RECENTLY_INCORPORATED"`)
  - `severity: Literal["info","low","medium","high"]`
  - `score_contribution: float`  (0–100, pre-weighting)
  - `explanation: str`  (human-readable, shown in UI)
  - `source: str`  (provenance)
  - `evidence: dict | None`  (raw supporting data)
- `SourceResult`:
  - `source_name: str`
  - `status: Literal["pending","ok","partial","error","timeout"]`
  - `latency_ms: int`
  - `signals: list[RiskSignal]`
  - `raw: dict | None`
  - `error: str | None`
- `CompanyRiskAssessment`:
  - `query`, `resolved_entity: ResolvedEntity | None`, `candidates: list[EntityCandidate]`
  - `overall_risk_score: float` (0–100)
  - `risk_band: Literal["low","medium","high"]`
  - `sources: list[SourceResult]`
  - `completeness: float`  (% expected fields populated)
  - `confidence: float`    (derived from source health — DISTINCT from risk)
  - `generated_at: datetime`
  - `prompt_version: str`

## Source abstraction (`backend/app/sources/base.py`)

```python
class DataSource(ABC):
    name: str
    timeout_s: float = 5.0

    @abstractmethod
    async def fetch(self, entity: ResolvedEntity) -> SourceResult: ...

    async def safe_fetch(self, entity: ResolvedEntity) -> SourceResult:
        # Wrap fetch() in asyncio.wait_for(timeout_s) and try/except.
        # On timeout -> SourceResult(status="timeout"). On exception -> status="error".
        # NEVER raise out of safe_fetch. This is where flaky-data robustness lives.
```

The orchestrator holds `sources: list[DataSource]` and a registry. Adding a source must be
**one new class + one registry entry** — that is the extensibility story, demonstrated.

## The three sources

### CompaniesHouseSource (REAL)
Free official UK API (`https://api.company-information.service.gov.uk`). HTTP Basic auth: API key
as username, blank password. Key endpoints:
- `GET /search/companies?q=...` → entity-resolution candidates
- `GET /company/{company_number}` → `date_of_creation`, `company_status`, `accounts`
- `GET /company/{company_number}/filing-history` → filing recency / sparsity

Signals to emit: `RECENTLY_INCORPORATED` (<12mo → medium, <3mo → high), `DISSOLVED_OR_LIQUIDATION`,
`SPARSE_FILING_HISTORY`, `OVERDUE_ACCOUNTS`.

Record real API responses into `backend/fixtures/` so tests run offline via respx.

### DirectorNetworkSource (REAL)
- `GET /company/{company_number}/officers`
- per officer: `GET /officers/{officer_id}/appointments`
Signal: `DIRECTOR_MULTIPLE_APPOINTMENTS`, severity scaling with active-appointment count
(e.g. >15 medium, >30 high). This mirrors Tunic's real recipient-intelligence angle.

### AdverseMediaSource (MOCKED retrieval, REAL LLM processing)
- Ship 3–4 fixture text blobs in `backend/fixtures/adverse_media/`.
- Feed raw text to Claude via **tool use**; the tool's `input_schema` is the JSON schema of a
  Pydantic model `AdverseMediaFinding {is_adverse, category, severity, summary}`. Force the tool call.
- Emit `ADVERSE_MEDIA_MENTION` signals from validated findings.
- Document the clean seam where a real source (news API, sanctions list) would slot in.

## LLM integration rules (this is heavily graded — follow exactly)

1. **Only two jobs touch the LLM:** (a) entity disambiguation tie-breaking when Companies House
   returns several fuzzy matches; (b) adverse-media structuring. Nothing else. Show judgment about
   when NOT to use an LLM.
2. **Structured output via tool use**, never prose parsing. Define an Anthropic tool whose
   `input_schema` equals the Pydantic model's JSON schema; set `tool_choice` to force it.
3. **Determinism / reproducibility:** `temperature=0`, pinned model string, frozen system prompt,
   deterministically-sorted inputs. State in the README that LLMs are not bit-reproducible even at
   temp 0, so (a) cache by input hash, and (b) keep SCORING fully deterministic and LLM-free.
4. **Prompt versioning:** prompts live in `backend/app/llm/prompts/<name>_v1.txt`, loaded by version,
   and the version string is stamped into every assessment's `prompt_version`.
5. **Guardrails (satisfies stretch goal):**
   - Validation-and-retry: if tool args fail Pydantic validation, re-prompt ONCE with the
     validation error appended, then fall back to a `status="error"` SourceResult.
   - `max_tokens` budget cap on every call.
6. The model and key come from env: `ANTHROPIC_API_KEY`. Use the model string the reviewers
   provide; default to a current Claude model and make it configurable.

## Orchestration & streaming (`backend/app/orchestrator.py`)

- `async def assess(query) -> AsyncIterator[Event]`:
  1. Resolve entity. If multiple strong matches and no reg number → yield
     `needs_disambiguation` with candidates and stop (UI lets user pick, re-submits with number).
  2. yield `entity_resolved`.
  3. Launch `safe_fetch` for all sources; consume with `asyncio.as_completed` and yield a
     `source_result` event as EACH lands (progressive updates).
  4. Aggregate deterministically; yield `final` with the full `CompanyRiskAssessment`.
- **10s latency budget:** each source has a hard timeout; total wall-clock is bounded by the
  slowest timeout, not the sum. Fast CH profile shows in ~1s; LLM adverse media trickles in.
- Expose `POST /assess` returning `text/event-stream`.

## Scoring & evaluation (named rubric item — do not skip)

- `backend/app/scoring.py`: pure function `aggregate_and_score(signals) -> (score, band)`.
  Weighted sum of `score_contribution`, normalized to 0–100, banded: low <30, medium 30–65, high >65.
  Weights live in a config dict so they're tunable. Fully deterministic. Table-driven unit tests.
- `completeness`: % of expected fields populated across sources.
- `confidence`: derived from source health (how many sources returned `ok` vs `error/timeout`).
  MUST be distinct from risk — "low risk" and "we couldn't find enough to tell" are different
  outcomes, and a fraud analyst needs to see which one they're looking at.
- `backend/evals/`: a small script running the pipeline against ~5 fixture companies with expected
  signal sets, printing a pass/coverage table. This is the answer to "how do you know a prompt
  change helped or hurt" — run it before/after a change.

## Frontend (`frontend/`)

Single view. Components:
- `SearchBar` — name or registration number.
- `DisambiguationList` — renders on `needs_disambiguation`; lets the user pick the right entity.
  (Directly answers the "Tunic Pay → Tunic & Co UK Limited" question — give this real care.)
- `SourceCard` — per-source live status: pending spinner → ok/error/timeout, shows signals.
- `RiskSummary` — band, score, confidence gauge, completeness, "Assessment complete" final state.
- `useAssessment` hook — consumes SSE via `EventSource`, folds events into state with a reducer.
Visual priority: information hierarchy and clear pending-vs-final states, not chrome. Minimal CSS
or Tailwind. Show "2 of 3 sources complete" progress; distinct visual for the final state.

## Repo layout

```
company-risk/
├── README.md
├── CLAUDE.md
├── .env.example                 # ANTHROPIC_API_KEY, CH_API_KEY, ANTHROPIC_MODEL
├── docker-compose.yml           # optional one-command run
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py              # FastAPI app, /assess SSE endpoint
│   │   ├── models.py            # Pydantic contracts — BUILD FIRST
│   │   ├── orchestrator.py
│   │   ├── scoring.py
│   │   ├── entity_resolution.py
│   │   ├── config.py
│   │   ├── llm/
│   │   │   ├── client.py        # tool-use wrapper, retry, caching
│   │   │   ├── tools.py         # tool/schema definitions
│   │   │   └── prompts/
│   │   └── sources/
│   │       ├── base.py
│   │       ├── companies_house.py
│   │       ├── director_network.py
│   │       └── adverse_media.py
│   ├── fixtures/
│   ├── evals/
│   └── tests/
└── frontend/                    # Vite React TS
    └── src/{components,hooks,types}
```

## README must contain

Run instructions; the architecture diagram; key decisions WITH trade-offs; example input/output
JSON; and a crisp "What I'd do differently with more time" (real news/sanctions sources; Redis
cache + queue for 1000 QPS; persistent eval dataset; PSC/beneficial-ownership signals;
OpenTelemetry tracing). Include the explicit 1000 QPS answer: stateless workers behind an LB;
LLM/source calls on a queue with job-id + push results; cache by
`(company_number, source, prompt_version)` in Redis with per-source TTLs; rate-limit and
circuit-break each upstream; batch LLM calls.

## Definition of done

- `POST /assess` streams entity_resolved → source_result(s) → final over SSE.
- Companies House + Director sources hit the real API; adverse media is mocked-retrieval + real LLM.
- One bad/slow source degrades to a card, never crashes the run.
- Risk score is deterministic; confidence is separate from risk.
- Tests: scoring table tests, one respx-backed source test, one LLM-validation-retry test.
- Eval script runs and prints a coverage table.
- README complete with diagram, trade-offs, examples, and the scaling answer.

## Build order (vertical slice first — do NOT build horizontally)

1. `models.py` + `sources/base.py` + orchestrator skeleton with TWO STUBBED sources streaming
   fake data end-to-end over SSE, and a minimal React view that renders the stream. Prove the
   pipe works before adding real data.
2. Real CompaniesHouseSource + DirectorNetworkSource + entity_resolution + scoring.
3. AdverseMediaSource with tool-use schema + validation/retry guardrail + prompt versioning.
4. Frontend polish: disambiguation flow, live source cards, summary.
5. Tests + eval script + README.

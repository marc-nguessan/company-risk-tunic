# Company Risk Assessment

> Prototype that gathers and structures information about a company so it can be risk-assessed as a
> **payment beneficiary** — the recipient of a payment. Built for the Tunic Pay take-home exercise.

A beneficiary is riskier if it was incorporated recently / files sparsely, has directors who sit on
many other companies (a mule-network signal), or appears in scam reports or adverse media. This tool
fans out to independent data sources, normalises everything into a single risk model, and streams the
result to the UI as each source lands.

---

## 1. What it does & how to run it

Enter a company name or Companies House registration number. The backend resolves the entity, fans
out to three data sources in parallel, streams each source's result over SSE as it completes, and
finishes with a deterministic risk score, band, confidence, and completeness.

### Prerequisites

- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/) (or plain `pip` + `venv` — see fallback below)
- **Node 18+** and `npm`
- **No API keys are required to run the demo.** `CH_USE_FIXTURES=true` (the default) serves
  Companies House data from local fixtures, and the eval harness and tests stub the LLM. You only
  need keys to hit the live Companies House API or to run live adverse-media classification.

### Environment variables

Copy `.env.example` to `.env` and fill in as needed. All config is read from env via `app/config.py`
— nothing is hardcoded.

| Variable | Purpose | Default |
|---|---|---|
| `CH_USE_FIXTURES` | `true` → serve Companies House from local fixtures (offline). `false` → call the live API. | `true` |
| `CH_API_KEY` | Companies House API key (only needed when `CH_USE_FIXTURES=false`). HTTP Basic auth: key as username, blank password. | — |
| `OPENROUTER_API_KEY` | OpenRouter key (prefix `sk-or-v1-`). Only needed for live adverse-media classification. | — |
| `OPENROUTER_BASE_URL` | OpenRouter API base. | `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | OpenRouter `provider/model` slug. Must support structured outputs (`json_schema`). | `anthropic/claude-sonnet-4-5` |

### Backend

```bash
cd backend
uv sync                                          # installs deps into .venv
uv run uvicorn app.main:app --reload --port 8000
```

<details>
<summary>pip / venv fallback (if you don't have <code>uv</code>)</summary>

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e .            # or: .venv/bin/pip install fastapi "uvicorn[standard]" httpx pydantic openai python-dotenv sse-starlette
.venv/bin/pip install pytest pytest-asyncio respx   # dev deps for tests
.venv/bin/uvicorn app.main:app --reload --port 8000
```
</details>

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /assess → http://localhost:8000)
```

Open http://localhost:5173 and try:
- `06789012` — overdue accounts (medium risk)
- `14999001` — recently incorporated + mule-network director + FCA warning (high risk)
- `LTD` — triggers the **disambiguation** flow (matches all fixture companies)
- `ZZZNOMATCH` — the **no-match** empty state

### Run the tests (single command)

```bash
cd backend && uv run pytest        # or: .venv/bin/pytest
```

### Run the eval harness (single command, no API key needed)

```bash
cd backend && uv run python evals/run_evals.py     # or: .venv/bin/python evals/run_evals.py
```

### Try the stream directly

```bash
curl -N -X POST http://localhost:8000/assess \
  -H "Content-Type: application/json" \
  -d '{"registration_number": "06789012"}'
```

---

## 2. Architecture

The guiding thesis: **this is a fan-out aggregation problem with an unreliable last mile.** The
architecture is a set of independent, individually-degradable data sources that stream into a
normalised risk model. The LLM is used surgically — only for fuzzy entity resolution and for turning
unstructured adverse-media text into structured signals — and is fenced off everywhere else with
schemas, timeouts, determinism controls, and validation-and-retry. **The risk score is fully
deterministic and never depends on LLM randomness.**

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

### The `DataSource` abstraction

Every source implements one method, `fetch(entity) -> SourceResult`, and inherits `safe_fetch()`,
which wraps `fetch()` in `asyncio.wait_for(timeout_s)` plus a try/except. On timeout it returns
`status="timeout"`; on any exception, `status="error"`. **`safe_fetch` never raises** — this is where
the flaky-last-mile robustness lives. The orchestrator only ever calls `safe_fetch`, so one bad
source can never crash the run; it just becomes an error card.

Adding a source is **one new class + one registry entry** in `orchestrator._SOURCES`. That is the
entire extensibility story.

### Normalised risk model

Each source emits zero or more `RiskSignal`s. Every signal carries `code`, `severity`,
`score_contribution`, a human-readable `explanation`, its `source` (provenance), and an `evidence`
dict with the raw supporting data. Auditability is a feature, not a nicety — this is a fraud product.
The deterministic scorer sums weighted contributions into a single 0–100 score and band.

### Streaming

`POST /assess` returns `text/event-stream`. The orchestrator is an async generator that yields typed
events: `entity_resolved` → `source_result` (one per source, as each lands via
`asyncio.wait(FIRST_COMPLETED)`) → `final`. If a name matches several companies and no registration
number was given, it yields `needs_disambiguation` and stops; if nothing matches, `error`.

---

## 3. Key design decisions (with trade-offs)

**The LLM is fenced to two narrow jobs; the score is deterministic and LLM-free.**
The LLM only does (a) entity-disambiguation tie-breaking and (b) adverse-media structuring. The risk
score is a pure weighted sum of signal contributions in `scoring.py` — no model output feeds it.
*Why:* a fraud score must be auditable, reproducible, and explainable to a regulator; LLM randomness
must never move it. *Trade-off:* the system can't "learn" new risk patterns without a code change to
the weights or signal logic — but that's the right trade for a compliance product.

**Schema-forced structured output + validate-and-retry.**
The adverse-media call uses OpenRouter's `response_format={"type":"json_schema", …, "strict":true}`,
and the schema is generated *from* the Pydantic model via `model_json_schema()` so the wire contract
and the validator can never drift. The returned JSON is fence-stripped, parsed, and validated against
the model; on failure we re-prompt **once** with the validation error appended, then fail closed to a
`status="error"` SourceResult. Every call has `temperature=0` and a `max_tokens` cap.
*Trade-off:* one extra round-trip on a malformed response, and `strict` schemas constrain prompt
phrasing — both worth it for reliability.

**Prompt versioning via files + an eval harness.**
Prompts live in `app/llm/prompts/adverse_media_v1.txt` (system) and `…_user_v1.txt` (user template),
loaded by version string, and the version is stamped into every assessment's `prompt_version`. The
eval harness (`evals/run_evals.py`) is the concrete answer to "how do you know a prompt change helped
or hurt": run it before and after a change and diff the coverage table. *Trade-off:* the offline
harness stubs the LLM for determinism, so you collect live verdicts separately and bake them into the
stub set when bumping a version — a deliberate split between "did signal extraction regress" (offline,
fast) and "did the model's judgement change" (live, on demand).

**Confidence vs completeness — two distinct numbers, deliberately.**
- **Confidence** = source *health*: how many sources returned `ok` vs `error`/`timeout`. It answers
  *"can we trust this result?"*
- **Completeness** = data *coverage*: how many expected fields were actually populated with non-empty
  data across all sources. It answers *"how thoroughly was this company profiled?"*

These must not collapse into one number. "Low risk" and "we couldn't gather enough to tell" are
different outcomes, and a fraud analyst needs to see which they're looking at. A healthy company with
one director, sparse filings, and no media coverage yields **high confidence, low completeness** — the
06789012 example below shows exactly this (`confidence: 1.0`, `completeness: 0.67`). A single blended
score would hide that distinction and mislead.

**Lightweight declared-field completeness.**
Completeness uses a small declared table (`_SOURCE_EXPECTED_FIELDS` in `scoring.py`) mapping each
source to the raw-dict keys it should populate, and counts how many are non-empty. *Trade-off:* it's a
hand-maintained list rather than schema introspection. A fuller version would derive expected fields
from each source's output Pydantic model (or a per-source "expected coverage" descriptor) so the two
can't drift — but for a prototype the explicit table is more readable and obviously correct.

**`CH_USE_FIXTURES` for offline development.**
A single env flag swaps the *retrieval* step between local fixtures and the live API; the parsing,
signal-generation, and scoring logic is **identical on both paths** — only the two private
`_load_*`/`_fetch_*` methods differ. *Why:* the exercise must run and be testable without a key, and
the fixtures double as the offline test corpus (recorded to mirror the real CH Public Data API
schemas). *Trade-off:* fixtures can stage-drift from the real API, mitigated by modelling them on the
documented response shapes and recording real responses where possible.

**SSE over WebSockets.**
The interaction is strictly one-directional server-push for the duration of an assessment, so
Server-Sent Events fit exactly: simpler than WebSockets, work over plain HTTP, no extra protocol.
*Trade-off:* no client→server channel mid-stream (not needed here) and a browser
6-connections-per-host limit (irrelevant for one assessment at a time). One wrinkle: `EventSource` is
GET-only, so the client uses `fetch` + a `ReadableStream` reader to POST and parse the stream itself —
which also trades away `EventSource`'s native auto-reconnect (an assessment is a one-shot stream, so
this doesn't matter here).

---

## 4. Product decisions & assumptions flagged

These are judgement calls made during the build that a reviewer should be able to challenge:

- **Unknown-age companies and the filing-history check.** A Charitable Incorporated Organisation
  (fixture `00000042`) can have a missing/empty `date_of_creation`. The age-based
  `RECENTLY_INCORPORATED` check correctly emits nothing. But the sparse-filing check, lacking an age to
  reason about, currently *does* fire `SPARSE_FILING_HISTORY` for it. Assumption: a company we can't age
  and that has filed nothing is genuinely worth flagging. If the product decision is "suppress
  filing-history checks when age is unknown", that's a one-line guard.

- **Sparse-filing threshold for mature companies.** `SPARSE_FILING_HISTORY` fires when a company older
  than 12 months has fewer than 3 filings in the trailing year. The 12-month suppression avoids
  penalising brand-new companies (which legitimately haven't filed yet). The "3 in 12 months" bar is a
  reasonable-looking default, not a calibrated one — it should be tuned against labelled data.

- **A dissolved company does not implicitly resign its officers.** When counting a director's active
  appointments, an appointment with no `resigned_on` counts as active **even if the appointed-to
  company has since been dissolved** — the API returns no server-side filter and dissolution doesn't
  auto-resign officers. This is deliberate: a director racking up appointments at companies that later
  dissolve is exactly the mule-network pattern we want to catch, not hide.

- **Disambiguation requires a registration number to proceed.** When a name matches several companies,
  we stop and ask rather than guessing. Selecting a candidate re-submits by registration number — the
  unambiguous path. Assumption: a wrong auto-pick in a fraud product is worse than one extra click.

---

## 5. Answers to the brief's "questions for consideration"

**Progressive results & knowing when results are final.** Each source streams its card the moment it
lands (`asyncio.wait(FIRST_COMPLETED)`), so the fast Companies House profile appears in ~1s while the
slower adverse-media/LLM path trickles in. While running, the UI shows a `"2 of 3 sources complete"`
counter and per-card pending spinners. When the `final` event arrives, the UI flips to an
unmistakable green **"Assessment complete"** banner with the score, band, confidence, and
completeness. The user is never left guessing whether more is coming.

**What happens when a source is slow.** Each source has a hard per-source timeout (`timeout_s`), so
total wall-clock is bounded by the *slowest single source*, not the sum. A source that exceeds its
budget degrades to a `timeout` card; one that errors degrades to an `error` card — visually distinct
from a source that succeeded but found nothing ("No risk signals found", green). The assessment always
completes. Confidence drops to reflect the degraded source health.

**Company-name ambiguity UX.** This is the "Tunic Pay → Tunic & Co UK Limited" problem. Three states,
each visually distinct from a loading spinner:
- **Multi-match** → a `DisambiguationList` showing each candidate's name, registration number, status
  badge, and address so the user can tell them apart; selecting one re-runs by registration number.
- **No match** → a neutral, calm "No company found" panel (not an alarming error), suggesting a
  registration-number search.
- **Single / exact match** → resolves straight through, no interruption.

**Prompt versioning & knowing if a change helped.** Versioned prompt files + `prompt_version` stamped
on every assessment + the eval harness. Run `evals/run_evals.py` before and after a prompt edit and
compare the per-case pass/fail and coverage summary. The harness deliberately includes the two hard
adverse-media cases — the **victim** story and the **same-name decoy** — which must both resolve to
`NOT_ADVERSE`; a prompt change that breaks either shows up immediately.

**Scaling to ~1000 queries/minute.** Stateless FastAPI workers behind a load balancer. `POST /assess`
returns a **job-id** immediately; the slow LLM and upstream source calls move onto a **queue**, with
results pushed back to the client (WebSocket / SSE channel keyed by job-id) as they complete. **Cache**
by `(company_number, source, prompt_version)` in Redis with **per-source TTLs** (e.g. CH profile 24h,
director network 6h, adverse media 1h) — most of the load is repeat lookups of the same beneficiaries.
**Rate-limit and circuit-break each upstream** independently (a token bucket per API, a breaker that
sheds load to cached/degraded results when an upstream is failing) so one slow provider can't stall the
fleet. **Batch LLM calls** across concurrent requests where the article set overlaps. The existing
in-process LLM cache (keyed by `model:prompt_version:registration_number:article_text`) is the
single-node version of this; Redis is the multi-node generalisation.

---

## 6. What I'd do differently with more time

- **Real retrieval sources.** Swap mocked adverse-media retrieval for a live news API (GDELT, Dow
  Jones, LexisNexis) and a sanctions/PEP list (OpenSanctions, OFAC/HMT). The seam is already clean —
  it's one private method per source.
- **PSC / beneficial-ownership signals.** The Companies House PSC endpoint exposes hidden ownership
  chains — a strong signal for shell-company and layering detection.
- **Redis cache + job queue.** The 1000 QPM design above; the in-process cache is the prototype stub.
- **A persistent, labelled eval dataset.** Grow `evals/` from 5 hand-built cases into a versioned
  corpus of real companies with analyst-labelled expected signals, tracked over time, with precision/
  recall per signal so prompt and scoring changes are measured, not guessed.
- **OpenTelemetry tracing.** A span per source fetch, latency histograms per source, LLM token-usage
  metrics — essential for spotting which upstream is the bottleneck under load.
- **Richer entity resolution.** Today, name resolution is substring/exact matching (fixtures) or the CH
  search ranking (live). A fuller version would use the LLM disambiguation seam already scaffolded:
  address/postcode matching, SIC-code plausibility, and fuzzy scoring across candidates.

---

## 7. Example input/output

**Input:**

```json
{ "registration_number": "06789012" }
```

**Output** (`final` event payload, `raw` blobs omitted for brevity):

```json
{
  "query": { "company_name": null, "registration_number": "06789012", "jurisdiction": "GB" },
  "resolved_entity": {
    "registration_number": "06789012",
    "name": "DELINQUENT ACCOUNTS LTD",
    "status": "active",
    "match_confidence": 1.0,
    "address": "7 Overdue House, Birmingham, B1 1BB"
  },
  "candidates": [],
  "overall_risk_score": 40.5,
  "risk_band": "medium",
  "sources": [
    { "source_name": "adverse_media", "status": "ok", "signals": [] },
    {
      "source_name": "companies_house",
      "status": "ok",
      "signals": [
        {
          "code": "OVERDUE_ACCOUNTS",
          "severity": "medium",
          "score_contribution": 35.0,
          "explanation": "Overdue: annual accounts (due 2024-04-30) and confirmation statement (due 2025-08-04).",
          "source": "companies_house",
          "evidence": {
            "accounts_overdue": true,
            "accounts_due_on": "2024-04-30",
            "confirmation_overdue": true,
            "confirmation_next_due": "2025-08-04"
          }
        },
        {
          "code": "SPARSE_FILING_HISTORY",
          "severity": "low",
          "score_contribution": 20.0,
          "explanation": "Only 1 filing(s) in the past 12 months.",
          "source": "companies_house",
          "evidence": { "recent_filing_count": 1, "total_count": 5 }
        }
      ]
    },
    { "source_name": "director_network", "status": "ok", "signals": [] }
  ],
  "completeness": 0.67,
  "confidence": 1.0,
  "generated_at": "2026-06-02T11:08:55.270280Z",
  "prompt_version": "adverse_media_v1"
}
```

Note `confidence: 1.0` (all three sources returned `ok`) alongside `completeness: 0.67` (4 of 6
expected fields populated — no adverse-media articles, so that source's two expected fields are empty).
This is the confidence-vs-completeness divergence working as intended: we fully trust the result, but
we didn't have a full data picture to work from.

---

## Project layout

```
├── README.md / CLAUDE.md / .env.example
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, POST /assess SSE endpoint
│   │   ├── models.py            # Pydantic contracts (the shared schema)
│   │   ├── orchestrator.py      # entity resolution → fan-out → stream → score
│   │   ├── scoring.py           # deterministic score + completeness (pure)
│   │   ├── entity_resolution.py
│   │   ├── config.py            # all env config
│   │   ├── llm/
│   │   │   ├── client.py        # OpenRouter wrapper: json_schema, retry, cache
│   │   │   └── prompts/         # versioned prompt files
│   │   └── sources/
│   │       ├── base.py          # DataSource ABC + safe_fetch
│   │       ├── companies_house.py
│   │       ├── director_network.py
│   │       └── adverse_media.py
│   ├── fixtures/                # offline CH + adverse-media corpus
│   ├── evals/run_evals.py       # offline regression harness
│   └── tests/                   # scoring, sources (respx), LLM retry, degradation
└── frontend/                    # Vite + React + TS single view
    └── src/{components,hooks,types,utils}
```

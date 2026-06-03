# Company Risk Assessment

Checks how risky a company is to **receive a payment** — useful for spotting scams where someone is
tricked into paying a fraudulent business. You enter a company name or number; the tool gathers data
from several sources, scores the risk, and shows the result live as each source reports back.

A company looks riskier if it was set up very recently, barely files its paperwork, shares a director
with many other companies (a money-mule pattern), or shows up in news about fraud or regulatory action.

---

## Project layout

```
├── README.md / .env.example
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, POST /assess streaming endpoint
│   │   ├── models.py            # Pydantic data shapes shared everywhere
│   │   ├── orchestrator.py      # resolve company → run sources → stream → score
│   │   ├── scoring.py           # the risk score (plain code, no LLM)
│   │   ├── entity_resolution.py # turn a name/number into one company
│   │   ├── config.py            # all settings, read from environment
│   │   ├── llm/
│   │   │   ├── client.py        # OpenRouter wrapper: strict JSON, retry, cache
│   │   │   └── prompts/         # prompt text files, versioned by name
│   │   └── sources/
│   │       ├── base.py          # DataSource base class + safe_fetch
│   │       ├── companies_house.py
│   │       ├── director_network.py
│   │       └── adverse_media.py
│   ├── fixtures/                # offline sample data (so it runs without keys)
│   ├── evals/run_evals.py       # offline check that signals are still correct
│   └── tests/                   # scoring, sources, LLM retry, failure handling
└── frontend/                    # Vite + React + TypeScript, single screen
    └── src/{components,hooks,types,utils}
```

---

## What it does & how to run it

You enter a company name or Companies House number. The backend finds the matching company, runs three
data sources at the same time, streams each result back as it finishes, and ends with a risk score,
a band (low/medium/high), and two quality measures (confidence and completeness — explained later).

### Prerequisites

- **Python 3.12+** with [`uv`](https://docs.astral.sh/uv/) (or plain `pip` — see fallback)
- **Node 18+** with `npm`
- **No API keys needed for the demo.** By default the tool reads Companies House data from local
  sample files, and the tests and eval harness use a fake LLM. You only need keys to call the real
  Companies House API or run real adverse-media analysis.

### Settings (environment variables)

Copy `.env.example` to `.env`. Everything is read from the environment via `app/config.py` — nothing
is hardcoded.

| Variable | What it's for | Default |
|---|---|---|
| `CH_USE_FIXTURES` | `true` = use local sample data (offline). `false` = call the real API. | `true` |
| `CH_API_KEY` | Companies House key (only when `CH_USE_FIXTURES=false`). Sent as the username, blank password. | — |
| `OPENROUTER_API_KEY` | OpenRouter key (`sk-or-v1-…`). Only for real adverse-media analysis. | — |
| `OPENROUTER_BASE_URL` | OpenRouter API address. | `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | Which model to use (must support strict JSON output). | `anthropic/claude-sonnet-4-5` |

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

<details>
<summary>No <code>uv</code>? Use pip instead</summary>

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install fastapi "uvicorn[standard]" httpx pydantic openai python-dotenv sse-starlette
.venv/bin/pip install pytest pytest-asyncio respx   # for the tests
.venv/bin/uvicorn app.main:app --reload --port 8000
```
</details>

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (forwards /assess to port 8000)
```

Open http://localhost:5173 and try:

- `06789012` — overdue paperwork (medium risk)
- `14999001` — brand new + mule-pattern director + FCA warning (high risk)
- `LTD` — matches several companies, so you get the **"which one?"** picker
- `ZZZNOMATCH` — the **no results** state

### Tests and the eval harness (one command each)

```bash
cd backend && uv run pytest                    # or: .venv/bin/pytest
cd backend && uv run python evals/run_evals.py # or: .venv/bin/python evals/run_evals.py
```

### Call the stream directly

```bash
curl -N -X POST http://localhost:8000/assess \
  -H "Content-Type: application/json" \
  -d '{"registration_number": "06789012"}'
```

---

## Architecture

The core idea: **gather data from many sources, where the last step (fetching) is unreliable.** Each
source is independent and can fail on its own without taking down the rest. The LLM is used in just
one narrow place — turning messy news text into structured findings — and is boxed in with strict
schemas, timeouts, and retries. **The risk score is plain code and never depends on the LLM.**

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

**The `DataSource` base class.** Every source has one method, `fetch()`. They all inherit
`safe_fetch()`, which runs `fetch()` with a time limit and catches every error: a slow source returns
`status="timeout"`, a broken one returns `status="error"`. **`safe_fetch` never throws.** Because the
orchestrator only ever calls `safe_fetch`, one bad source can't crash the run — it just shows up as a
failed card. Adding a new source is one class plus one line in the registry.

**The shared data shape.** Each source produces zero or more `RiskSignal`s. Every signal records what
it found (`code`), how serious it is (`severity`), its points (`score_contribution`), a plain-English
`explanation`, which source it came from, and the raw `evidence` behind it. Keeping the evidence
matters: this is a fraud tool, so every number must be traceable.

**Streaming.** `POST /assess` returns a live event stream. The orchestrator sends: `entity_resolved`
(which company we're checking) → one `source_result` per source as it finishes → `final` (the full
assessment). If a name matches several companies it sends `needs_disambiguation` and stops; if nothing
matches, `error`.

---

## Scoring

The score is **plain arithmetic, fully deterministic** — same inputs always give the same score, and
the LLM never touches it. It lives in `scoring.py`.

Each signal carries a `score_contribution` (0–100) set by the source that raised it. The scorer
multiplies each contribution by a per-signal **weight**, adds them up, and caps the total at 100:

```
score = min(100, Σ (signal.score_contribution × weight[signal.code]))
```

The weights (in `SIGNAL_WEIGHTS`, tunable in one place):

| Signal | Weight |
|---|---|
| `DISSOLVED_OR_LIQUIDATION` | 1.2 |
| `ADVERSE_MEDIA_MENTION` | 1.1 |
| `RECENTLY_INCORPORATED` | 1.0 |
| `DIRECTOR_MULTIPLE_APPOINTMENTS` | 0.9 |
| `SPARSE_FILING_HISTORY` | 0.8 |
| `OVERDUE_ACCOUNTS` | 0.7 |

(Any unlisted signal defaults to weight 1.0.) The final score maps to a **band**:

| Score | Band |
|---|---|
| below 30 | low |
| 30 to under 65 | medium |
| 65 and above | high |

No signals at all → score 0, band low.

**Worked example (06789012):** overdue accounts (contribution 35 × weight 0.7 = 24.5) plus sparse
filings (20 × 0.8 = 16.0) = **40.5**, which lands in the **medium** band. This matches the example
output at the end of this README.

Keeping scoring deterministic and code-based is deliberate: a fraud score has to be auditable and
explainable to a regulator, and reproducible on demand. The cost is that it can't "learn" new patterns
on its own — changing the logic means editing the weights or signal rules — which is the right trade
for a compliance tool.

---

## Key design decisions (and their trade-offs)

**The LLM does one job; the score is LLM-free.** The only place the LLM runs is reading adverse-media
text into a structured finding. The score is computed separately in plain code. *Trade-off:* no
automatic learning, but full auditability and reproducibility. (Entity-disambiguation tie-breaking was
also planned as an LLM job; today that's handled by asking the user instead — see assumptions.)

**Strict JSON output + retry-once.** The adverse-media call forces the model to return JSON matching a
fixed schema, and that schema is generated *from* the Pydantic model so the two can never drift. The
reply is cleaned of stray markdown, parsed, and validated. If it fails, we ask again **once** with the
error attached; if it fails again, that source returns `status="error"`. Every call uses
`temperature=0` and a token cap. *Trade-off:* one extra request on a bad reply — worth it for
reliability.

**Versioned prompts + an eval harness.** Prompts are text files named by version
(`adverse_media_v1.txt`), and the version is recorded on every assessment. To know whether a prompt
edit helped, run `evals/run_evals.py` before and after and compare. *Trade-off:* the harness uses a
fake LLM for repeatable results, so real model judgement is checked separately and then baked into the
harness when a version is bumped.

**Confidence and completeness are two separate numbers — on purpose.**

- **Confidence** = how many sources worked (returned `ok` vs failed). Answers *"can we trust this?"*
- **Completeness** = how many expected data fields actually came back filled. Answers *"how much did we
  actually find out?"*

These are not the same. "Low risk" and "we couldn't find enough to judge" are different answers, and an
analyst must be able to tell them apart. A healthy company with one director, few filings, and no news
gives **high confidence but low completeness** — see the 06789012 example (`confidence 1.0`,
`completeness 0.67`). Merging them into one number would hide that.

**Completeness uses a simple declared list.** `scoring.py` keeps a small table of which fields each
source should fill, and counts how many are non-empty. *Trade-off:* it's hand-maintained. A fuller
version would derive the expected fields from each source's data model so they can't fall out of sync —
but for a prototype the explicit list is clearer.

**One flag swaps fixtures for the live API.** `CH_USE_FIXTURES` switches only the *fetching* step;
the parsing, signal logic, and scoring are identical either way. *Why:* it must run and be testable
without keys, and the sample files double as the offline test data (shaped to match the real API).
*Trade-off:* samples can drift from the real API over time.

**Server-Sent Events, not WebSockets.** The data only flows one way (server → browser) during an
assessment, so SSE is the simpler fit — plain HTTP, no extra protocol. *Trade-off:* no mid-stream
channel back to the server (not needed here). One quirk: the browser's built-in `EventSource` only
does GET, so the client reads the POST stream manually — which gives up `EventSource`'s automatic
reconnect, but an assessment is a one-shot stream so that doesn't matter.

---

## Product assumptions worth challenging

- **Companies with no known age.** A charity body (sample `00000042`) can have no creation date. The
  "recently incorporated" check correctly stays silent. But the "sparse filings" check still fires,
  since it has no age to reason about. Assumption: a company we can't age and that has filed nothing is
  worth flagging. Suppressing it instead is a one-line change.

- **Sparse-filing threshold.** Fires when a company older than 12 months has fewer than 3 filings in
  the last year. The 12-month grace avoids punishing genuinely new companies. "3 in 12 months" is a
  sensible default, not a calibrated one — it should be tuned against real labelled data.

- **A dissolved company doesn't auto-resign its directors.** When counting a director's active roles,
  a role with no resignation date counts as active **even if that company has since dissolved** — the
  API doesn't filter these out, and dissolution doesn't remove officers. This is intentional: a
  director piling up roles at companies that later collapse is exactly the mule pattern we want to see.

- **Ambiguous names ask the user.** When a name matches several companies, we stop and show a picker
  rather than guessing; picking one re-runs by its number. Assumption: in a fraud tool, a wrong
  auto-pick is worse than one extra click.

---

## Answers to the brief's questions

**Live results, and knowing when they're final.** Each source's card appears the moment that source
finishes, so the fast Companies House data shows in about a second while the slower news/LLM step
trickles in. While running, the UI shows a "2 of 3 sources complete" counter and spinners. When the
`final` event arrives, it switches to a clear green **"Assessment complete"** banner with the score,
band, confidence, and completeness — so you always know if more is coming.

**Slow sources.** Each source has its own time limit, so total time is bounded by the *slowest single
source*, not the sum. A source over its limit becomes a `timeout` card; a broken one becomes an
`error` card — visually different from a source that worked but found nothing ("No risk signals
found", green). The assessment always finishes, and confidence drops to reflect the failures.

**Ambiguous company names** (the "Tunic Pay → Tunic & Co UK Limited" problem). Three states, each
clearly different from a loading spinner:
- **Several matches** → a picker listing each candidate's name, number, status, and address; choosing
  one re-runs by number.
- **No match** → a calm "No company found" message (not a scary error) suggesting a number search.
- **One clear match** → goes straight through.

**Knowing if a prompt change helped.** Versioned prompt files, the version stamped on every result,
and the eval harness. Run it before and after an edit and compare the pass/fail table. It includes the
two hard cases on purpose — a fraud story where the company is the **victim**, and a **different
company with the same name** — both of which must come back as "not adverse". If a prompt change breaks
either, you see it immediately.

**Handling ~1000 queries a minute.** Run many stateless copies of the backend behind a load balancer.
`POST /assess` returns a job id straight away; the slow LLM and source calls go onto a queue, and
results are pushed to the browser as they land. Cache results by
`(company number, source, prompt version)` in Redis with a different expiry per source (e.g. company
profile 24h, directors 6h, news 1h) — most traffic is repeat lookups of the same companies.
Rate-limit and circuit-break each external API on its own, so one slow provider can't stall everything
(falling back to cached or partial results). Batch LLM calls where requests share the same articles.
The current in-memory LLM cache is the single-machine version of this idea; Redis is the multi-machine
version.

---

## What I'd do with more time

- **Real data sources.** Swap the mocked news retrieval for a live news API (GDELT, Dow Jones) and a
  sanctions/PEP list (OpenSanctions, OFAC). The swap point is already isolated to one method per source.
- **Ownership signals.** Use the Companies House "people with significant control" data to spot hidden
  ownership chains — strong for shell-company detection.
- **Redis cache + job queue.** The scaling design above; the in-memory cache is the stand-in.
- **A real labelled test set.** Grow the eval harness from 5 hand-built cases into a tracked set of
  real companies with analyst-checked answers, measuring precision/recall per signal over time.
- **Tracing.** Per-source timing and LLM token usage, to see what's slow under load.
- **Smarter name matching.** Today it's substring/exact (offline) or the API's own ranking (live). A
  fuller version would add fuzzy matching, address/postcode checks, and the planned LLM tie-breaker.

---

## Example input/output

**Input:**

```json
{ "registration_number": "06789012" }
```

**Output** (`final` event, raw blobs trimmed):

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

Here **confidence is 1.0** (all three sources worked) but **completeness is 0.67** (4 of 6 expected
fields filled — there were no news articles, so that source's two fields stayed empty). That's the
point of keeping them separate: we fully trust the result, but we didn't have a complete picture.

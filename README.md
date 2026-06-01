# Company Risk Assessment

> Prototype risk-assessment tool for payment beneficiaries — built for the Tunic Pay take-home exercise.

## Architecture

```
React UI (Vite+TS)
   │  POST /assess (SSE stream)
   ▼
FastAPI Orchestrator
   ├─ resolve entity (Companies House search / LLM disambiguation)
   ├─ fan-out sources via asyncio (parallel, independently degradable)
   │     CompaniesHouseSource   ← real API
   │     DirectorNetworkSource  ← real API
   │     AdverseMediaSource     ← mocked retrieval, real LLM structuring
   ├─ stream each source_result as it lands (SSE)
   └─ deterministic score + final event
```

## Quick start

### Prerequisites
- Python 3.12+, `uv`
- Node 18+, `npm`

### Backend

```bash
cp .env.example .env       # fill in CH_API_KEY, OPENROUTER_API_KEY, LLM_MODEL
cd backend
uv sync                    # installs deps into .venv
uv run uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                # http://localhost:5173
```

## Run instructions (Phase 1 — stubs)

Backend streams two stub source results over SSE. No real API keys are needed for Phase 1.

```bash
# In one terminal:
cd backend && uv run uvicorn app.main:app --reload --port 8000

# In another terminal:
cd frontend && npm run dev

# Or test the stream directly:
curl -N -X POST http://localhost:8000/assess \
  -H "Content-Type: application/json" \
  -d '{"company_name": "Acme Ltd"}'
```

Expected stream output:
```
event: entity_resolved
data: {"type":"entity_resolved","entity":{...}}

event: source_result
data: {"type":"source_result","result":{"source_name":"stub_companies_info",...}}

event: source_result
data: {"type":"source_result","result":{"source_name":"stub_director_network",...}}

event: final
data: {"type":"final","assessment":{...}}
```

## Key decisions & trade-offs

| Decision | Rationale | Trade-off |
|---|---|---|
| Fan-out with `asyncio.wait` (FIRST_COMPLETED) | Streams results progressively; total latency = slowest single source | Slightly more complex than `gather` |
| LLM only for disambiguation + adverse-media structuring | Keeps score deterministic; LLM randomness can't corrupt risk output | Less "AI-powered" feel |
| `response_format` json_schema + validate-then-retry | Schema enforced by model; retry catches transient format failures | Extra round-trip on failure |
| Score is deterministic sum of signal contributions | Auditable, testable, reproducible regardless of LLM state | Can't learn from new patterns without code change |
| `confidence` ≠ `risk` | "Low risk" and "couldn't find enough to tell" are different fraud-analyst outcomes | Slightly more UI real estate |

## Example input/output

**Input:**
```json
{"company_name": "Tunic Pay Ltd"}
```

**Final output (truncated):**
```json
{
  "overall_risk_score": 55.0,
  "risk_band": "medium",
  "confidence": 0.67,
  "completeness": 1.0,
  "sources": [
    {"source_name": "companies_house", "status": "ok", "signals": [...]},
    {"source_name": "director_network", "status": "ok", "signals": [...]},
    {"source_name": "adverse_media", "status": "ok", "signals": [...]}
  ]
}
```

## What I'd do differently with more time

- **Real news/sanctions sources:** NewsAPI, OFAC/HMT sanctions lists, OpenSanctions
- **PSC/beneficial-ownership signals:** Companies House PSC endpoint reveals hidden ownership chains
- **1000 QPS scaling:** Stateless FastAPI workers behind an LB; `POST /assess` returns a job-id immediately, sources run as queue tasks, results pushed to the client via WebSocket or long-poll. Cache `(company_number, source, prompt_version)` in Redis with per-source TTLs (CH profile: 24h, director network: 6h, adverse media: 1h). Rate-limit and circuit-break each upstream with a token-bucket. Batch LLM calls across concurrent requests where entity overlaps.
- **Persistent eval dataset:** Snapshot real CH API responses in fixtures; run before/after every prompt or scoring change to catch regressions.
- **OpenTelemetry tracing:** Span per source fetch; latency histograms per source; LLM token usage metrics.
- **LLM caching:** Hash `(prompt_version, sorted_input)` → cache in Redis; LLMs are not bit-reproducible even at `temperature=0`, so cache is the only way to get true reproducibility.

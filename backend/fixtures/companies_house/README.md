# Companies House Fixtures

These fixture files mirror the **real Companies House Public Data API** response schemas.
They exist so the processing logic can be tested without an API key, and so CI runs offline.

Flip `CH_USE_FIXTURES=false` in `.env` (plus a valid `CH_API_KEY`) to switch to live calls.
**Only the retrieval step changes — the parsing, signal-generation, and scoring logic is
identical on both paths.**

---

## Source endpoints mirrored

| Fixture path | Real API endpoint | Purpose |
|---|---|---|
| `{number}/profile.json` | `GET /company/{number}` | Company status, dates, accounts |
| `{number}/filing_history.json` | `GET /company/{number}/filing-history` | Filing recency / sparsity |
| `{number}/officers.json` | `GET /company/{number}/officers` | Active director list |
| `officers/{id}/appointments.json` | `GET /officers/{id}/appointments` | Per-director appointment count |

---

## Fixture companies

| Company number | Name | Purpose |
|---|---|---|
| `14999001` | NEWCO DIGITAL LTD | Recently incorporated 2026-03-10 → **HIGH RECENTLY_INCORPORATED** |
| `09123456` | DISSOLVED VENTURES LTD | `company_status: dissolved` → **DISSOLVED_OR_LIQUIDATION** |
| `06789012` | DELINQUENT ACCOUNTS LTD | `next_accounts.overdue: true` + `confirmation_statement.overdue: true` → **OVERDUE_ACCOUNTS** |
| `00000042` | HOPEFUL COMMUNITIES CHARITABLE FOUNDATION | `date_of_creation: ""` (CIO edge case) → graceful no-signal |
| `SC987654` | MULE NETWORK CONSULTING LTD | Director holds 34 active appointments → **HIGH DIRECTOR_MULTIPLE_APPOINTMENTS** |

---

## Fixture officers

| Officer ID | Name | Active appointments | Expected signal |
|---|---|---|---|
| `officer_muleking001` | MULEKING, James Robert | 19 (incl. 3 at dissolved companies, no resigned_on) | MEDIUM DIRECTOR_MULTIPLE_APPOINTMENTS |
| `officer_supermule001` | SUPERMULE, Victor Anton | 34 (incl. 3 at dissolved companies, no resigned_on) | HIGH DIRECTOR_MULTIPLE_APPOINTMENTS |
| `officer_normal001` | NORMAL, Sarah Elizabeth | 5 | No signal |
| `officer_dissolved001` | DISSOLVED, Robert Charles | 0 (all resigned) | No signal |

---

## Real-world gotchas encoded in these fixtures

1. **Dissolved companies return HTTP 200.** `09123456` has `company_status: "dissolved"` but
   a full, valid body. The code branches on `company_status`, never on the HTTP status code.

2. **`date_of_creation` can be missing.** `00000042` (a Charitable Incorporated Organisation)
   has `"date_of_creation": ""`. The code handles absence gracefully — returns no signal.

3. **Search results ≠ full profile.** Entity resolution uses `/search/companies` only to
   discover candidates; it always fetches `/company/{number}` for the full profile before
   running any signal checks.

4. **Active-appointment counting is client-side.** The API returns all appointments (active
   and resigned) with no server-side filter. `officer_muleking001` and `officer_supermule001`
   both have appointments at **dissolved** companies where `resigned_on` is absent — these
   count as active because the officer never formally resigned. The code counts
   `len([a for a in items if not a.get("resigned_on")])`, not `total_results`.

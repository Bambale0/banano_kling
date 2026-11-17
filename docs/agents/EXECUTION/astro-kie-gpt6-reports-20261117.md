# Astro GPT-6 via KIE: durable long reports / guarded rollout

## Scope

Backend-only implementation for all seven versioned report templates.
Signed Telegram admins can request a report with explicit data-storage
consent, poll its owner-scoped status, and view completed text. Never debit
wallets, expose this API to ordinary users or enable retired VK features.

### Provider contract

- Existing `config.KIE_AI_API_KEY` and `config.KIE_BASE_URL`; do not copy a key
  into Astro configuration. Official KIE model registry was checked live:
  `gpt-6-astra` listed in `/openai/v1/models` (HTTP 200).
- `POST /codex/v1/responses` with configured model, structured JSON section,
  `store:false`, `stream:false`, low reasoning by default. Inspect KIE JSON
  error codes even on HTTP 200; distinguish terminal 401/402 from rate-limit,
  5xx, transport and incomplete results. No raw prompts, data or secrets logged.
- One production-host KIE smoke with a synthetic instruction returned HTTP
  200, status `completed`, one `output_text` response and usage present. It
  did not generate or charge for seven full user reports.
- The versioned prompt and min-word policies live in
  `bot/astro_report_plans.json` (all seven services), never in Python code.

### Operator env configuration (provide values from secret manager)

| Key | Example / default | Requirement |
|---|---|---|
| `ASTRO_REPORTS_ENABLED` | `0` | Keep disabled until release and sign-off |
| `ASTRO_REPORT_KIE_MODEL` | `gpt-6-astra` | REQUIRED for activation, model from KIE registry |
| `ASTRO_REPORT_FINGERPRINT_SECRET` | *(secret manager)* | REQUIRED, stable random secret, >=12 chars |
| `ASTRO_REPORT_DATA_KEY` | *(secret manager)* | REQUIRED Fernet key; **backup and retain** for encrypted existing reports |
| `ASTRO_REPORT_KIE_TIMEOUT_SECONDS` | `120` | HTTP request timeout |
| `ASTRO_REPORT_KIE_MAX_OUTPUT_TOKENS` | `8192` | Per-section token cap |
| `ASTRO_REPORT_KIE_REASONING` | `low` | Configured reasoning effort |
| `ASTRO_REPORT_MAX_ATTEMPTS` | `4` | Includes worker crash reclaim attempts |
| `ASTRO_REPORT_SECTION_VALIDATION_RETRIES` | `1` | 0–2 bounded rewrites for rejected section content; fact/length checks unchanged |
| `ASTRO_REPORT_RETRY_BASE_SECONDS` | `5` | Exponential retries with max 300s |
| `ASTRO_REPORT_RETRY_MAX_SECONDS` | `300` | Retry ceiling |
| `ASTRO_REPORT_LEASE_SECONDS` | `180` | Lease heartbeat duration |
| `ASTRO_REPORT_CIRCUIT_FAILURES` | `4` | Persistent KIE failure threshold |
| `ASTRO_REPORT_CIRCUIT_COOLDOWN_SECONDS` | `120` | Breaker open interval |
| `ASTRO_REPORT_JOB_TIMEOUT_SECONDS` | `7200` | Entire report timeout |
| `ASTRO_REPORT_WORKERS` | `1` | Max 4; increase only with provider quota |
| `ASTRO_REPORT_POLL_SECONDS` | `3` | Idle worker poll |
| `ASTRO_REPORT_CLEANUP_INTERVAL_SECONDS` | `3600` | Encrypted job/checkpoint expiry purge |
| `ASTRO_REPORT_RETENTION_DAYS` | `90` | 1–365-day data TTL |

Enable ONLY after protected CI, exact SHA deploy and admin/nonadmin smoke.
The routes exist when disabled but respond 503; they do not invoke KIE.

### Persistence and safety

- `astro_report_jobs` and `astro_report_sections`: SQL checkpoint commits,
  owner+HMAC fingerprint idempotency, encrypted source facts and ciphertext
  outputs via the same stable Fernet key. Structured job errors contain safe
  codes only; no user birth data or report sections in structured logs.
- Worker lease heartbeat, atomic claim, fenced commit, stale-owner refusal,
  bounded exponential retries, max-attempt failure, SQL-persisted breaker,
  restart recovery and owner-scoped status. Expired job dedupe records cleared.
- KIE does not expose a documented guaranteed billing-idempotency contract for
  our in-flight Responses call. A crash AFTER a provider charged request but
  BEFORE the section checkpoint was committed may cause an extra paid call.
  Checkpoints avoid regeneration for all already committed sections; **no
  claim of exactly-once provider charging** is made.
- Synchronous facts calculation occurs on the server; no user-provided
  longitude, timezone, aspect list or model prompt is trusted. An explicit
  numeric/date proof gate rejects unsupported degrees/ISO dates before saving
  a completed section, but cannot prove all qualitative interpretation is
  scientifically correct; astrology is symbolic.
- The solar calendar's 12 months start at the exact local solar-return time;
  it must not substitute January–December or invent precise transit dates.

### Verified tests and remaining release gates

- Real one-request KIE GPT-6 output protocol success, with no user data.
- Complete seven-service long-report simulation (5–12k+ words for each)
  through all template sections with a deterministic fake LLM; replay does
  not call provider again.
- HTTP → SQL queue → worker → completed report → owner-only status → restart
  test for all seven, no third-party charges.
- Retried interrupted natal report reuses committed section. Concurrency,
  lease expiry, bounded crash attempts, circuit persistence, consent and
  encryption verified. See tests in this PR and CI record.
- **NOT verified:** seven costly full live GPT-6 reports; real mobile Telegram
  report UI (separate change due stacked compatibility UI #583); exact-SHA
  production deployment; PostgreSQL concurrency in a live cluster; billing
  reconciliation after lost KIE response. No user balances charged.

Followed `Bambale0/.agents` TDD/verification skills and project `AGENTS.md`.

## Final gate checklist

1. Protected CI and code review, then exact merge SHA on Docker and static
   Mini App, without relying on retired VK DNS; preserve `data/price.json`.
2. Operator supplies stable Fernet/HMAC secrets and `gpt-6-astra` model to
   `.env.astro` through approved secrets, without leaking either in logs.
3. Set `ASTRO_REPORTS_ENABLED=1` only after signed admin + non-admin 401/403
   and one low-cost live section test (no user money charged).
4. Repeat seven full provider-backed documents only under an approved token
   budget; present test results separately from synthetic long-form tests.
5. Confirm real Telegram report controls in a subsequent compatible frontend
   PR (the current production frontend revision is older than backend).

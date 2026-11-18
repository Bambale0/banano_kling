# Astro queue truthfulness and fact-guard recovery (18 Nov 2026)

- Baseline: `4ae787db41072857f51c28968985d0183075c38f`, task branch `fix/astro-report-status-fact-20261118` → `tanyapi`.
- Production evidence (12:01–12:08 UTC): one new natal job got two provider responses per attempt, each rejected for `section_03 / unsupported_claim`; another admin received the same ID of an older `failed` job for both start requests. PostgreSQL confirms both rows `failed`, retry count 2; no user balance debit in Astro flow.
- Root causes: first, `/reports/start` always labels any deduplicated row `202 queued` even when `failed`; second, explicit sign-relative degrees (`longitude mod 30`) are rejected though derived from verified facts. Local section errors also increased the KIE provider circuit breaker.
- Scope: truthful HTTP status and Mini App UI for existing failed/completed jobs; allow derived zodiac degree within current numeric proof gate; actionable private validation retry feedback; separate content errors from provider circuit. No provider/pricing/auth changes.
- Invariants: no automatic paid replay of old reports; owner-scoped status and explicit consent retry remain; invalid degrees and unsupported ISO dates still rejected; no raw birth details/LLM text in logs.
- Tests: add failing API lifecycle, numerical sign-degree and worker circuit regression before implementation. Re-run focused pytest, frontend E2E and required CI; verify exact deployed SHA if merged.
- Rollout: squash PR into `tanyapi` after CI, auto-deploy, health + log smoke. Old failed jobs can be resumed only via owner-authorized manual retry.

## Verification snapshot (before CI)

- New regressions RED on baseline: sign-relative degree false rejection, stale failed `/start` returned HTTP 202, local validation wrongly increased provider circuit.
- GREEN after change: 51/51 in focused API/worker/queue/fact-guard/pipeline; TypeScript `tsc --noEmit` passed, targeted ESLint 0 errors, `git diff --check` passed.
- Broader local Astro run: 273 passed, 10 skipped, 2 fail on missing `numpy` in host QA venv; separate PDF tests not collected because `reportlab` absent. These are missing local QA dependencies, not a green full-suite claim. CI is required to validate these layers.
- No production DB mutation, user-paid retry or KIE charge performed during this fix. Old failed reports remain failed until explicitly retried by the owner with consent.

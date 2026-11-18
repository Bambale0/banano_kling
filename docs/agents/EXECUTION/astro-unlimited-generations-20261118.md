# Astro: unlimited new reports per deliberate click — 2026-11-18

## Baseline and reproduction

- Production baseline and `tanyapi` base: `1e4aa807c67bccd5f9e23dd012d05d515ac935c2`.
- A new Astro `POST /mini-app/api/astro/reports/start` with identical astronomical facts returned an older `failed` job because `UNIQUE(owner_id, fingerprint)` and the facts-only report fingerprint were reused.
- Reproduction: `pytest -q tests/test_astro_report_jobs.py -k test_enqueue_is_idempotent_per_request_not_per_birth_facts` failed against the old backend due to missing per-click request identity.
- Existing historical reports and shared checkpoints must remain readable through their legacy fingerprints.

## Contract and design

- Every deliberate click creates a fresh report, even when service, birth inputs and plan match a prior failed, active or completed report. No quota limits new report creation.
- Each click sends a new random 128-bit hexadecimal `request_id`; the server maps it through an owner-scoped HMAC to a stable job id. Replayed HTTP requests from that click return that **same** job. Invalid keys and reuse of a key with changed facts fail validation.
- Older Mini App clients that omit `request_id` still create a new job on every explicit request; the frontend in this release emits the key for modern WebViews.
- Report fingerprints and encrypted section checkpoints are scoped by each job ID, not just the birth facts. A fresh report never reuses the model-generated content of a previous report.
- Workers can resume historical jobs by verifying either the per-generation fingerprint or the original facts-only fingerprint; no schema migration or balance change.
- Keep existing admin-only gate, consent checks, per-job bounded provider retries, and delivery queue semantics unchanged. New creations are unlimited even when a previous *single-job retry* budget is exhausted.

## Verification evidence

- Targeted backend tests: **52 passed**, Ruff check clean on changed Python files (QA run at `b32c394c64a0c5d0a5e1441f6aa84a1aaa34b300`).
- Mini App Astro panel Jest tests: **19 passed** (QA at `ac24d753d2ab3267933c33948583c38d16e1bd13`).
- Tests cover new report after failure, duplicate request idempotency, changed-input replay rejection, owner isolation, legacy job resume, two complete identical-facts reports, and client-generated request ids.

## Production data hygiene

- Explicitly authorized cleanup of five terminal administrative test reports: five jobs, 20 checkpointed sections, five delivery rows, and three manual retry records removed transactionally from production PostgreSQL.
- Verified all five selected jobs absent after commit and the count of other owners' jobs unchanged.
- Secured owner-scoped pre-cleanup backup retained on the host, mode `0600`. No customer-wide cleanup, balance update, or Telegram message deletion.

## Release controls / residual risks

- PR to protected `tanyapi` only; native auto-merge and four required gates, then production exact-SHA Docker/Mini App verification.
- The underlying risk of long KIE GPT-6 request timeout remains a separate incident: this change removes only stale-result reuse and ensures repeatable fresh attempts without cross-run checkpoints.
- Do not claim paid end-to-end PDF delivery based only on the deterministic provider mock tests.

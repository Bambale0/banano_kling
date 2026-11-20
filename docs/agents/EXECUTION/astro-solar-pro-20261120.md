# 2026-11-20 — NEUROMIX ASTROLOGY PRO: соляр, новые инструкции

## Baseline
- Source branch: `tanyapi`, prior solar template `2.0.0-full-original-20261115` in `bot/astro_report_plans.json`.
- Prior plan: 21 sections, 12,000-word floor and 12 forced civil-month narrative sections.
- User supplied new full module-specific source, with 17 sections, no artificial padding or unsupported transit dates.

## Scope and decisions
- Replace only `services.solar` with `3.0.0-astrology-pro-solar-20261120`.
- Save exact instruction in `docs/astro/solar-system-pro-20261120.md` and as `service_instructions`.
- Keep global `system_prompt` safety/fact gate and other six services identical.
- Keep 17 thematic sections; select modest 45-word technical per-section floor and 765 total to avoid 12k-token padding behavior. This is not a product word-count promise.
- Remove `dynamic_period` to prevent ungrounded monthly transit narratives.
- Archive original solar v2 config and enable signed HMAC resolution for existing queued/retry jobs.
- No payments, auth, price, model, database migration, user data, runtime secrets or frontend changes.

## Observability, tests, release
- Existing worker logs archived plan selection with job_id, service and version without personal facts.
- New regression tests verify exact source/config identity, 17 sections, source rules, no invented calendar, old/new signed fingerprints and tamper rejection.
- Update existing seven-service specification to reflect the new solar-only plan.
- CI before merge: Python/deploy validation, safe regression, Mini App E2E and Docker build.
- Merge only after required gates; then verify exact SHA in production, health, worker/report smoke and telemetry.
- Rollback: revert config to archived solar v2 (keep archive and HMAC support to allow historical checkpoints).

## Limitations
- This changes the interpretation template, not the astronomy calculator. Existing fact payload must still contain actual solar return, natal chart and location. A new ephemeris transit-event solver is not implemented here; section 15 must disclose absence of dated transits rather than fabricate them.
- No live paid generation has been executed solely by changing this prompt.

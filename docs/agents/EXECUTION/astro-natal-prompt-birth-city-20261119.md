# Astro natal: replace instruction and carry verified birth city (2026-11-19)

## Scope / baseline

- Baseline: `4a00af33b54b657a4c71fb086d8c08fd67f79780` on protected `tanyapi`.
- User supplied a Russian NEUROMIX natal instruction (~298 chat-export lines) and reported: `Отдельного текстового поля с названием места рождения в исходных фактах нет`.
- Existing `bot/astro_report_plans.json` was global policy + per-service instructions. Natal used 18 sections and a hard 10,000-word floor, contradicting the user's new eight-block instruction emphasizing shorter, nonrepetitive text.
- City root cause: the frontend submits trusted GeoNames `place_id`, `get_place` resolves canonical name/country/coordinates/timezone, but `_birth_profile` passes only coordinates/timezone to the ephemeris; the report handler did not restore the city and `_fact_catalog` filtered it out. The LLM therefore saw no verified human-readable birthplace.

## Changes

1. Versioned natal prompt `3.0.0-human-natal-20261119` in `bot/astro_report_plans.json`. Exactly the supplied substantive instructions after removing chat-export speaker/time markers, line-continuation backslashes and escaped Markdown dots. Source text retained in `docs/astro/natal-system-20261119.md` with a SHA-256 regression test. All six other service instructions, versions and section plans are unchanged. The global factual trust gate remains the final priority.
2. Natal now has eight distinct content blocks, matching the uploaded instructions; per-section minimum and total are editorial safety floors (540 words), not a target/quota, and no section should add filler for length.
3. Archived original natal version `2.0.0-full-original-20261115` in `bot/astro_report_plans_natal_v2_legacy.json`. Worker matches the signed fingerprint against current + original natal plans (with/without per-click generation ID) and resumes historical jobs with original encrypted checkpoints; mismatches are rejected. No database migration or deletion. Production preflight observed 3 failed natal records and no active natal jobs.
4. The natal report calculation now attaches a trusted `astronomical_facts.birth_place` object from **server-side GeoNames lookup**, fields `name`, `country_code`, `place_id`, `timezone`, `source: GeoNames`. Raw browser city text and names typed in arbitrary payload fields are never forwarded. Strict allowlist validates exact fields/types/limited text before encrypted persistence and KIE transmission. First natal block instruction explicitly cites the verified birthplace.
5. No payment/credit, service authorization, model/provider, timestamps, other six Astro services, frontend or DB schema altered.

## Test-first evidence / verification

- Initial prompt test import failed (missing historic-plan resolver); added and 7 targeted tests passed.
- City regression: initially **7 failures** (missing `birth_place` on server facts and provider payload, malformed facts not rejected). After fix, 14 targeted city+prompt tests passed, Ruff clean.
- Initial broad suite found 4 historic assertions demanding 18 sections or >=10k natal words. Updated only those stale natal expectations to new user-supplied plan; kept six other service floors unchanged. Result: **343 passed, 9 skipped** across `tests/test_astro_*.py`, Ruff clean.
- Follow-up: ensure full Astro regression and CI after final first-section birthplace guidance, test actual offline GeoNames record, and production exact deployed SHA before claiming released.

## Rollout / rollback

- Normal task PR to protected `tanyapi` with native squash auto-merge; never bypass four CI gates. Production Docker and Mini App may share same revision, verify each.
- Smoke: read-only GeoNames result, actual natal input-to-facts provider request (mock provider so no paid tokens), job status and historical recovery, absence of secret/PII logs and HTTP health.
- Rollback: revert PR to previous natal instructions. The old archived template is read-only and exists solely for historical signed jobs; do not delete jobs or touch balances.
- Watch: `astro_report_invalid_content`, `astro_report_archived_plan_selected`, `astro_provider_call_started` and Telegram PDF delivery statuses. Real KIE GPT-6 textual quality is subject to provider variability.

## Risks

- Prompt replacement reduces output length and changes natal report structure intentionally; frontend PDF and history should continue to render arbitrary ordered sections.
- Birthplace is personal context: only the user-consented, server-verified selected place is encrypted at rest and sent to the configured provider. Do not log raw birthplace or expose through unauthenticated status APIs.
- Historic jobs were created under the v2 template; archive must remain available as long as manual retries of old jobs are supported.

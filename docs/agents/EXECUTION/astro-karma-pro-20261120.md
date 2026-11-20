# 2026-11-20 — NEUROMIX ASTROLOGY PRO: инструкция «Карма и кармические уроки»

## Базовое состояние
- Production source: branch `tanyapi`, existing karma `2.0.0-full-original-20261115`.
- Existing interpretation plan: 27 sections, 8,000-word minimum, and extensive required topics regardless of calculated data.
- The user supplied a new 17-section karma instruction including explicit limitations for nodes, retrogrades, houses, UTC, engine source, uncertainty, and a practical 5–10 action plan.

## Цель
- Preserve the complete owner source verbatim in `docs/astro/karma-system-pro-20261120.md`.
- Only `services.karma` changes to `3.0.0-astrology-pro-karma-20261120`; other six services and global facts/anti-hallucination policy unchanged.
- Deliver exactly 17 thematic sections, with 45-word minimum validation floor each and 765 technical total. No arbitrary 8k forced length; user quality requirement controls real prose length.
- Never equate retrograde positions with punishment or assume past-life identities. Unknown birth time means no unverified house/ASC/MC claims.
- All calculated input is still provided by existing ephemeris fact engine and curated `_fact_catalog`; this PR does not add unsupported ephemeris objects or exact aspects.
- Keep prior v2 karma immutable archive for signed in-flight jobs, accepting legacy and per-generation HMAC while rejecting altered fingerprints.

## Files and blast radius
- `bot/astro_report_plans.json`: exclusively karma instructions, version, structure.
- `docs/astro/karma-system-pro-20261120.md`: original source.
- `bot/astro_report_plans_karma_v2_legacy.json`: exact original karma plan and global system prompt for fingerprint consistency.
- `bot/services/astro_report_worker.py`: select the historical signed karma template.
- `tests/test_astro_karma_prompt.py`: source integrity, per-section structure, six-service isolation, v2 legacy jobs, signed new jobs and tamper refusal.
- `tests/test_astro_report_full_spec.py`, `tests/test_astro_report_pipeline.py`: v3 structural and minimum-word contract.

## Verification and rollout
1. Use owner-provided source and existing project service schema.
2. TDD: introduce regression tests before implementation.
3. Validate JSON config, 17 sections and exact source inclusion, compare other services against baseline.
4. PR to `tanyapi` and review required GitHub checks (Python/deploy validation, safe regression, E2E and Docker build).
5. Auto-merge when protected branch CI permits, then exact production SHA/health/logs and one real karma report smoke for Admin.
6. Rollback: restore v2 karma plan from archive while preserving the archive and signed-plan recognition.

## Risks / limitations
- No production smoke until CI/deploy completed; no claims that paid AI interpretation was executed.
- Accurate lunar nodes, retrogrades, houses and aspects depend on existing AstroFacts output. The prompt must not create missing measurements.
- The separate solar PR #657 may modify the same files. Before merge verify both changes are preserved and resolve conflicts without overwriting solar work.

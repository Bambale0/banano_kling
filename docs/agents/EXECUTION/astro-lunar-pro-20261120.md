# 2026-11-20 — NEUROMIX ASTROLOGY PRO: Лунный календарь

## Source and baseline
- Source branch `tanyapi`; old lunar v2 `2.0.0-full-original-20261115` used 14 static chapters, a minimum of 5,000 words, plus one paid LLM section for every calendar day.
- The existing MIT Astronomy Engine computes lunar quarter events, local noon daily facts, precise lunar sign ingresses, IANA local times and a documented 24-hour synodic-day convention.
- The interpretation `_fact_catalog` excluded `ingresses`, the lunar-day method and canonical city, so a prompt-only migration would still miss important reliable data.

## Implementation
1. Preserve the complete user-supplied system instruction unchanged in `docs/astro/lunar-system-pro-20261120.md`.
2. Use ten semantic chapters, with the tenth only if a computed natal chart is provided. Generic calendar is nine chapters and requires no birth data.
3. One compact Markdown table covers the full month, with one ISO-dated row per day; validate the calculated days are complete, chronological, distinct and month-appropriate.
4. Validate provider output against the exact calculated date sequence, with bounded regeneration when a row is omitted/duplicated; never mark an incomplete calendar completed.
5. Add only verified GeoNames city metadata from the backend resolver and previously computed lunar ingresses/convention to the v3 LLM facts and signed fingerprint. v2 uses the historical catalog, preserving all old signatures.
6. Archive the complete old lunar v2 plan and extend worker's signed-plan resolver for old encrypted jobs.
7. Other six services, global anti-hallucination instructions, prices, billing, auth, DB tables, frontend and lunar astronomy calculations remain unchanged.

## Verification and safety
- Tests cover exact instruction/config matching, all sections, 2024 leap-month and 2026 November, missing/duplicate/reordered/out-of-period days, no forced daily LLM calls, optional natal chapter, city provenance, ingress data/UTC IANA convention, HMAC v2 jobs and v3 tampering.
- Source work follows relevant repository `AGENTS.md`, `Bambale0/.agents` TDD skill, regression-first flow and archived-plan precedent.
- Required CI: Python/deploy syntax and Ruff, safe regression, Mini App E2E, production image; then auto-merge into protected `tanyapi`; exact deployed SHA, API health, smoke and log verification.
- Maintain code/PR compatibility with concurrent solar #657 and karma #659; their same-file changes must not be overwritten.

## Risk and rollback
- The current lunar report backend produces general calendar facts. The tenth section is conditional on an already calculated natal chart; no invented natal chart or cross-aspects are generated.
- Unsupported `void_of_course`, planetary aspects and eclipses remain absent; instruct model to disclose rather than fill in.
- Rollback: restore archived lunar v2 plan and preserve v2 resolver/HMAC checkpoints. No destructive operations.

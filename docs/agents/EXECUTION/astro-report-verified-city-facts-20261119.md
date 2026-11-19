# Astro — verified birthplace names in LLM facts (2026-11-19)

## Reproduction and root cause
- User-facing LLM output said: "Отдельного текстового поля с названием места рождения в исходных фактах нет".
- Astro Mini App submits a GeoNames `place_id`, not the typed city. `bot/services/astro_places.py:get_place()` correctly resolves a trusted `name`, `country_code`, coordinates and IANA timezone.
- `bot/astro_report_api.py:calculate_verified_facts()` forwarded only latitude, longitude and timezone to ephemeris functions. Those functions return genuine astronomical data without a textual city name.
- `bot/services/astro_report_pipeline.py:_fact_catalog()` selected a strict list of facts and did not include a birthplace name. As a result GPT-6 did not see the user-selected town in its JSON facts, despite correct chart mathematics.
- TDD: 10 tests reproduced missing GeoNames labels in all seven services, missing interpreter input, and missing validation of forged names; initially all 10 red.

## Fix
- Generate canonical `<GeoNames.name>, <ISO country code>` labels only on the backend from the resolved `place_id`. Reject missing/invalid country codes and control characters. Ignore any forged form field `birth_place_name`.
- Include `birth_place_name` for natal, karma, year, month, solar. Include both `first_birth_place_name` and `second_birth_place_name` for synastry; `solar_return_place_name` for the relocated solar return; `calendar_place_name` for lunar calendar.
- Pass these five optional labels through the explicitly-curated `_fact_catalog()` into the GPT-6 section JSON. Validate format and control characters again at the LLM boundary.
- Preserve exact original ephemeris calculations, IANA birth timezone and owner-only encrypted task persistence. Historical jobs without city names remain valid; do not guess their city from approximate coordinates. Newly generated reports include the verified names.
- Avoid logging raw city labels, dates, birth profiles or prompts.

## CI / independently verified tests
- 61 focused + seven-service E2E / full report tests passed on this code.
- Extended Astro + tariffs suite: 374 passed, 9 skipped, two pre-existing aiohttp warnings.
- `ruff` and changed-line Ruff gate passed for city API, curated facts, tests.
- Unit/regression for Wan audio sandbox: pinned verified FFmpeg/FFprobe wheel hashes, diagnostic synthetic OGG, and added `-filter_threads 1` to keep cgroup threads bounded without weakening existing RLIMIT_AS 512 MiB, CPU 12s, duration and file-size limits.
- CI GH issue reproduced: prior apt FFmpeg install exceeded 95s and 300s due to Ubuntu/Azure mirror delays; pinned FFmpeg 9 installed but GitHub runner failed with `pthread_create() failed: Resource temporarily unavailable` for audio filter threads. New bounded filter-graph option addresses this cause; after-run logs must verify it under GitHub.
- Not a license to bypass required GitHub CI; protected branch auto-merge, backend/frontend exact-SHA deploy, and smoke required.

## Risks
- A previously generated report is immutable: city metadata will only be present in reports created after deploying this change. Automatic backfill or re-billing of historical jobs is out of scope.
- GeoNames display names may be in the location dataset's local language and are unambiguous with the two-letter country code.
- KIE prose quality is non-deterministic; test that **the exact request JSON** includes the trusted label. An existing report need not be regenerated to validate the patch.

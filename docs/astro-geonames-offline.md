# Astro-02 — GeoNames offline places and historical IANA timezone resolver

Source: GeoNames cities1000.zip downloaded from
https://download.geonames.org/export/dump/cities1000.zip .
**GeoNames CC BY 4.0 attribution is required** in eventual app/API and documentation:
© GeoNames, https://www.geonames.org/, licensed under CC BY 4.0.
The import file and output SQLite are managed deployment assets, **not committed to Git**.

## Operational contract

1. Download/version/pin source externally. 2026-11-16 snapshot:
   source ZIP SHA-256 46a35f52226f34dd56b64d57b4e9bb380a8ad06605354f8095ea9cdc561aba2c.
2. Build offline (no network) as a NEW immutable DB path:
   python3 scripts/astro_build_places.py --source-zip /data/astro/cities1000.zip --output /data/astro/places-20261116.sqlite3
3. Verify successful import and SHA-256; staging receipt for 2026-11-16:
   171939 places, output DB SHA-256 98f6fd9046819ff380a5e0ef24bff4a851a58cbc593290e66c158c11a7fa8350.
4. Configure runtime ASTRO_PLACES_DB_PATH with the full verified, read-only DB path; no implicit downloads or SQLite DB creation, no source ZIP in image. Atomically switch path after smoke. This foundation PR does not modify prod env/config.
5. search_places(query) returns explicit name, country, population, place_id, IANA timezone, coordinates. Geonameid is selected by user, never inferred by LLM. get_place(place_id) checks immutable trusted catalog.
6. resolve_birth_place(...) determines the timezone on the selected birth date/time with Python zoneinfo; DST overlap requires explicit fold=0/1, nonexistent local times fail closed. Unknown time uses approximation and must not claim houses.
7. Owners may have birthplaces not covered by cities1000 (populations below 1000); future coverage should support a denser operator-managed dataset and explicit validated coordinates with independent timezone verification. Do not silently fill unknown locations.

## Scope and release

This is an offline search/calculation library only, not a new public Astro endpoint or persistent birth profile. It changes no VK, Telegram FSM, provider pricing/payment, S3, frontend or production service. Before exposure add signed Telegram admin-only API with rate limits, consent/PII safeguards, explicit place picker and end-to-end tests.

Security: parameterized SQL plus carefully quoted FTS tokens, immutable read-only SQLite, input size bounds, no network from user API. Do not log exact birth records. Where historical IANA data is incomplete, surface that limitation.


### Country-aware search
Frozen CLDR country names in Russian and English / ISO codes accompany GeoNames.
Both Russia, Saint Petersburg and Россия, Санкт-Петербург match city alias and
country, never guessing a place from a similar-named city elsewhere.

## Admin-only HTTP search (dependent follow-up)

A subsequent isolated PR exposes POST /mini-app/api/astro/places with signed
Telegram initData and server-side admin validation before and after the search.
The response contains at most 10 trusted geonameid matches and the visible
attribution to GeoNames. The raw city query is never logged, persisted or used
as a billing field. Access without configuration returns 503; unauthorized 401,
non-admin/VK 403. No birth-date data or profile is accepted at this endpoint.
Frontend selection and the real 7-service calculations remain separate work.

# Astro calculations — alternate MIT ephemeris foundation

Parent #544, epic #559. Current production lunar/natal calculation via Astronomy Engine is unchanged. This is an **isolated dormant module**; do not expose new routes until accurate API, geographic identity, consent, event search and E2E are complete.

- Library: pinned openephem 0.5.0 (MIT, no Swiss-AGPL deployment dependency).
- Source of planetary facts: pre-provisioned NASA/JPL DE440 binary `de440.bsp` (~120 MB). Do not download at request time or ship files inside Git. Provision as read-only managed asset in deployment and set `ASTRO_DE440_PATH` and `ASTRO_DE440_SHA256` via secure environment configuration. Fail closed when missing or hash mismatched.
- Verified isolated staging asset size 119799808 B, SHA-256 `a4ce9bf9b3282becc9f4b2ac3cebe03a2ae7599981aabd7265fd8482fff7c4b5`, fetched over HTTPS directly from https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de440.bsp on 2026-11-16. This is a provenance record, not a live deployment setting.
- Engine adapter `bot/services/astro_chart_core.py` returns structured deterministic facts for natal, synastry, karma indicators, 12 monthly or 28–31 daily transit snapshots, and an exact solar return instant at independently supplied coordinates.
- **Caveat:** noon transit samples are NOT exact transit-aspect event crossing times. High-latitude Placidus may be undefined. No interpretation, billing, geocoding or public API. Do not silently substitute another house system.
- Local isolated offline unit tests using production dependencies and vendored MIT engine: 27 passed. One actual natal calculation with SHA-verified DE440 yielded 12 objects. Independent reference-chart oracle and full integration remain required.
- No VK, payments, frontend, profile persistence, or existing Telegram API changes. Configurable only when feature is explicitly enabled in a later guarded PR.

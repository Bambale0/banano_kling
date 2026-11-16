# ASTRO-09: lunar zodiac ingresses — execution ledger (2026-11-16)

- Parent: #544; epic: #567; production branch: `tanyapi`.
- Task branch: `feature/astro-lunar-ingresses-20261116` (created from then-current `tanyapi`).
- User-visible slice: display the actual UTC/local instant when the Moon crosses each tropical 30° zodiac boundary for the selected lunar-calendar month. No fake daily-sign extrapolation.
- Existing functionality: admin-only lunar API `POST /mini-app/api/astro/lunar` from #546 with real quarters, 12:00 positions, phase/illumination/synodic days; React UI consumes and displays these facts.
- Confirmed gap: production's `build_lunar_calendar('2024-03','UTC')` lacks `ingresses` (read-only assertion failed as expected on 2026-11-16). User requirement includes accurate sign-change times.

## Design / non-hardcode
- Existing MIT Astronomy Engine 2.1.19 retained; no Swiss license change and no new provider or dynamic model parameters.
- At most 3 UTC hours between observations, bounded bisection of actual ephemeris longitude to a UTC-second crossing; correctly handles 359°→0°. Fail closed on nonfinite/discontinuous results.
- API `astro.lunar.v1`: new additive `ingresses` array, each with `from_sign`, `to_sign`, `longitude_deg`, `at_utc`, `at_local`, `local_date`. Existing `events` for quarter phases and `days` unchanged.
- Parse and localize with the selected IANA timezone; represent true event instant, do not interpolate linearly from noon positions.
- No DB migration, user birth profile, payment, feature flag, pricing, OpenAI integration, provider call, Telegram FSM or VK changes. Current admin-only API gate unchanged.
- Data minimization: ingress times are not personal data; no additional request logging.

## TDD and verification
1. Reproduce: read-only production assert `'ingresses' in build_lunar_calendar('2024-03','UTC')` returned AssertionError.
2. Add regression tests: 2024-03 Europe/Berlin (UTC/local conversion, ordered crossings, sign on either side of each event) and Pisces→Aries 360° wrap.
3. Add deterministic engine search. Preserve lunar daily and phase contracts.
4. Add Mini App integration regression fixture and visible list of exact ingress times, resilient to older API responses without this additive field.
5. Run mandatory protected GitHub backend/frontend/Playwright CI on exact PR SHA; review, native squash auto-merge only if green; then exact-SHA production smoke including admin/non-admin and telemetry.

## Open risks / follow-ups
- No independently certified subsecond precision: exposed times rounded to seconds, matching Astronomy Engine time input precision.
- No city geocoding yet (#560). Selected IANA timezone is still supplied explicitly.
- Planetary aspects, void-of-course, eclipse calculations and traditional advice are outside this slice and remain open under #567.
- Full 7-service release, long sections and billing remain open under #544 and other ASTRO epics.
- Production correctness/deployment cannot be claimed before exact-SHA CI and runtime check.

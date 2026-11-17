# Full JPL synastry: verified two-person compatibility API

## Dependency and scope

Stacked on #581, which depends on #579; do not merge to `tanyapi`
until both are deployed and independently verified. This adds only the
admin-only `POST /mini-app/api/astro/compatibility/full`. The existing
`/compatibility` route remains unchanged for old Telegram Mini App builds.

The new endpoint verifies signed Telegram initData, rechecks current admin
status after computations, rejects VK/unsigned requests, requires two
canonical numeric GeoNames IDs and resolves both locations server-side.
Client coordinates, IANA names and `is_admin` are never trusted. Historical
IANA offsets, DST and JPL DE440 are delegated to the existing strict
engine. No user birth data stored/logged, no third-party provider, balance,
price or wallet action.

It returns two independent natal charts with real inter-chart aspects,
Placidus house rulers/placements and directional house overlays. Unknown
birth time yields no invented houses for that person's chart. A signed
admin-only Mini App UI adaptation is the subsequent dependency.

## TDD and evidence

- Red: import of the endpoint module failed before implementation.
- Green: 15 isolated handler regression tests: forged fields ignored,
  unsigned 401, VK/nonadmin 403, role revocation 403, invalid IDs 400,
  missing GeoNames/JPL 503 without secrets and both routes registered.
- The combined affected Astro/backend suite passed 176 tests, Ruff clean.
- Real read-only `--network none` operator GeoNames+JPL HTTP smoke:
  `scripts/astro_full_synastry_smoke.py` — anonymous 401, synthetic
  authorized Telegram test actor 200, both overlay directions 12 bodies,
  schema `astro.synastry-facts.v1`, no-store.

## Not ready yet

Protected CI gates and exact-SHA prod deploy still required. User-facing
Mini App currently calls the backward-compatible legacy endpoint; migrate
frontend in a dedicated tested PR only after this API is available.
Full 5k–18k word reports, consent/history/delivery and advanced composite
are independent issue #544 acceptance items. No public Astro enablement.

Skills applied from Bambale0/.agents: systematic-debugging,
test-driven-development, verification-before-completion, frontend-ux-audit.

## Long-form report handoff regression

The structured `astro.report.v1` composer must receive the actual
`house_overlays` in its curated astronomical facts, not only inter-chart
aspects and natal bodies. The HMAC cache fingerprint now includes those
calculated directional house mappings: a different placement cannot reuse
an existing checkpoint report. Untrusted client note fields remain excluded.
The new regression failed with missing `house_overlays` before the fix.
After the addition, 32 report tests and 208 combined affected Astro tests
passed; the real two-city JPL-DE440 signed API smoke stayed green.
This is *not* an active LLM report delivery endpoint yet.

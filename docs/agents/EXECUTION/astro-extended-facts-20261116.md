# Astro follow-on: karma, monthly/annual transits, relocated solar

Stacked on #578 (full admin natal with verified GeoNames places).

Four new admin-only POST endpoints under /mini-app/api/astro/: karma, year, month, solar.
Only signed Telegram admins may call. Place IDs are server-resolved through the
operator-provisioned GeoNames database. Latitude, longitude, timezone and
platform assertions in request JSON are ignored; current admin is checked
again before response. Solar explicitly requires a second return-place ID.

Astronomy input: JPL DE440 via MIT openephem, with checksum-verified immutable
asset configured separately. Calendar-period validation accepts YYYY for
annual transits and solar return, YYYY-MM for monthly daily snapshots.
Unknown or conflicting civil birth time fails with a clear input error where
mathematically necessary. No tokens, debits, DB writes or AI interpretation.

The new Mini App panels show precise node positions and karmic indicators,
12 annual local-noon transit snapshots, per-day local-noon monthly snapshots,
and the relocated solar return timestamp plus Placidus houses, ASC and MC.
They explicitly distinguish timestamp samples from exact aspect-crossing
calculations and symbolic interpretations from scientific predictions.

Tests: 26 new mocked API/auth/period/revocation/regression tests and 118
existing Astro backend tests passed in a network-isolated container; 18 React
unit tests passed including karma city verification and separate solar place.
Ruff, TypeScript and ESLint clean. Real JPL+GeoNames karma and annual samples
also passed (4 indicators and 12 snapshots). Real month/solar and production
WebView smoke are not yet confirmed and must be checked before release.

Release dependency: merge #578 and verify exact SHA before retargeting this PR
to tanyapi. Do not remove VK rollback, do not enable payments or public Astro.

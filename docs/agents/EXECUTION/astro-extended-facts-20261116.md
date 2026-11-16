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

## Real operator-host smoke on 2026-11-16

Tested against the REAL host's GeoNames database and SHA-256 checked JPL DE440,
not mock ephemeris values or user birth data, in a network-isolated, read-only
Docker container with no wallet/backend DB access. Reproducible command:

    docker run --rm --network none --read-only --tmpfs /tmp -w /app \
      --env-file .env.astro -e PYTHONPATH=/app:/vendor \
      -e ASTRO_DE440_PATH=/assets/de440.bsp \
      -e ASTRO_PLACES_DB_PATH=/assets/geonames-20261116.sqlite3 \
      -v <feature-checkout>:/app:ro -v <vendor-deps>:/vendor:ro \
      -v <operator-assets>:/assets:ro --entrypoint python \
      banano-kling-bot:local scripts/astro_extended_smoke.py

Observed PASS: 4 factual karma indicators, 12 annual samples, all 29 days
of 2028-02, exact solar return 2028-02-29T05:27:36.894667+00:00 for
fixture born 2000-02-29 13:45 Europe/Moscow, solar location Berlin;
12 solar Placidus cusps, 12 objects, ASC/MC, natal-to-return Sun longitude
agreement <0.001 degree. Unknown time of birth correctly rejected for solar.
The test files themselves were run without any external web/provider requests.

Asset integrity checked on operator host:
DE440 SHA256 a4ce9bf9b3282becc9f4b2ac3cebe03a2ae7599981aabd7265fd8482fff7c4b5;
GeoNames SQLite SHA256 98f6fd9046819ff380a5e0ef24bff4a851a58cbc593290e66c158c11a7fa8350.

Running production container at smoke moment: healthy, revision
0733bd0d374405b96af4a5be18ddf57c7c175b18, S3 backend healthy.
Anonymous POST /mini-app/api/astro/places and lunar/compatibility -> 401
(expected signed Telegram requirement). Full natal, karma, year/month, solar
-> 404 because dependent #578 and #579 are NOT deployed. End-to-end signed
Telegram-admin WebView/HTTP smoke remains pending until protected CI merge and
exact-SHA deployment. No claim of complete production release.

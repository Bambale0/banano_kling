# Astro two-person compatibility — Telegram Mini App UI integration

Stacked on PR #582 (full JPL synastry API), which in turn depends on #581
and #579. Do not merge/deploy UI before backend's exact SHA is live and
admin-only API smoke passes.

- Both birthplaces must be explicitly selected from the server-side GeoNames
  city autocomplete. The form sends separate canonical numeric `place_id`s;
  historic IANA zones display as readonly values and cannot be spoofed by
  the UI. No free-text place is converted into invented coordinates.
- Compatibility now calls `/mini-app/api/astro/compatibility/full` and renders
  the actual versioned two-chart JPL facts: interchart aspects plus both
  directional house overlays. If a receiver has unknown birth time, that
  direction explicitly reports houses are not calculated.
- On edit, city change, access revocation, slow or out-of-order API responses,
  previous results are invalidated. No billing or persistence.
- When GeoNames is unavailable, do not propose an impossible manual time zone
  override: the full JPL service requires real server-resolved geography.

## Verification / scope

- 18/18 Astro React unit and integration tests pass, including two city IDs,
  historical zones, age-independent date validation and no result after 403.
- TypeScript, ESLint, and Next.js 16 static export build pass.
- `e2e/critical-flows.mjs` includes new two-city GeoNames selection and
  display of directional house data. Its *Astro critical path* passed in
  actual Chromium after staging `out/` in `.e2e-server/mini-app/`.
- Full `critical-flows.mjs` execution ran Astro and other private Repeat,
  Feed/Profile and Seedance upload cases successfully but stopped later in
  the separate `seedance25-identity-transfer.mjs` on missing `Видео` button.
  Do not mark the whole cross-product suite green from that run. Protected
  CI must provide independent all-suite verdict before production.
- Real Telegram mobile WebView, an actual signed admin identity, production
  timezone autofill and exact-sha frontend deploy remain to be verified.

Skills: Bambale0/.agents systematic-debugging, test-driven-development,
verification-before-completion and frontend-ux-audit, subject to AGENTS.md.

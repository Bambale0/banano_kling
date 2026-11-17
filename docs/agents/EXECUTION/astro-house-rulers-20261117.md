# Astro house rulers and overlays — deterministic contract

Scope: additive facts on the Telegram-admin-only Astro calculation pipeline.
No billing, pricing, account, S3, VK or other existing miniapp changes.

- Calculated Placidus cusps are the **sole** basis for house geometry.
- Configurable `houses.ruler_system` in `data/astro_settings.json` supports the
  explicit historical/traditional or modern planetary ruler convention;
  defaults to the checked-in `traditional` setting. This is a symbolic
  convention and must never be represented as a scientific prediction.
- Each natal chart now has 12 sourced `houses` (cusp longitude, sign, ruler)
  and `body_houses` (planet-to-house mapping). No extra planetary positions
  are inferred. The Mini App displays the ruler and house number from this
  computed backend result, never from client-side astrology guesses.
- Synastry provides **directional** planet overlays into the other person's
  birth houses, and solar provides natal-in-solar plus solar-in-natal overlays.
  Birth-time-unknown charts must not receive angles or houses; if either
  target's houses are unknown, that overlay direction is explicitly null.
- Invalid cusp arrays, nonfinite positions, incomplete angles or overlapping
  house geometry fail closed. No silent switch to Whole Sign at polar latitudes.

## Reproduction and checks

- TDD red: new `tests/test_astro_houses.py` failed to import before module
  existed; new integration cases failed for missing natal/synastry house data.
- TDD green: 134 backend Astro regressions passed; 16 Astro React tests passed
  after the new house-label assertion initially failed. Ruff, TypeScript,
  ESLint, and Next.js static production export build all passed.
- Real off-network JPL DE440+GeoNames smoke with fixed synthetic fixtures:
  `scripts/astro_house_rulers_smoke.py`: natal houses=12, solar houses=12,
  each overlay direction calculated, karma=4, annual samples=12, leap February
  2028=29 daily samples, solar Sun return exact and unknown-birth-time blocked.
- One existing pytest config warning about asyncio loop scope is not related.

## Release / exclusions

Use protected `tanyapi` CI gates, then exact-SHA backend+frontend production
smokes for signed admin and denied ordinary user. This PR **does not** implement
long 5k-18k word interpretations, secure report delivery, stored profiles,
payments, exact transit crossings, composited relationship charts or public
Astro access. Those remain separate acceptance gates under issue #544.

Skills applied: Bambale0/.agents systematic-debugging, test-driven-development,
verification-before-completion, frontend-ux-audit. Project AGENTS.md prevails.

## Protected `tanyapi` release baseline (17 November)

The verified ancestor #579 was merged as 14b27719, followed by the
unrelated retired-VK smoke fix af96e57e. This PR was rebased onto the
actual `tanyapi` SHA af96e57e, eliminating the already-merged ancestor
commits from its diff. The resulting isolated change passed 161 Astro
backend tests, 18 Astro React tests, TypeScript, ESLint, Ruff, Next.js
static export build and GeoNames/JPL-DE440 offline smoke. A new protected
CI run and exact-SHA rollout check are still required; local tests alone
do not authorize a direct protected-branch push.

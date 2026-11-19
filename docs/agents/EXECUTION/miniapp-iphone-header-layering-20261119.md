# iPhone Trends header / Telegram native safe-area regression — 2026-11-19

## Goal
Remove the visible overlap/order inversion where the Trends heading paints above the NEUROMIX status/header card in Telegram iOS fullscreen (user screenshot, 18:15).

## Baseline / evidence
- Starting tanyapi SHA: `62682822c72ffc5433de8e9436c803f16f5ff981` (PR #635).
- Screenshot: native Telegram Close/menu at top; `Тренды` heading visible in the strip above the NEUROMIX card.
- Source: `mini-app-shell.tsx` applied `safe-top` to the outer scroll container, while `hero-header.tsx` used `sticky` with `top: var(--miniapp-safe-top)`.
- Two outer `overflow-x-hidden` containers implicitly become overflow scroll containers and can prevent sticky behavior relative to the viewport.
- Previous E2E only checked a minimum header offset; it could pass while the gap still exposed a scrolled heading.

## Root cause / fix
- Consolidate the native top exclusion into the sticky header itself; keep `top: 0` and an opaque background so scrolling content cannot be seen above it.
- Change outer shell overflow handling to `overflow-x-clip`, avoiding unintended vertical scroll containers.
- Preserve horizontal landscape safe-area padding separately via `safe-horizontal`, without stacking vertical offsets.
- Keep media lightbox and bottom nav safe-area behavior from PR #635 unchanged.

## Test / acceptance
- Add responsive geometry E2E at 320/390/430 px, simulating Telegram 24px device + 56px content top insets.
- Assert header begins at viewport top, sticky top is zero, NEUROMIX card starts below 80px, Trends heading follows the full header, and scrolled content does not paint in front of the header.
- Assert bottom nav and lightbox safe-area regressions still pass.
- Require lint/build/CI/browser E2E on PR, protected squash merge into `tanyapi`, production CI + exact SHA for frontend and backend; verify HTTP /health and Mini App.
- Real Telegram iOS screenshot verification remains an explicit manual follow-up if unavailable through the browser suite.

## Scope
Frontend-only layout correction; no changes to auth, payment, back-end service contracts, model costs, providers, or other domains.

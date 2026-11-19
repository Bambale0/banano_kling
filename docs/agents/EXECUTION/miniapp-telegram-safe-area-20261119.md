# Telegram Mini App: native Back/Close overlap — 2026-11-19

- Baseline: `tanyapi` SHA `d365f1db5a5add93e152ebc8a733616e1537cfe2`.
- Task branch: `fix/miniapp-telegram-safe-area-layout-20261119`.
- User-visible requirement: native Telegram Back/Close must never overlap actionable Mini App controls; same on 320/390/430 px and after fullscreen/viewport changes; preserve navigation and fullscreen.
- Source evidence: `app/layout.tsx` requests fullscreen; `mini-app-shell.tsx` uses `safe-top`; `globals.css` previously used only `env(safe-area-inset-top)`; `hero-header.tsx` was `sticky top-0`; feed/profile fullscreen viewers place close icons at `top-4`; bottom nav previously ignored Telegram content insets.
- Root cause assessment: missing Telegram `contentSafeAreaInset` in app shell/viewers and sticky positioning. No device WebView reproduction performed yet, so observed source issue is distinct from production visual confirmation.
- Telegram contract: `safeAreaInset` for device chrome; `contentSafeAreaInset` for Telegram UI, with live CSS variables, per https://core.telegram.org/bots/webapps. Fallbacks must work in ordinary browsers and older clients.
- Scope: shared CSS, shell/header, feed/profile lightboxes, workspace sheet header spacing and geometry regression in existing browser E2E. No backend/API/schema/payment/provider/auth/VK contour changes; no new mutable business values.
- Regression: Playwright geometry at 320/390/430 px simulates top device=24 px, Telegram content top=56 px, bottom=12+8 px; asserts header, sticky offset, lightbox close and content, tab nav remain clear of native bands; restores viewport/insets before existing flows.
- Verification required before release: lint, frontend production build, relevant tests and browser E2E; Telegram Android/iOS/Desktop manual visual smoke after exact-SHA deploy, especially fullscreen transition, native Back/Close, media preview, scrolling and bottom tabs.
- Rollback: revert this PR; no migrations/config changes.
- Status: source changes and regression test authored; tests, CI, production build, deployed SHA and device smoke are not yet verified.

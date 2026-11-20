# NEUROMIX / website top-up auth loop — fix and verification

Date: 2026-11-20. Base: tanyapi c774a0c8f2f8221486bc3d7cc5b0aac92db56f86.

## Reproduction and root cause

Native Telegram Mini App → external website top-up link → /login?return_to=/mini-app/?intent=topup&package_id=...&provider=... → website identity (Yandex/Google) plus verified Telegram link. The POST /mini-app/api/web-auth/studio endpoint mints a signed webstudio_* Telegram-shaped launch credential bound to a revocable web session (bot/web_auth.py). The frontend returns to the same static Mini App bundle with that credential.

frontend/miniapp-v0/lib/web-payments.ts originally recognized ONLY query_id=browser_* as a website checkout. webstudio_* failed isBrowserPaymentSession(), so the browser was treated as native Telegram with Stars-only checkout. The fiat action offered the website login again. This caused the reported loop. Browser versus native Telegram authority, not the visual appearance of the shared app, determines payment capabilities.

## Fix

Recognize server-minted webstudio_* query IDs (restricted to the verified token character/length contract from verify_studio_bridge) as website sessions for the payment-surface predicate while retaining the existing browser_* compatibility.

- A genuine Telegram WebView stays Stars-only and opens website via the original login link.
- A linked browser webstudio_* session shows fiat providers and uses existing server-side payment authority, including revocation. No shared wallet cutover, fake Telegram ID or new provider adapter.
- The existing allowlisted return_to preserves top-up intent, package, provider and promo. No auth credentials in query parameters; signed initData remains in the URL fragment.
- No price, payment/refund, DB, model, provider or feature-flag changes.

## Evidence

- Reproduced red: webstudio_* erroneously classified as native Telegram.
- Fixed green: 16 payment predicate tests including malformed query IDs and native Telegram.
- Full Jest: 124 suites, 1013 tests passed.
- Next 16 optimized production build, TypeScript and ESLint passed.
- Landing login Chromium E2E: synthetic webstudio_* redirect retains top-up, package, provider and referral.
- Payment Chromium Android E2E: real Telegram fixture offers Stars; browser webstudio_* offers a card and generates one fixture payment link.
- Local WebKit is blocked by missing Linux shared libraries; iOS WebKit production compatibility is not claimed tested locally. GitHub CI remains release gate.
- Local backend pytest could not collect because the host Python lacks aiogram; no backend code changed.

## Release

Normal PR to protected tanyapi, full required CI. Verify exact SHA in healthy Docker, public frontend revision, HTTP /health and anonymous web-auth 401. Authenticated payment smoke needs a dedicated linked TEST account, not customer's cookie, signed fragment or financial data. Rollback by reverting the frontend predicate patch. Do not enable Draft #646 financial flags as part of this fix.

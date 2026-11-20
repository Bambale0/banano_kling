# NEUROMIX — browser access to the same Mini App bundle (read-only rollout)

Date: 2026-11-20. Base: tanyapi 1649fe602cbc94776f770f49d66d2b48d9d0fbfe (includes browser-payment fixes #654 and #655). Branch: feature/web-workspace-current-20261120.

## Scope, observed architecture, user-visible behavior

The canonical React/Next Mini App already has a single native model registry, verified shared account actor, revocable website session and owner-scoped read-only Telegram task APIs from #647–#651. Its paid generation and bootstrap store still require Telegram initData; Draft #646 cannot safely merge while users.credits and shared_wallets.live are separate financial authorities.

This increment enters the SAME /mini-app/ static export and bundle with ?web=1 for authenticated browser-only sessions. It uses a read-only workspace rather than mounting paid Telegram MiniAppShell under a counterfeit Telegram ID. Real Telegram WebView credentials retain the native shell; signed VK behavior is not changed.

The server, never URL or client-supplied actor IDs, determines ownership:

- GET /mini-app/api/web-auth/actor authenticates before private loading.
- GET web-auth/catalog consumes the same native model registry from #649 without financial metadata or web paid actions.
- GET web-auth/history reads only verified owned Telegram tasks via #650. Browser-only accounts have no legacy history.
- GET web-auth/task reads owner-checked, privacy-sanitized detail via #651. Hidden prompts are also suppressed by the browser UI.
- POST web-auth/logout revokes the cookie. UI clears owned media immediately, aborts in-flight reads and does not restore it on failure.
- Focus/visibility revalidation hides private media until the exact owner and wallet scope are verified again after cross-tab logout/account switch.
- All requests use same-origin credentials and no-store. Images load lazily; videos use preload=none. No charge, refund or provider call.

Website login: Yandex/Google use configured OAuth/PKCE, email uses the existing secure one-time code backend if configured; Telegram OIDC remains unchanged. Browser-only Yandex users automatically reach the web workspace without forced Telegram linking. Optional link remains at /login?link=telegram; verified linked Telegram legacy studio is preserved. Linked browser readers get an explicit /login entry into the already verified paid legacy studio without claiming balances are merged; browser-only users do not receive that CTA. Safe bounded ref/startapp hints survive OAuth.

## Verification

TDD: first browser workspace test failed due missing import; focus-revocation test failed when private history stayed visible after external session revocation; two new CTA tests failed RED and passed GREEN after distinguishing linked legacy studio from independent-web billing.

- RED: email redirect test failed (missing function); GREEN: server-approved same-origin return to login preserves OAuth/account routing and rejects unsafe destinations.
- Earlier full frontend Jest: **126 suites and 1023 tests passed**. After adding the final linked-studio CTA tests, full local reruns reported **123 passed / 3 failed suites (1016 passed / 9 failed tests)**, all in unrelated reference-upload suites; those 3 suites pass **11/11 in isolation**. This remains a release gate for clean GitHub CI, not a claim of a fully green final local suite.
- TypeScript tsc --noEmit: passed.
- Next 16 optimized static export: passed.
- Playwright e2e/landing-login.mjs: passed at 320, 390, 768, 1440 widths, including Yandex-only, email OTP, Google OAuth, voluntary TG linking, linked legacy studio, browser history/privacy/logout and referral/checkout continuity.
- ESLint on changed components: no warnings/errors. Diff check and basic changed-text secret scan: passed. No paid provider smoke or financial migration.

## Release, rollback, follow-up

Only merge to protected tanyapi after full CI. Verify exact production Docker/frontend SHA, health, anonymous read-only endpoints; test authorized readback with a dedicated test-linked account. Rollback by reverting additive frontend changes. No DB, payment, provider, legacy Telegram callback or financial feature flag changed.

This is NOT 100% platform parity: independent web paid generation, account-scoped execution, and a single shared financial authority remain blocked. Draft #646 must not be merged, nor web paid flags enabled, until writer fencing, opening balance precision, late refund reconciliation, payment idempotency and provider end-to-end contracts are verified. Financial read-only PR #652 reports blockers; it does not authorize a live wallet migration.

## Production configuration observed at baseline

Public GET /mini-app/api/web-auth/config on 2026-11-20 returned providers: {google: false, yandex: true, telegram: true, email: false} (anonymous). Thus Google and email UI are contract-tested but disabled until corresponding server OAuth/mail provider credentials are configured. Never claim those methods already work live. Production Docker/frontend still reported 3ccfd596 during the earlier merge's own ongoing release verification; release this PR only through strict GitHub CI and exact-SHA deploy gates.

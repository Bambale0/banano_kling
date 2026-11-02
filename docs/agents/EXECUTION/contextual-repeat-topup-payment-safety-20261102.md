# Payment safety follow-up for contextual video-repeat top-up

- Date: 2026-11-02
- Base: production `tanyapi@d177a98ef3d551e81d71c25468dceb99f0a0d774` (merged PR #394 and #396)
- Branch: `fix/contextual-topup-payment-safety-20261102`
- Previous competing branch: PR #395 was based on pre-#394 code and must **not** be merged. Its direct merge would replace recently released UI and break strict branch protection; only small, independently reviewed hardening is ported.
- Workflow: existing `AGENTS.md` -> inspect effective base and CI -> regressions -> minimal implementation -> exact SHA CI -> protected native auto-merge -> deploy -> smoke.

## Proven baseline

- Production `/mini-app/revision.txt` served `d177a98ef3d551e81d71c25468dceb99f0a0d774` directly from SentinelX-connected tanyapi host.
- Public `https://tanyapi.chillcreative.ru/health` returned `{"status":"ok","service":"tanya-bot"}`.
- GitHub Actions deploy run `41440438932` passed the protected CI and reported matching deployed/container/frontend SHA with a healthy backend container.
- PR #394 and #396 already delivered the reusable funding offer, dynamic configured packages, explicit checkout and return to the untouched video/trend editor, auto-open on repeat quote, plus mocked mobile E2E.

## Bug diagnosis

1. On Telegram Stars invoice callback `paid`, `BalanceSheet` called global `refreshTasks()`. This sets `state.isLoading=true`; the Mini App shell swaps the editor for the global loader, which unmounts the repeat and can discard photos/prompt/choices. Moreover, any refresh/network error could flow into the payment error toast *after* a successful Stars payment.
2. When `openInvoice()` is missing/fails or a Tribute link is opened, neither code path populates `readyPayment`. If the Telegram link bridge is absent/throws and `window.open` is blocked, the UI previously claimed a reusable payment link existed but did not render one.
3. A late provider response after closing payment can leave the earlier signed invoice in component state, causing an irrelevant/stale link on the next payment attempt.

## Changed behavior

- Add authenticated `refreshBalance()`, which applies the confirmed backend bootstrap directly **without setting global isLoading** and throws on error. Do not synthesize successful balances, add invoice retries, or change money/credit business logic.
- Separate Telegram-confirmed payment from a later failure to refresh the wallet. Explain that the payment is confirmed, the balance has not yet refreshed, and **no second purchase is needed**.
- Preserve a user-clickable `https:` payment link in the existing sheet for the Stars/Tribute fallback when no normal `readyPayment` exists; do not navigate the original Mini App WebView away from its repeat draft.
- Clear stale links on closing checkout, discard late payment replies to a closed sheet; preserve existing one-in-flight guard, explicit user-initiated checkout, original signed URLs and backend idempotency.
- No new backend routes, schema migrations, provider changes or mutable business settings.

## Verification

- Jest: existing `balance-sheet-payment.test.tsx` plus cases for paid-Stars/refresh-failure, no Telegram bridge & popup blocked, Tribute fallback without invoice creation, and stale late reply after close.
- Mandatory gates: `tanyapi` Python/deploy validation, safe regression, Mini App browser E2E, production Docker image, plus frontend build and focused tests.
- After squash auto-merge, confirm exact merge SHA and deployment for backend and Mini App static export, public `/health`, `revision.txt`, operational logs. No real customer payment or paid generation is to be triggered.
- Rollback: revert fix PR in `tanyapi` and use standard CI/CD, leaving #394/#396 base intact.

## Exact-head review iteration

- PR #398 first CI: focused Jest `11 suites / 80 tests` passed, Mini App static build, Python/deploy validation, PostgreSQL schema, WAN provider tests and publication scope green; required browser E2E / full Python regression were still running on that superseded SHA.
- Exact-head Codex review identified three P2 edge cases. Patched: (1) reject **late Stars** response after sheet closes before even reaching native invoice/fallback; (2) snapshot `chatAccessRevision` *before* async bootstrap to avoid race with write-access grants; (3) automatically scroll the fallback link into view, like signed `readyPayment` panel.
- Added Jest checks for late Stars response never opening old invoice, and visibility/scroll behavior for manual payment fallback. Recheck latest SHA through strict gates and review; no shortcuts to production.

Status: awaiting latest-head CI, review, protected squash auto-merge, exact-SHA production deploy and read-only smoke.

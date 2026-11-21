# Linked Telegram balance in browser — no shadow wallet

Scope: read-only production UI/API enhancement. Base: `tanyapi` after PR #673.

## Evidence and root cause
Legacy Telegram `users.credits` (PostgreSQL double precision) is still the payment/generation authority. The new `shared_wallets` live ledger is a separate authority for independent browser-only users. Login/linking alone changes ownership identity, not financial ownership. Copying the legacy balance into the shared wallet would allow duplicate spending while direct SQL legacy writers remain active.

Production read-only evidence on 21 November 2026: 94,827 legacy Telegram users; 86,833 with positive credits; 12,328 internally pending payment records (not confirmed paid invoices); zero shared live journal entries and zero opening claims. Some legacy float values are not exactly representable as 4 decimal fixed-point amounts.

## Design
- `GET /mini-app/api/web-auth/web-payments/balance` uses authenticated HttpOnly browser cookie. Independent web users retain existing exact `web_live` wallet JSON.
- Verified account with real Telegram legacy link reads **only the original** `users.credits`, with identity binding checked before and after the query. Revoked cookie, missing identity or invalid source fails closed.
- Read-only display to 4 places; `precision_review` indicates a legacy float residue, without changing source bytes or declaring an approved migration.
- A previous independent web wallet, if nonzero after account linking, is displayed separately as `held_web_balance`; it is not added to available Telegram funds or double-credited. The old portal still needs an auditable transfer before this can be spent as one balance.
- Browser UI does not offer duplicate checkout/web-native generator to linked legacy accounts; existing verified webstudio Telegram studio continues to charge/credit the canonical legacy source. VK-only accounts remain cutover-gated.
- No DDL, wallet entry, user balance, transaction, provider invoice, old payment callback or task changes.

## Tests
TDD: new backend regression originally failed with HTTP 409 and frontend had no balance fetch. GREEN: `tests/test_web_wallet_browser_balance.py`, `tests/test_web_native_paid.py`, `frontend/miniapp-v0/components/browser-native-paid-entry.test.tsx`; TS and changed-file ESLint.

## Financial cutover still required
This is not a live balance import. A fully spendable single ledger across Telegram, browser-only and VK requires proof of all legacy writer fences, signed immutable opening manifests, rounding policy for precision cases, provider event reconciliation, late refund mapping and dual spend protection, with PostgreSQL tests before cohort activation. Do not toggle a new wallet authority just because a balance appears on both screens.

Rollback by reverting this API/UI projection only; no financial data migration or money liability changes.

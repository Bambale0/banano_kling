# Neironych balance alert — 2026-11-08

- Baseline: `tanyapi@14a719c3db05e7c419a63e73c74ab4d63f7af4c8`.
- Work branch: `feat/neironych-balance-alert-20261108`.
- Goal: proactively notify each configured Telegram admin when the provider's **cash** balance drops below 2,000 RUB. No generation, user wallet, or payment changes.

## Verified provider contract

Read-only `GET https://api.xn--e1aikcel5c5a.online/v1/balance`, authenticated with `NEIRONYCH_API_KEY` using `Authorization: Bearer`. Official `/guide?lang=ru` documents JSON string `balance_rub`, independent of `available_balance_rub` (cash plus approved credit). Unauthenticated endpoint returned HTTP 401 on 2026-11-08. The alert compares **`balance_rub` only**; invalid, non-finite, or absent values never trigger alerts.

## Runtime behavior

- Runs inside the existing Telegram bot startup/shutdown background-worker lifecycle, first check immediately, then every 15 minutes by default.
- If `balance_rub < threshold`, sends one Telegram message per `ADMIN_IDS` recipient. Equality (`== 2000`) is healthy.
- Redis `SET NX EX` claims are keyed per admin, providing atomic cross-process deduplication and default 12-hour reminders while the balance remains low. A valid healthy reading deletes the claims, rearming alerts after a later new drop.
- On definitive Telegram send exception the claim is released with atomic compare-and-delete Lua, permitting a later retry. Ambiguous Telegram delivery can still create a duplicate if an exception follows successful delivery. On Redis outage the monitor logs an explicit warning and **does not send unguarded duplicate messages**.
- Provider requests have a 10-second timeout, a single bounded retry for network/429/5xx failures, no redirects, and no secret-bearing logs. Other failed checks are logged and retried at the next interval.
- No schema migrations and no public API/FSM/Mini App changes. No direct customer charges or provider generation calls.

## Managed environment

Uses existing `NEIRONYCH_API_KEY`, `NEIRONYCH_API_BASE_URL`, `ADMIN_IDS`, and `REDIS_URL`/`REDIS_PREFIX`. New settings, default values:

| Setting | Default | Meaning |
| --- | --- | --- |
| `NEIRONYCH_BALANCE_ALERT_ENABLED` | `1` | Disable with `0` |
| `NEIRONYCH_BALANCE_ALERT_THRESHOLD_RUB` | `2000` | Cash balance threshold in RUB |
| `NEIRONYCH_BALANCE_ALERT_INTERVAL_SECONDS` | `900` | Poll interval, 60–86400 s |
| `NEIRONYCH_BALANCE_ALERT_REMINDER_SECONDS` | `43200` | Dedup/reminder TTL, at least interval, at most 7 days |
| `NEIRONYCH_BALANCE_ALERT_TIMEOUT_SECONDS` | `10` | HTTP deadline, 1–60 s |

If the key or admin IDs are absent, the worker is disabled with a reason logged. Invalid configuration fails closed without breaking the main bot.

## Acceptance / validation ledger

1. [x] Read AGENTS.md, branch baseline, bot lifecycle, provider adapter, Redis wrapper, existing tests and production docs.
2. [x] Verify balance endpoint + cash-vs-credit semantics from provider guide.
3. [x] Write behavior tests first (API contract, threshold, dedup, rearm, concurrency, invalid payload, Telegram failure, Redis outage).
4. [x] Implement provider HTTP reader, durable-ish Redis TTL dedup, bot startup/shutdown integration.
5. [ ] Verify CI/backend unit tests and lint on exact task SHA.
6. [ ] PR squash auto-merge into `tanyapi`; verify exact production image/backend revision and read-only live balance check.
7. [ ] Observe production logs for `event=neironych_balance_checked` and actual Telegram delivery when balance is below threshold (no synthetic low-balance notification to production admin by default).

Rollback: revert the PR from `tanyapi`; Redis dedup keys expire naturally, no migration needed.

Skills consulted: `Bambale0/skills:skills/engineering/tdd/SKILL.md`, `Bambale0/skills:skills/engineering/diagnosing-bugs/SKILL.md`, `Bambale0/claw:.agents/skills/backend-integration/SKILL.md`. Anthropic skills inspected; browser testing is out of scope for this backend-only feature.

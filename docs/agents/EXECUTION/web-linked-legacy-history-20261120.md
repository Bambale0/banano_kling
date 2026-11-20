# NEUROMIX verified browser → legacy Telegram generation history (read-only)

**Date:** 2026-11-20. **Base:** protected \`tanyapi\` SHA \`1a454fade6f5f75d35edb95c4283feff8e2e4dca\`. Incremental feature branch \`feature/web-linked-legacy-history-20261120\`.

## Goal

A verified browser session (Yandex/Google/email/Telegram OIDC) voluntarily linked with the same Telegram identity should be able to read its **existing** Telegram-generated tasks. An unrelated or revoked web account must **never** read another person's photos, videos, prompts, references or private trend recipes. This is a read-only projection, not a financial migration or new task execution path.

## Endpoint and data flow

\`GET /mini-app/api/web-auth/history?cursor=<owned task id>\` registers before Mini App's fallback routes:

1. Reject any unknown query parameters, oversized/blank cursor (400). Never trust client account_id, telegram_id or user_id.
2. Resolve the existing \`nm_web_session\` through \`resolve_account_actor(request)\`, which checks revocation and the account's verified identities. Missing/revoked credential → 401.
3. If account has no real verified Telegram identity **and** legacy user link, report \`{"ok":true,"scope":"web_only","recent_tasks":[],"next_cursor":null,"cursor_reset":false}\`. No legacy task query or synthetic Telegram ID. This does not yet expose future standalone-web jobs.
4. If Telegram account is verified and legacy-linked, reuse **unchanged** native \`miniapp._fetch_recent_tasks(telegram_id,limit=9,before_task_id=cursor)\`, which scopes the SQL query to the actor's own \`generation_tasks.telegram_id\`, excludes \`genjutsu\`, formats known result URLs without a blocking external S3 HEAD, returns 8 plus one pagination sentinel. A stale/foreign cursor falls back to that owner's head, \`cursor_reset=true\`.
5. Reuse \`trend_task_privacy.sanitize_task_api_payload\` to hide protected prompts/private references exactly as native Mini App history does.
6. **Revalidate the authenticated account, verified Telegram link and exact legacy Telegram ID before returning any task payload.** This closes the logout/unlink/identity-reassignment race while slow task/media reads are running. Authentication failure → 401; changed link → 403.
7. Respond \`Cache-Control:no-store\`, \`Referrer-Policy:no-referrer\`; on internal errors fail closed with 503 \`history_unavailable\`, never a database/private exception body.

## Tests / TDD evidence

- RED: request to missing route returned 404; added route.
- RED: unlink during fetch unexpectedly returned 200 with private Telegram result; after second actor check it fails closed.
- Direct HTTP regressions: anonymous 401; browser-only Yandex user sees no legacy jobs; verified Telegram link sees only that user's tasks; sanitizer invoked; unexpected query account_id/telegram_id rejected; stale cursor owner-scoped; revoked cookie 401; logout and link removal *during* fetch fail closed.
- Real in-memory isolated DB records for two distinct users confirm owner sees only own task IDs after Yandex link; after link deletion legacy history becomes inaccessible.
- 121 backend tests passed on exact production base with #648, 73 environment-dependent skipped (includes shared accounts/identity, web auth, legacy native task history, revocable studio). Ruff targeted and Python compile passed. Full protected-branch CI, PostgreSQL, E2E and production smoke are still required.

## Production release and rollback

Normal protected \`tanyapi\` PR, GitHub native squash auto-merge after complete CI. On deployment verify exact SHA across checkout/Docker/public frontend revision, \`/health=200\`, anonymous \`GET /mini-app/api/web-auth/history=401\`, invalid query rejected, and a **known test-linked account** returns only owned tasks. Do not use a real customer's cookie, raw prompt or private media URL in logs.

Rollback by reverting the small additive route/handler. No migrations or balance changes; the existing Telegram native history continues unchanged.

## Remaining work toward 100% cross-platform parity

This endpoint does **not** merge legacy Telegram jobs with \`web_generation_tasks\`, execute Seedance 2.5 or other paid models for web-only users, migrate \`users.credits\` into shared wallet, combine purchase history, or make the MiniAppShell work for Yandex-only accounts. Those P0/P1 conditions in Draft #646 still block "fully working cross-platform" release. Provider adapters and billing flags are deliberately unchanged.

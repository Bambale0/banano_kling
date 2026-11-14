# VK #451 — independent owner-only saved-reference library

Status: incremental, with no financial changes. This does **not** make the
full 10-domain VK application ready or authorize any provider/write flag.

## Purpose

Telegram's saved_references table uses an internal legacy Telegram user FK.
VK-only users already upload owner-scoped photo references through the signed
`vk-image-upload` API, but cannot bookmark and reuse them across sessions.
Reusing Telegram's saved_references/user IDs would expose other accounts'
photos or create fake Telegram ownership.

## New native contract

- Additive `shared_vk_saved_references` metadata table in the existing
  shared-account SQLite/PostgreSQL schema, keyed by verified numeric VK user
  and opaque server-created reference ID; unique owner+URL hash.
- `GET /mini-app/api/account-preview/vk-references` lists only the signed
  VK actor's own records, never exposing owner ID or legacy TG data.
- `POST /mini-app/api/account-preview/vk-references` supports exact JSON
  `{action:"save",url,name}` or `{action:"forget",reference_id}`.
  Server validates original VK upload URL **and actual S3/local object**
  with the same owner verification used before every native provider call.
  Metadata saves are idempotent on URL; deletes are idempotent and cannot
  affect another owner.
- Reference quota is read from `VK_MINIAPP_SAVED_REF_MAX_ITEMS` (default
  100, configuration range 1..1000), with a transaction-scoped actor lock
  (SQLite BEGIN IMMEDIATE / PostgreSQL advisory transaction lock) to prevent
  race-based over-quota writes. No cost/provider/model is hardcoded.
- Forgetting a bookmark **never deletes S3 media**: active native tasks and
  references may still need the original object. Media cleanup belongs to
  the separate retention/reconciliation service.
- Native VK profile shows the user's gallery and can upload a new photo
  only when the signed VK server advertises `photo_upload_enabled`.
  Linked VK/TG accounts can **read/forget** VK-owned bookmarks but cannot
  bypass native write restrictions by linking Telegram.
- VK photo/video/trend composers allow selecting existing own bookmarks,
  combine with new uploads, invalidate a stale quote when refs change and
  honor the existing native worker's reference count. The backend always
  re-verifies ownership and media availability before execution.

## Verification

Focused tests exercise owner isolation, foreign URL rejection, duplicate
save under concurrency, atomic quota, stale/deleted bookmarks, signed
VK bearer, invalid body, linked identity, upload/save timeout retry with
same original URL and native composer reuse. Full protected CI including
SQLite/Postgres, Mini App Jest, VK static build and browser E2E required.

No independent VK money, task delivery, TG wallet, S3 bucket settings or
security flags are modified by this slice. Its rollout still requires
exact-SHA release smoke and real signed VK WebView verification.

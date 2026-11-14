# Execution ledger: VK #451 — shared feed comment reading

Baseline: `tanyapi@871fa96ab0da13415e1a4ca46c400ada1a81589f`
Branch: `feat/vk451-public-feed-comments-read-20261114`

## User-visible result and scope

An independently authenticated VK Mini App visitor can open a **public** post in the
same Telegram/VK feed and read its existing comments, with author display name
and text. Comments are fetched only on demand, through an actor-checked VK-only
API. No mandatory Telegram link, fabricated Telegram user, private profile
comment, billing, external generation or message delivery is introduced.

The write action is deliberately NOT enabled: the current shared `feed_comments`
table has a non-null foreign key to legacy Telegram `users.id`. A native VK
write API must first receive an actor-neutral shared comment ownership schema,
moderation and rate limits, and real VK WebView acceptance. Do not fake the
Telegram foreign key to activate write support.

## Evidence and chosen seams

- `bot/database.py:get_feed_generation_card(..., viewer_user_id=None)` already
  authorizes public feed rows and excludes nonpublic/adult tasks.
- `bot/database.py:get_feed_comments(..., viewer_user_id=None)` already returns
  comments in the common feed without requiring a Telegram viewer ID.
- `bot/shared_accounts/actor.py:resolve_platform_actor` validates a revocable
  signed VK session; no lookup by caller-supplied user ID.
- `frontend/miniapp-v0/components/vk-standalone-discovery.tsx` already opens
  public feed details, but did not offer their common comments.

Test seams: authenticated `GET /mini-app/api/account-preview/vk-feed-comments`,
the actual VK feed detail UI, and signed client request. No direct payment/provider
tests: this slice has no charges or provider calls.

## Implementation

1. RED: new Jest public-feed-comments test could not import its component.
2. GREEN: implement server-authenticated read with public/feed-only ACL,
   strict numeric feed ID, Telegram-aligned 80-default/150-cap, and a limited
   response DTO excluding Telegram IDs, user IDs, referral data and private
   recipes.
3. Add native VK API client plus a read-only, abortable UI component with
   stale-response protection and manual retry; mount on public-feed detail
   only when the viewer opens comments.
4. Add HTTP contract, invalid-ID and private-content regression coverage,
   client auth and malformed response coverage.
5. Verify isolated backend tests, frontend targeted suites, lint, TypeScript,
   production export, protected CI; exact-SHA production smoke after merge.

## Release and rollback

- Does not enable `VK_FULL_APP_PARITY_ENABLED`, any write or payment flag.
- Normal protected PR to `tanyapi` with squash auto-merge.
- After merge verify exact bot Docker SHA, TG/VK `revision.txt`, HTTP health,
  unauthorized GET 401 and public/private signed-WebView behavior if a safe
  signed test actor is available.
- Rollback by reverting the additive read-only PR; no schema migration.
- Full #451 remains OPEN: native comment writing, own VK publishing, all
  10-domain parity, wallet linking, services, video references and delivery.

## Verification ledger

- Preflight: read AGENTS.md, current VK parity architecture, platform actor,
  API, SQLite/PostgreSQL feed comments, frontend VK/Telegram boundaries.
- Local RED: Jest failed on missing `vk-public-feed-comments` module.
- Initial GREEN: 10/10 standalone backend tests; 75/75 focused Jest;
  Next.js production export + TypeScript successful; ESLint 0 errors with
  2 pre-existing warnings.
- Further tests and final exact-SHA deployment status recorded in PR / issue.

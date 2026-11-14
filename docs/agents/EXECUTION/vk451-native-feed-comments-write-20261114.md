# VK #451 — independent native feed comments

Baseline: tanyapi@871fa96ab0da13415e1a4ca46c400ada1a81589f
Task branch: feat/vk451-platform-feed-comments-20261114
Prerequisite: #512 read-only public comments, still awaiting protected safe CI at preflight.

## Product and security contract

Independent signed VK actors can write comments under the same published,
non-adult public feed entries as Telegram users. This is NOT a synthetic
Telegram user ID and never touches either wallet or a provider. Existing
Telegram comments are preserved. VK author display is deliberately generic
until a trusted profile identity and moderation contract exists.

Existing feed_comments.user_id is a NOT NULL foreign key to Telegram
users.id. Implement an additive actor-scoped vk_feed_comments table with
foreign key to generation_tasks, unique actor+idempotency request key and
actor+cooldown bucket. This protects concurrent requests/retries while
keeping both platform owners independent. Schema is created at initialization
on both SQLite and PostgreSQL and included in the PG bootstrap file.

New signed POST account-preview/vk-feed-comment accepts only feed_gen_id,
text (1..500 normalized characters) and client_request_id (16..80 safe
characters). Unknown fields and claimed user IDs are rejected. Creation is
conditional on the source remaining completed, public, retained and non-adult.
409 marks conflicting same-key payload, 429 another key within the cooldown
bucket; exact replay returns the existing row, never a second comment.

VK write feature flag VK_MINIAPP_FEED_COMMENTS_ENABLED stays OFF until real
signed VK WebView and production schema/abuse acceptance. Cooldown is configurable
via VK_MINIAPP_FEED_COMMENT_COOLDOWN_SECONDS (1..3600, default 10). Runtime
configuration and a future authenticated admin surface must be reconciled.

The common Telegram/VK feed reads both tables and counts both forms of comment
without exposing Telegram/VK actor IDs, hidden recipe, provider references or
referral codes. Native IDs use vk:<id>; legacy TG IDs retain their numeric form.

## Execution and validation

1. Read AGENTS.md, VK architecture, native actor and API, database abstraction,
   source SQL/schema, existing Telegram feed UI, tests and deployment rules.
2. RED: Python test import failed on missing native comment service.
3. GREEN: 20/20 focused Python tests (actor scoped writes, SQLite migration,
   concurrent idempotency, replay mismatch, spam limit, private/adult checks,
   signed HTTP and invalid body rejection).
4. GREEN: 13/13 focused Jest (authenticated client, no TG identity in request,
   accessible composer, ambiguous same-key manual retry, unmount race, validation).
5. Independent disposable PostgreSQL 17 transactional test passed CREATE TABLE,
   index, ON CONFLICT, two owners, rate uniqueness, combined count and FK CASCADE;
   rolled back and destroyed test container. Production DB untouched.
6. Next: integrate #512 read component, shared on-demand composer, full frontend
   build/lint/E2E, protected PR and exact-SHA deployment.
7. No full parity readiness is claimed. Full #451 still needs feed publishing,
   all ten native API domains, shared shell, finance reconciliation, services,
   real VK WebView and result delivery.

## Release and rollback

Protected PR to tanyapi only, squash native auto-merge after all mandatory CI.
Keep all VK write/payments/full-parity switches OFF until signed production
acceptance. Rollback by disabling the feature flag; additive table and existing
data stay intact. No destructive migrations, production financial writes,
provider charges or real-user messages are authorized.

## Integrated read/write checkpoint

Merged the #512 signed public read source plus #513 Seedance geometry patch
in a separate task branch; preserved both shared API/client flows. GET
now supports legacy numeric and namespaced VK IDs, exposing is_mine only for
the signed VK actor. Composer is mounted only when the backend authorizes it.
A confirmed POST refreshes the common feed comments and count; unknown
network responses never generate a new idempotency key automatically.

After finding an intermittent SQLITE_BUSY on concurrent journal_mode=WAL
connection initialization, serialized only the native SQLite writer opens
with a short-lived event-loop-local weakly held lock. PostgreSQL retains
full concurrency and database uniqueness remains authoritative. The same
flaky concurrency case passed 20 repeated runs. Merged targeted tests:
38/38 Python, 90/90 Jest; follow with full CI and exact-SHA production smoke.

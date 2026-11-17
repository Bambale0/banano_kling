# Astro Telegram report delivery — guarded production rollout

Baseline `tanyapi`: `586cb93be84a98e3e5133995a85bab02f784ef5a`.

## Incident and change

- Live report jobs existed and the KIE Responses adapter returned successfully, but two Nov 17 jobs ended `failed`, `temporary_provider_failure`, with **zero checkpoint sections**. A provider response returning HTTP 200 does **not** prove that the report section passes the min-word/schema/numeric-proof gates. This backend PR does not change those correctness validators or claim the two reports recovered.
- Existing Astro Mini App returns a completed report through owner-scoped signed status API, but had no Telegram delivery integration. A user closing Mini App could receive no push outcome. The new SQL outbox is inserted **in the same database transaction** as completed or terminal failed state, without modifying wallet/payment data.
- Outbox contains only `job_id`, owner ID, state, timestamp, attempt count and Telegram message metadata. All completed content remains encrypted in the report jobs schema. A private `BufferedInputFile` text document contains every validated section; no public CDN URL, local export, group chat or birth facts in logs. The recipient is the exact Telegram owner, and authorization is rechecked just before send.
- Telegram failures/uncertain timeouts use a bounded env-configured exponential backoff and persisted lease; `message_id > 0` is required before marking delivered. Terminal generation errors send a safe short message instead of silently disappearing.
- Exactly-once message delivery is **not guaranteed** if Telegram accepts a document but its response is lost. The system provides exclusive claims, persisted acknowledgment and at-least-once recovery. Workflows are idempotent at the outbox/lease level, not at Telegram transport.
- Owner history and status remain owner-scoped; successful reports expose `telegram_delivery` metadata only to their owner. Revoked admins never receive the report. Privacy erasure and retention purge remove outbox metadata.

## TDD and verification evidence

- RED: new delivery module absent. GREEN: 5 dedicated fake-bot tests plus original Astro queue/worker suites; transient error, terminal failure notice, role revocation, owner erasure, restart recovery.
- Full local Astro suite: **271 passed, 9 skipped**, Ruff clean. Environment used isolated QA venv; initial missing numpy/psycopg imports fixed *only* in QA venv.
- Real disposable PostgreSQL 16 on localhost, ephemeral `astro_delivery_qa` database and synthetic credentials, no production data: native DDL, 2 concurrent claims => 1 delivery, delivered status, owner scope, deletion passed. Script `scripts/astro_telegram_delivery_pg_smoke.py` refuses any non-disposable/non-local DB target.
- No live paid KIE run or Telegram push attempted by this PR's tests. Protected CI and exact-SHA production deploy required; after deploy verify queue task, job/email logs (without content) and one signed admin result.
- Two already-failed reports are not silently requeued, and no historical notifications are backfilled. User must explicitly retry failed report after provider quality fix / safe configuration acceptance.

## Rollout / rollback

- Deployment only to protected `tanyapi`, no main/dev/VK/payment changes.
- New DDL is additive native PostgreSQL/SQLite CREATE TABLE + index, no destructive migration.
- Operational controls: `ASTRO_TELEGRAM_DELIVERY_MAX_ATTEMPTS`, `ASTRO_TELEGRAM_DELIVERY_TIMEOUT_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_LEASE_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_RETRY_BASE_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_RETRY_MAX_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_POLL_SECONDS`.
- Roll back the code release to stop new notifications; encrypted reports and unprocessed outbox metadata remain in PostgreSQL for later reconciliation.

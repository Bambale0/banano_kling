# NEUROMIX: production log audit and trend-preview concurrency incident

Audit date: 2026-11-23 (Moscow); evidence interval: approximately
2026-11-20 21:36 through 2026-11-22 21:36 **UTC**.
Scope: `Bambale0/banano_kling` production `tanyapi` only.
Procedures: `Bambale0/.agents/skills/diagnosing-bugs`,
`devops-troubleshooter`, `tdd`. Raw logs, personal IDs,
provider payloads, access tokens and secrets are deliberately omitted.

## Sources of evidence

- Production bot log files: `logs/bot.log.2026-11-20`,
  `logs/bot.log.2026-11-21`, and `logs/bot.log`.
- Nginx `access.log`, rotated `access.log.1`, `access.log.*.gz`,
  `error.log` and `error.log.1`; host-level access counters include
  **other virtual hosts** and must not be misrepresented as NEUROMIX-only.
- PostgreSQL 16 server log and read-only `pg_stat_activity`, limited
  production `notification_deliveries`, `notification_campaigns`,
  `web_payment_orders` status counts.
- Production Docker image revision, running environment and read-only
  HTTP health checks. Actual live media storage mode is Selectel S3.
- GitHub PR/CI and exact release SHA.

## P1: trend preview rendering races

Production logged **45 lightweight MP4 preview** and **9 JPG poster**
exceptions, affecting **22 distinct source media files**. The stack traces
terminate in `Path.replace()` (`trend_preview_service.py:134` or the
equivalent JPG poster code) with `FileNotFoundError`.

Root cause is a deterministic **shared ffmpeg temporary pathname**:
`output_path.with_suffix(".tmp.mp4")` / `(".tmp.jpg")`.
Two concurrent renderers for one output race to overwrite, delete or
rename the same temp file; the error handler can then delete the
successful peer's final output.

**Before-fix reproduction:** two concurrent calls to
`_run_ffmpeg_preview()` against an isolated fake ffmpeg with a barrier
returned `["FileNotFoundError", "ok"]` and used one temporary path.
This exercises the actual caller code, with no real output or customer
assets affected.

**Fix in this PR:** UUID-unique per-invocation temporary paths,
`try/finally` local-temp cleanup, atomic `replace`, and no deletion
of the shared final output when an individual renderer fails.
New concurrent MP4/JPG and peer-output-preservation regression tests
are in `tests/test_trend_preview_concurrency.py`.

**Isolated post-fix verification:** both simultaneous MP4 renders
returned `ok`, both JPG poster renders returned `ok`, and the two
temporary paths differed. A simulated ffmpeg failure removed its own
temporary artifact. This **does not** replace CI or a post-deploy
production user-flow check.

## P1: PostgreSQL pool/availability

Historical bot logs include **251** instances of
`PostgreSQL pool exhausted for 10.0s`. A concentrated incident at
**2026-11-22 18:44–18:48 UTC** corresponds to failed Mini App
bootstrap/task-detail requests (72 analyzed bootstrap stack traces
end in `PoolTimeout` / `OperationalError`). Multiple Nginx
upstream timeouts began around **18:42 UTC**, so the pool exhaustion
may be part of a larger upstream stall rather than the original
trigger.

The DB pool is bounded to a configured maximum (current default code:
24); live PostgreSQL `max_connections` returned 100. During the audit
there was no persistent pool outage; PG activity showed only a few
connections. PostgreSQL logs contain repeated `there is already a
transaction in progress` warnings: examine transaction lifecycle,
connection hold time, and long synchronous tasks before raising pool
limits. **Root cause beyond the connection contention is not proven.**

## P1: missing historical media keys

Approximately **9,840** S3 materialization warnings with HTTP
`404/NoSuchKey` correspond to **1,392 distinct `uploads/...` keys**
(primarily `feed` and `refs`). No corresponding local file existed
for these 1,392 keys at inspection time. Verify which database/history
records reference them, discover recovery sources, and backfill
**with digest checks** rather than deleting anything.

This is not a total S3 outage: 10 fresh samples and 40 old `feed` /
`refs` samples had matching remote size and SHA-256 metadata.
The host still held about **338 GiB** in local `static/uploads`
(mostly historic `feed` and `refs`), with roughly 196 GiB free
at the audit. `MEDIA_STORAGE_BACKEND=s3` and
`MEDIA_S3_KEEP_LOCAL_CACHE=0` are enabled; unmarked historic files
are outside the automatic materialized-cache cleanup.
**No storage deletion was performed.**

## P1: notification campaign terminal failures

Campaign **49** had approximately 41,909 sent, 25,649 failed after
five attempts, 22,640 blocked, and 4,049 queued at audit time.
`TelegramBadRequest` is recorded as a class; the system does not
retain an actionable, safely normalized Telegram failure reason.
Treat blocked/deactivated recipients separately from malformed
content or recipient-specific terminal failures; fix observability
first before replaying anything, respecting idempotency.

Campaign **48** was completed with 44,500 delivered and 49,152
blocked. Do not interpret blocked Telegram recipients as systemic
server errors.

## P1: payment callbacks and release safety

- Approximately 1,967 Lava webhook requests had HTTP 403 in the
  historical window **before** the previous IP allowlist repair.
- After that repair and before this audit's latest deploy, some
  authenticated callbacks returned HTTP 503 while provider invoice
  status remained `in_progress`; intentional fail-closed behavior,
  but retry latency could exceed the callback deadline.
- [Lava fast-path PR #687](https://github.com/Bambale0/banano_kling/pull/687)
  has passing CI but was **not merged** at the audit check.
- [Web invoice-only fix #688](https://github.com/Bambale0/banano_kling/pull/688)
  merged and exact-SHA production deployment at
  `70932fc5bb91c3541d385d2df0cdeab1fc75ac30` was confirmed.
- The legacy `web_payment_orders` table still had **12** orders in
  `creating` status without a safe verified binding; do not recreate
  invoices or credit balances without provider reconciliation.

## Nginx and deploy continuity

The shared host access log counted 1,519 total 5xx responses
**across all virtual hosts** over the audit window. Confirmed
NEUROMIX-relevant examples include 111 Nginx 502 and 32 Nginx 504
responses for `/mini-app/api/bootstrap`. The
`neuromixbot.com` error vhost logged 144 upstream connection
refusals and 94 upstream timeouts during the same period. A
single-container replacement can introduce a short window of 502;
investigate zero-downtime handoff separately.

Production after `70932fc`: Docker healthy, new bot image revision
and Mini App `revision.txt` match; `neuromixbot.com/mini-app/`,
`neuromixbot.com/login`, and `tanyapi.chillcreative.ru/health`
return HTTP 200; backend canonical Mini App and media origins remain
`neuromixbot.com`, webhook origin remains `tanyapi.chillcreative.ru`.

## Follow-up and operational priorities

1. Finish trend-preview CI, merge, and post-release video tile smoke
   for concurrent renders; watch `FileNotFoundError` rate fall to zero.
2. Add event-loop delay, PG pool wait/checked-out utilization, and
   request-ID latency correlation; reproduce the historical
   18:42–18:48 stall under controlled load before changing pool caps.
3. Inventory the 1,392 missing S3 keys against DB and backup/S3
   manifests; repair only verified durable objects; preserve old
   media until reconciled.
4. Diagnose Telegram's 25k terminal BadRequest outcomes without
   exposing personal data, and avoid unsafe broad campaign replays.
5. Release Lava #687 through protected CI and verify webhook
   response times plus exact-once account credits. Confirm any
   remaining unbound legacy orders manually against provider evidence.
6. Monitor automatic deploy downtime and separate legacy/other-vhost
   health signals from NEUROMIX metrics.

No payments, balances, stored media, provider credentials, or
production datasets were modified as part of this audit. The PR
contains only the scoped trend-preview race fix, regression tests,
and this evidence note.

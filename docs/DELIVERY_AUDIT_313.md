# Issue #313 — audit and bounded Telegram media delivery

## Production diagnosis (2026-10-15, read-only)

Repository: `Bambale0/banano_kling`, branch `tanyapi`.
Starting release: `b1ee0ce818a88ba63402206b9233ad03907faf57`.
The affected model is `motion_control_v26`, not the editorial trends catalog.

- Available logs for the newly restarted container: 5,434 lines, with 10 ERROR entries, all `Request Entity Too Large` from the same result; 10 video-URL fetch failures and watchdog replays.
- Production DB sample: latest 10,000 completed generation tasks updated in the previous 7 days. Delivery state: 9,747 `delivered`, 240 `unavailable`, 12 legacy/unset, 1 `pending`. That pending Motion Control 2.6 video already had 7,835 state transitions/attempt-count increments and `delivery_link_sent=true`.
- Separate warnings: 640 blocked campaign #29 sends, stored terminally as `blocked`; 4 rejected payment webhooks (3 Lava, 1 Prodamus); 1 unauthorized trend detail request. No evidence these are retry loops or security bypasses.

These are *bounded, observed samples*, not a claim to audit all historical logs.

## Exact failure chain

1. Provider successfully completes a paid video generation; `store_task_result_ready` preserves `status=completed` and the original result URL.
2. Telegram cannot fetch the video from the URL, so the bot downloads the original MP4 and tries uploading it.
3. Telegram rejects the upload with HTTP 413 / `Request Entity Too Large`.
4. The bot sends a result link but records `delivery_status=pending` anyway.
5. The watchdog selects the completed result for recovery and replays the same URL and oversized video indefinitely. The historical `delivery_attempts` counter increments both on lease claims and delivery-status writes, so it is not a count of distinct Telegram API uploads.

### Tight reproducible loop

`pytest -q tests/test_delivery_oversize_313.py`

Before the fix, all first three test cases failed because the actual delivery state remained `pending`, not terminal `link_only`/`uncertain`. The real KIE webhook handler is exercised with a fake Telegram and a local streaming download response. No paid calls or production modifications.

## Implemented behavior

- Add `link_only` as a terminal, partial-success delivery status for confirmed successful link sends. The provider-completed result is preserved; the original file remains downloadable and visible in Mini App.
- Recognize explicit Telegram/media 413 and `file too big`. Do not retry that video representation indefinitely.
- On explicit oversize without a confirmed link, mark `uncertain` for manual recovery without hiding or refunding a successfully generated result.
- Bound outstanding recovery to 20 *historical metadata transitions* (several actual attempts). On exhaustion, stop the lease/replay: `link_only` if the link was confirmed sent, otherwise `uncertain` for manual review.
- Status writes use optimistic CAS to prevent late callbacks from overwriting terminal delivery receipts.
- Preserve temporary-error retries (network/timeout/429), normal user notifications, and explicit terminal Telegram chat-unavailable handling.
- Do not re-run providers, trigger purchases, send duplicate links, or change prices.

## Tests and release criteria

- Original red-capable integration and DB tests now green, including duplicate webhook, historical 7,835-count recovery, low-budget transient retry, explicit size rejection, no-link manual review and immutability of terminal state.
- Existing delivery/webhook/watchdog/poller regression suite.
- Isolated PostgreSQL test covers completed result retention and terminal 413 state, and the existing PG concurrency tests run in CI.
- PR into `tanyapi`, all required checks and review green, native squash auto-merge, protected deployment.
- Post-release: verify Git/Docker/Mini App SHA, health, runtime pricing hash unchanged, PostgreSQL task converges to `link_only`, counter stops growing and no repeat `Request Entity Too Large` errors.

Future observability: periodically report aggregated `pending` and `uncertain` completed tasks, max retry attempts, link-only completions and new HTTP 413 events. A confirmed terminal `uncertain` without a link needs administrator investigation rather than silent retries.

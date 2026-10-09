# Referral event notifications

Referral attachment and the one-time accepted-generation bonus are independent
receipts. Existing financial eligibility, amounts, first-inviter rules, and
historical claims are unchanged.

The pending-invite insertion queues an `attached` event in its transaction;
the successful bonus grant queues a separate `bonus` event in its transaction.
Unique event keys prevent duplicate enrollment. Rolled-back transactions leave
no receipt. Newly granted old pending claims produce a current bonus receipt;
already granted claims and historical attachments are never backfilled.

`referral_notification_outbox` is created empty through existing idempotent
partner-policy initialization and the PostgreSQL schema. It stores frozen text,
recipient, delivery progress, fencing token, attempt count and Telegram receipt.
There are no changes to campaign audiences, support tickets, prices or balances.

A single guarded startup worker polls once per second, with no Telegram I/O in
request handlers or financial transactions. The existing frozen snapshot sender
persists intent before calling Telegram and receipts afterward. Concurrent workers
use conditional fenced claims; the bonus waits for an active attachment notice.

Explicit Telegram rate limits are retried after the returned delay, up to five
attempts. Blocked/invalid recipients become terminal. Timeout, 5xx, cancelled
in-flight send, or unknown delivery outcome is `uncertain`: it is not automatically
replayed. After restart, expired unstarted claims can retry and saved receipts can
finish without resending. Exactly-once Telegram delivery cannot be guaranteed.

Operators can inspect `status`, `last_error`, `attempts`, `delivery_parts`, and
`telegram_message_id` to reconcile uncertain/terminal records. Do not reset these
records or send historical messages without separate authorization. Normal logs
include `Referral notification sent/failed/blocked/terminal/uncertain` and event key;
`Referral notification worker failed` indicates a worker/storage problem.

Regression coverage uses mocked Bot API calls, SQLite transaction tests, and the
dedicated disposable PostgreSQL partner CI job. No live test recipients or paid
provider jobs are used.

## Managed runtime settings

Administrators can use `/referral_notifications_config` to download the current
JSON, `set JSON` (also via reply text or a JSON document) to save it, or `reset` to restore defaults.
The existing `bot_settings` registry records the last editor and update time;
it is not a separate immutable audit history. No live settings are changed by
this release. Startup additively upgrades legacy two-column registries with nullable audit columns, preserving values and unknown historical metadata. The key is `referral_notifications.config`.

Validated fields are `poll_seconds` (0.1–60), `batch_delay_seconds` (0.01–5),
`lease_seconds` (integer 61–900, strictly above the sender timeout), `max_attempts`
(integer 1–20), `attached_template`, and `bonus_template` (1–2000 characters).
Each template must contain `{identity}` and `{bonus}` only; attribute/index
access, conversion/spec syntax, invalid HTML and oversized rendered text are
rejected. Only formatting tags without attributes are supported; links are not
accepted in these receipt templates. Code/pre tags cannot overlap other formatting entities, including the formatted identity placeholder. Identity values are escaped, and saved text is immutable per event.
Unknown fields and nonfinite/bool numeric values are rejected. Malformed stored
configuration logs a sanitized warning and falls back to defaults instead of
rolling back referral accounting. Partial JSON uses defaults for omitted fields.

Future claims use current settings (worker reads use the existing five-second
cache); in-flight claims retain their captured lease and attempt limit. A known
`never_started` recipient remains queued without consuming attempts until the
existing private-chat lifecycle clears that state. Actual Telegram rejection
remains terminal: `/start` does not replay historical blocked/uncertain notices.
Recovery restores attempts from durable send intent rather than counting a
claim that crashed before starting a retry. No campaign audience or billing
behavior changes.

Lowering the retry limit terminalizes queued/failed records that already reached
the new budget before releasing dependent bonus notices. Raising the limit later
does not revive them or reverse attachment-before-bonus ordering.

The admin setter accepts a replied UTF-8 JSON document with verified declared
size and a streamed hard limit of 48000 bytes, a 10-second download deadline,
and a 12000-character decoded JSON cap. This permits reapplying full-size
templates that cannot fit in a single Telegram text message.

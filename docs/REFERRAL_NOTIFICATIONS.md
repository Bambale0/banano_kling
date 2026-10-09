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

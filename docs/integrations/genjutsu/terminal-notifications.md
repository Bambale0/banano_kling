# Genjutsu terminal notifications

Genjutsu sends one durable text notification when a run newly becomes failed,
canceled, or partially completed. Successful video delivery stays in the existing
`genjutsu_deliveries` path.

## Settlement and privacy

The terminal transition, any refunds, and insertion into `genjutsu_notifications`
are one repository transaction. The outbox primary key is `run_id`; repeated
terminal refreshes and concurrent cancellation cannot enqueue duplicate notices.
No finance mutation logic is changed.

The notification snapshot contains only coarse reason categories, terminal state,
step counts, and totals from `genjutsu_finance`. It never includes prompts, private
recipe data, provider responses, credentials, or media URLs. The message links to
the authenticated Studio run.

- Moderation: the provider returned `nsfw`; the exact trigger is not known
- Provider failure: upstream returned `failed` without a persisted detailed reason
- Technical failure: another terminal processing error
- Admin/free run with zero reserve: the message says that no bananas were charged
- Paid run: the message states the amount returned to the same banana balance and
  the net charge at terminal settlement
- Partial run: completed results remain available, with the run-level refund and
  net charge shown separately

A finance `capture` is settlement bookkeeping, not another user balance debit.
Amounts in the text are the snapshot at terminal settlement, rather than a claim
about later administrative adjustments.

## Safe delivery

The `genjutsu-notifications` worker starts after schema migration and is canceled
and awaited during application shutdown. Delivery status and attempts persist.

- Explicit Telegram rate limits are retried no earlier than `retry_after` and the
  configured polling interval
- Retries are bounded by `notification_max_attempts` (default 5, range 1–20) and
  `notification_retry_deadline_seconds` (default 3600, range 60–86400)
- These limits are saved with each notice; changes apply to new notices
- Known inaccessible chats or rejected messages become `unavailable`
- Transport uncertainty and expired sending leases become `delivery_unknown`
- `delivery_unknown` is never automatically replayed: Telegram may already have
  accepted the message

The local enqueue is idempotent. Exactly-once external Telegram delivery is not
claimed. Sending a notification never restarts generation or changes a balance.

## Managed notification copy

The authenticated admin settings form edits `notification_templates` through the
existing versioned `save_settings` action. There are eleven exact keys: `failed`,
`canceled`, `partial`, `moderation`, `provider_failure`, `technical_failure`,
`canceled_steps`, `no_charge`, `refund`, `charge`, and `details`.

Each nonempty plain-text template is limited to 300 UTF-16 code units, matching
browser input limits. Controls other than newline are rejected. The refund
message requires `{refunded_credits}` exactly once; the charge message requires
`{charged_credits}` exactly once. No other braces or placeholders are accepted.
Rendering uses literal replacement, not executable formatting or HTML parsing.

Copy is read from current validated settings at delivery time. Category selection
and amounts always come from the immutable terminal settlement snapshot. Editing
copy cannot alter the refund policy, ledger, or branch that selects the message.

## Rollout and rollback

The additive table/index migration is empty and contains no historical scan or
backfill. Already-terminal historical runs are not notified, even if refreshed or
canceled again. A previously active run that first reaches a terminal state after
rollout may create its normal new notification.

Existing saved settings receive the validated retry and notification-copy defaults when read; deployment
does not rewrite feature flags or enable public admission. Existing unused quotes
may require refreshing because validated settings fingerprints now include the
new fields. Already accepted generation work retains its pricing snapshot.

Rolling the application back leaves the additive table untouched and stops its
worker. Review pending notification rows before a subsequent rollout if their
relevance has changed; there is no automatic historical replay command.

## Verification

`tests/test_genjutsu_notifications.py` exercises synthetic SQLite settlement,
concurrency, downstream refunds, partial results, migration without backfill,
transaction rollback, retries, ambiguous acknowledgements, privacy-safe text,
Telegram error classification, and lifecycle shutdown. No real Telegram/provider
calls are made. `tests/test_genjutsu_postgres.py` additionally verifies the outbox
through the repository's actual PostgreSQL adapter in dedicated ephemeral CI.

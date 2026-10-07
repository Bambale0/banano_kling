# Internal Admin Notification Campaigns

## Endpoints

```text
POST /internal/admin/notifications/preview
GET  /internal/admin/notifications/campaigns
POST /internal/admin/notifications/campaigns
GET  /internal/admin/notifications/campaigns/{id}
POST /internal/admin/notifications/campaigns/{id}/test
POST /internal/admin/notifications/campaigns/{id}/start
POST /internal/admin/notifications/campaigns/{id}/cancel
```

Все запросы используют private-network allowlist и exact-body HMAC. Write-команды дополнительно требуют `Idempotency-Key`, `X-Admin-User-Id` и `X-Request-Id`.

## Segments

Поддерживаются строго типизированные сегменты:

- `all` — все незаблокированные пользователи;
- `paid` / `unpaid`;
- `recent` / `inactive` с `days`;
- `balance_gte` / `balance_lt` с `amount`;
- `explicit` с массивом до 1000 Telegram ID.

Произвольный SQL, WHERE или имя таблицы из административного payload не принимаются.

## Campaign flow

1. `preview` возвращает размер аудитории без создания кампании.
2. `POST /campaigns` создаёт draft после подтверждения `SAVE CAMPAIGN`.
3. `test` отправляет сообщение только указанному Telegram ID после `TEST {id}`.
4. `start` после `START {id}` один раз материализует аудиторию в `notification_deliveries`.
5. bot-owned worker отправляет сообщения, обновляет отчёт и завершает кампанию.
6. `cancel` после `CANCEL {id}` отменяет ещё не отправленные deliveries.

## Delivery safety

- `FOR UPDATE SKIP LOCKED` для конкурентного claim;
- lease на `sending`; подтверждённые части не повторяются, неизвестный результат требует сверки;
- экспоненциальный backoff и Telegram `retry_after`;
- максимум 5 попыток;
- blocked/deactivated chats учитываются отдельно;
- уникальность `(campaign_id, telegram_id)` исключает повторное создание строки получателя; она сама по себе не гарантирует exactly-once в Telegram;
- текст отправляется как plain text;
- кнопка разрешает только `https://` или `tg://`.

## Repeat button compatibility

Старые result keyboards использовали `repeat_result_*`, а безопасный repeat-flow слушает `repeat_image_*`. Compatibility router сохраняет работу уже отправленных сообщений и направляет оба callback-формата в один экран подтверждения.


## Telegram promo editor (schema v2)

The existing Telegram admin → Рассылка entry opens saved promo drafts and history.
Create a draft, enter text, add up to ten photos/videos, then add zero to two buttons.
Each button has a 1–64 character label and a server-searched existing published trend.
The selector uses the existing approved/public user_prompts model and trend tag.
It does not create duplicate availability flags or accept arbitrary URLs.

Buttons open the existing prompt deep link in the Mini App; the recipient sees the
selected trend and chooses the normal repeat action. No referral is attributed to an
administrator or another recipient by the broadcast link.

One photo/video carries its text and keyboard. Two or more files are sent as one
album, followed by a separate text message with vertical buttons. An album requires
promo text. Existing single-media messages without captions remain supported.
Telegram albums do not accept inline keyboards.

### Test and launch

«Тест на админах» queues this exact normalized snapshot to config.admin_ids. The same
worker and renderer deliver tests and broadcasts. At least one complete successful
delivery to a current admin enables final confirmation. The editor reports pending,
failed and uncertain targets. Delivery is not proof that a human clicked either link.

All newly composed Telegram promos, including those without buttons, require a
matching successful test. Changes to text, formatting, ordered media or buttons clear
the test. The final launch transaction rechecks the immutable payload, current bot
username/deep links, current admin receipt, trend availability and confirmed audience
count. Concurrent clicks materialize only one recipient set. Launched snapshots are
read-only; duplicate creates a fresh draft with no test authority.

The old Telegram confirmation safely reopens the editor. Legacy signed internal
campaign endpoints remain for their existing clients, but reject v2 promo test/start
requests so they cannot bypass the Telegram test gate. Previously queued historical
campaigns are not retroactively gated.

### Delivery and recovery

The existing PostgreSQL tables receive additive promo revision/snapshot/test fields and
per-part receipts. Startup DDL is serialized with a transaction advisory lock.
Each Telegram call is preceded by committed ownership-fenced intent and followed by
committed message IDs. Confirmed albums are skipped when retrying a subsequent text
part. Definite 429 failures respect retry_after. Forbidden/deactivated/missing chats
are terminal for that recipient. Unknown network acceptance, timeouts and 5xx responses
are recorded as uncertain; no blind retry can guarantee deduplication because Telegram
does not supply send idempotency keys. This deliberately favors avoiding duplicate
promos over automatic retry of an ambiguous 5xx response.

An expired in-flight part without a receipt requires reconciliation. A crash after
all receipts were persisted can complete without another Telegram call. Logs contain
IDs, hashes, part method, attempt, error category and timings, never promo text, media
contents, auth data or raw exception URLs.

### Deployment and rollback constraints

Deploy all notification workers on this version before enabling new promo creation.
Do not run old and new consumers together: older code cannot render v2 albums/buttons.
Do not roll code back while v2 campaigns are running. First freeze/drain their queued
work with an authorized operation and preserve receipts; then roll back. An additive
schema alone does not make the old consumer safe for v2 snapshots.

No real Telegram test or mass send is part of automated regression tests. The release
acceptance still requires a specifically approved admin-only test using safe content:
two videos, two published trends, actual button clicks, correct Mini App cards, edit
invalidation and post-deploy logs. Do not start a paid repeat to validate navigation.

### Verification

Default offline suite includes renderer and Telegram handler regressions. Real
PostgreSQL tests use tests/test_promo_campaigns_postgres.py only with explicit
PROMO_POSTGRES_TEST=1 and PARTNER_POSTGRES_TEST=1 on a guarded local test database.
The Runtime PostgreSQL Regression workflow creates a separate banano_promo_test
database and exercises migration, concurrent launch, test hash, partial delivery and
uncertain-recovery behavior without Telegram network calls.


### Database clock and reviewed edge cases

Lease and retry deadlines use PostgreSQL clock arithmetic, matching the session timezone
of the existing TIMESTAMP columns. UTC, Europe/London and Asia/Kolkata are covered by
real-adapter regression tests.

A recovered fenced claim with an empty part list is provably unsent: both current
senders persist intent before calling Telegram. It can reclaim its unused attempt
budget and retry. Historical unfenced empty claims and any unconfirmed in-flight part
remain uncertain and are never blindly replayed. A fifth in-flight test attempt still
counts as pending and cannot be replaced by another test run.

New promo revisions record campaign, revision, acting administrator, payload hash and
timestamp in the same transaction as the edit. No-op saves and stale rejected edits
do not add revision history.

Operational configuration review remains a separate improvement: request timeout and
lease retain their safe technical defaults (60 and 90 seconds with the invariant
timeout < lease). This release does not add dynamic runtime policy changes or weaken
the fencing guarantees.

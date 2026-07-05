# Payment Parameter Trace Map — banano_kling (Таня ТГ)

> Generated: 2026-07-04 | Scope: ALL payment flows end-to-end

---

## Flow 1: YooKassa Payment Flow

```
handlers/payments.py:initiate_payment()
  → yookassa_service.py:create_payment()
    → external YooKassa API
      → webhook → handlers/payments.py:handle_yookassa_webhook()
        → database.py:complete_payment_atomic()
```

### Flow 1 Parameter Trace Table

| Flow | Parameter | Created at | Expected by (next consumer) | Actually passed | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|------|-----------|-----------|---------------------------|-----------------|-------|----------------|---------------|-------------|--------------|
| YK | `amount_rub` | payments.py:445 — `float(package["price_rub"])` | yookassa_service.create_payment(amount_rub=float) | ✅ `amount_rub: float` → `f"{amount_rub:.2f}"` as string in API payload | No | **Yes** — float→formatted string in yookassa_service.py:52; correct for YK API but float precision risk | Low | None — YK API expects string `"%.2f"` | Yes |
| YK | `order_id` | payments.py:430 — `f"{callback.from_user.id}_{int(time.time()*1000)}_{package_id}"` | yookassa_service → metadata["order_id"] → webhook lookup | ✅ Passed as string to `create_payment(order_id=...)`, stored in `metadata["order_id"]`, later extracted from `payment.metadata` | No | No — string throughout | None | None | No |
| YK | `payment_id` (YK: PaymentId) | yookassa_service.py:72 — `payment.id` from YK SDK | handlers/payments.py:498 — stored in DB via `create_transaction(payment_id=invoice_id)` | ✅ `result["PaymentId"]` → `invoice_id` → `create_transaction(payment_id=invoice_id)` | No | No — string | None | None | Yes |
| YK | `payment_id` (webhook→DB lookup) | webhook payload `data["object"]["id"]` → `payment_id` | DB lookup: `WHERE payment_id = ? AND provider = 'yookassa'` | ✅ `payment_id` from webhook is matched against DB `transactions.payment_id` | No | No — string match | **Medium** — partial index `WHERE payment_id IS NOT NULL` but NULL webhook-id could bypass dedup | Consider tightening webhook validation for empty payment_id | Yes |
| YK | `notification_url` | config.py:223 — `{WEBHOOK_HOST}/yookassa/webhook` | yookassa_service.create_payment(notification_url=...) | ⚠️ `config.yookassa_notification_url` → passed as `notification_url` kwarg | No | No | **Low** — YK sends to this URL; validates via HMAC | None — HMAC validation present | Yes |
| YK | `user_id` (internal DB) | `get_or_create_user(callback.from_user.id)` → `user.id` → `create_transaction(user_id=user.id)` | complete_payment_atomic → `SELECT telegram_id FROM users WHERE id = txn_row["user_id"]` | ✅ `callback.from_user.id` (Telegram ID) → `user.id` (internal PK) → stored as `transactions.user_id` | No | **Yes** — `callback.from_user.id` is a Telegram ID (int), but it's first mapped through `get_or_create_user()` which creates/gets internal `users.id` (PK). The DB's `transactions.user_id` stores the **internal PK**, not the Telegram ID. This is correct but confusingly named. | Medium — variable naming: `user_id` in different contexts means different things (Telegram ID vs internal PK) | Rename internal PK references from `user_id` to `db_user_id` or add comments | No |
| YK | `telegram_id` | database.py:1927 — `int(user_row["telegram_id"])` from users table | `_notify_user(bot, telegram_id, ...)` | ✅ Resolved from DB as int | No | No | None | None | No |
| YK | `provider` | payments.py:386 — hardcoded `"yookassa"` | DB `transactions.provider` | ✅ Passed to `create_transaction(provider=provider)` → stored | No | No | None | None | No |
| YK | `status` (transaction) | payments.py:448 — hardcoded `"pending"` | complete_payment_atomic → checks `pending` → sets `processing` → `completed` | ✅ Status transitions: pending → processing → completed | No | No — strings are exact | **Low** — race between webhook and reconcile loop; protected by `status = 'pending'` WHERE clause | Already protected with atomic status transitions | Yes |
| YK | `status` (YK API) | yookassa_service.py:90 — `payment.status` from API | webhook handler: checked as `paid` flag or `status in ("succeeded","paid","captured")` | ✅ YK status string mapped to boolean `paid` flag | No | No — status strings use `.lower()` normalization | None | None | No |
| YK | `description` | payments.py:434 — `f"Покупка {total_credits} бананов ({package['name']})"` | yookassa_service → `description[:128]` | ✅ Truncated to 128 chars before API call | No | No | None | None | No |
| YK | `return_url` / `success_url` | payments.py:431 — `f"https://t.me/{bot_info.username}?start=success_{order_id}"` | yookassa_service.create_payment(return_url=success_url) | ✅ Passed as `confirmation.return_url` | No | No | None | None | No |

---

## Flow 2: CryptoBot Payment Flow

```
handlers/payments.py:initiate_payment()
  → cryptobot_service.py:create_invoice()
    → external Crypto Pay API
      → webhook → handlers/payments.py:handle_cryptobot_webhook()
        → database.py:complete_payment_atomic()
```

### Flow 2 Parameter Trace Table

| Flow | Parameter | Created at | Expected by (next consumer) | Actually passed | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|------|-----------|-----------|---------------------------|-----------------|-------|----------------|---------------|-------------|--------------|
| CB | `amount_rub` | payments.py:445 — `float(package["price_rub"])` | cryptobot_service.create_invoice(amount_rub=float) | ✅ `amount_rub: float` → `f"{amount_rub:.2f}"` as string in API payload `"amount": "%.2f"` | No | **Yes** — float→formatted string; low risk | Low | None | No |
| CB | `order_id` | payments.py:430 | cryptobot_service → `"payload": order_id` → webhook `invoice["payload"]` | ✅ `order_id` is sent as `payload` field | No | No | None | None | No |
| CB | `payment_id` (CB: invoice_id) | cryptobot_service.py:79 — `str(invoice.get("invoice_id"))` | handlers/payments.py:499 — `create_transaction(payment_id=invoice_id)` | ✅ `invoice_id` → stored as `transactions.payment_id` | No | No — string | None | None | Yes |
| CB | `payment_id` (webhook→DB lookup) | webhook `invoice["invoice_id"]` or `invoice["id"]` | `get_transaction_by_order(order_id)` → checks `str(transaction.payment_id) != invoice_id` | ⚠️ Webhook matches by `order_id` first, then verifies `payment_id` matches. If mismatch → logged and returns 200 (no error). | No — logged but silently skipped | No — strings | **Medium** — invoice_id mismatch silently returns 200; attacker could replay webhook with different invoice_id but same order_id. Would be caught by `complete_payment_atomic` idempotency anyway | Add explicit alerting for invoice_id mismatch (currently just `logger.warning`) | No |
| CB | `signature` | webhook header `crypto-pay-api-signature` | cryptobot_service.verify_webhook_signature(raw_body, signature) | ✅ SHA256 HMAC with API token as key | No | No — bytes | **None** — standard HMAC verification | None | No |
| CB | `update_type` | webhook `data["update_type"]` | checked: must be `"invoice_paid"` | ✅ Only processes `invoice_paid` events | No | No — string exact match | None | None | No |
| CB | `user_id` (internal DB) | Same as YK: `get_or_create_user()` → `user.id` → `create_transaction(user_id=user.id)` | Webhook: `get_telegram_id_by_user_id(transaction.user_id)` | ✅ Internal PK stored in transactions.user_id | No | Same naming confusion as YK flow | Medium — same `user_id` naming issue | Same as YK flow | No |
| CB | `telegram_id` | Webhook: `get_telegram_id_by_user_id(transaction.user_id)` → int | `_notify_user(bot, telegram_id, ...)` | ✅ Resolved from DB | No | No | None | None | No |
| CB | `description` | payments.py:434 | cryptobot_service → `description[:1024]` | ✅ Truncated to 1024 chars (vs 128 for YK) | No | No | None | None | No |
| CB | `paid_btn_url` | payments.py:431 — `success_url` | cryptobot_service → `"paid_btn_name": "openBot"`, `"paid_btn_url": paid_btn_url` | ✅ | No | No | None | None | No |
| CB | `provider` | payments.py:386 — hardcoded `"cryptobot"` | DB `transactions.provider` — also accepts `"cryptopay"` as alias | ⚠️ `initiate_payment` checks `provider in ("cryptobot", "cryptopay")` but always stores `"cryptobot"` | No — aliasing handled at entry point | No | **Low** — DB may have `"cryptopay"` from old code; `_resolve_payment_state` normalizes: `provider.lower()` | None — normalization handles it | No |
| CB | `currency` | cryptobot_service.py:65 — `"fiat": "RUB"`, `"currency_type": "fiat"` | CryptoBot API | ✅ Hardcoded RUB | No | No | None | None | No |
| CB | `status` (CB API → DB) | Webhook: `invoice["status"] == "paid"` | complete_payment_atomic → pending→processing→completed | ✅ | No | No | **Low** — Cleanup job (`cleanup_stale_cryptobot_pending`) also reads CB status and may race with webhook; both use `complete_payment_atomic` which is idempotent | Already safe due to idempotent atomic completion | No |

---

## Flow 3: Lava Payment Flow

```
handlers/payments.py:initiate_payment()
  → lava_service.py:create_invoice()
    → external Lava.top API
      → webhook → handlers/payments.py:handle_lava_webhook()
        → database.py:complete_payment_atomic()
```

### Flow 3 Parameter Trace Table

| Flow | Parameter | Created at | Expected by (next consumer) | Actually passed | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|------|-----------|-----------|---------------------------|-----------------|-------|----------------|---------------|-------------|--------------|
| LV | `offer_id` | config.lava_offer_id_for_package(package_id) | lava_service.create_invoice(offer_id=offer_id) | ✅ | No | No | None | None | No |
| LV | `currency` | payments.py:471 — `"USD"` hardcoded | lava_service → `"currency": "USD"` | ✅ Hardcoded USD (NOT RUB like other providers) | No | No | **Medium** — Lava uses USD while YK/CB use RUB. Package `price_rub` is in RUB but Lava offer may have its own pricing. No currency conversion is applied. | Verify that Lava offers are correctly priced in USD; add documentation | Yes |
| LV | `email` | config.LAVA_DEFAULT_EMAIL | lava_service → `"email": email` | ✅ | No | No | None | None | No |
| LV | `client_utm` (metadata) | payments.py:473 — `{"telegram_id": str(...), "order_id": ..., "package_id": ...}` | lava_service → `"clientUtm": client_utm` — sent to Lava API, NOT used in webhook lookup | ⚠️ `order_id` is in clientUtm but Lava webhook doesn't use it directly. Webhook resolves by `contract_id` or recursive `order_id` search. | **Yes** — clientUtm is NOT the primary lookup key for the webhook | No — dict → API JSON | Low | Document that clientUtm is for Lava-internal analytics only; webhook uses contract_id | No |
| LV | `payment_id` (LV: contract_id / invoice_id) | lava_service.extract_invoice_id(result) — tries `id`, `data.id`, `result.id` | `create_transaction(payment_id=invoice_id)` → stored in DB | ✅ Extracted via multi-key fallback | No | No — string | **Medium** — Multiple possible keys for invoice_id extraction; if Lava API response format changes silently, invoice_id could be None | Add explicit logging when extract_invoice_id returns None | No |
| LV | `order_id` (webhook→DB lookup) | Webhook body: recursive `_extract_first(data, ("order_id", "orderId"))` | `get_transaction_by_order(str(order_id))` | ⚠️ Multiple resolution paths: 1) direct order_id from webhook, 2) fallback: `WHERE payment_id = contract_id AND provider = 'lava'` | **Yes** — direct order_id may not be present (uses fallback) | No — str | None — fallback is robust | None | No |
| LV | `contract_id` (webhook) | lava_service.webhook_contract_id(data) — `contractId`, `contract_id`, `invoiceId`, `invoice_id` | Used as payment_id for DB lookup when order_id is absent | ✅ Multi-key extraction | No | No — string | None | None | No |
| LV | `signature` (HMAC) | webhook `data["signature"]` | config.LAVA_WEBHOOK_SECRET → HMAC-SHA256 verification | ✅ HMAC check when LAVA_WEBHOOK_SECRET is set | **Yes** — HMAC check is optional (only when configured). If LAVA_WEBHOOK_SECRET is empty, webhooks are accepted without signature validation! | No | **HIGH** — Without LAVA_WEBHOOK_SECRET, any caller can POST to `/lava/webhook` and trigger payment completion | **CRITICAL: Enforce HMAC validation; make it mandatory.** | Yes |
| LV | `event_type` | lava_service.webhook_event_type(data) | `is_success_webhook()` / `is_failed_webhook()` | ✅ Checks `eventType == "payment.success"` OR status-based detection | No | No | **Medium** — Fallback to status-based detection (not just event_type). Could interpret non-payment webhooks incorrectly. | Add a whitelist of known event types and reject unrecognized ones | No |
| LV | `provider_status` (Lava API) | `_resolve_lava_provider_status()` — calls `lava_service.get_invoice(payment_id)` | Webhook: must be `"completed"` before processing success webhook | ⚠️ Makes an extra API call to verify status even after receiving a webhook. Rate limit and latency risk. | No | No | Low — extra validation is good but adds latency | None — defensive check is reasonable | No |
| LV | `user_id` / `telegram_id` | Same pattern as YK/CB | Same resolution as YK/CB | ✅ | No | Same naming issue | Medium — same `user_id` naming issue | Same as YK | No |

---

## Flow 4: Telegram Stars Payment Flow

```
handlers/payments.py:initiate_payment()  [provider == TELEGRAM_STARS_PROVIDER]
  → answer_invoice() (Telegram native)
    → pre_checkout_query → process_successful_stars_payment()
      → database.py:complete_payment_atomic()
```

### Flow 4 Parameter Trace Table

| Flow | Parameter | Created at | Expected by (next consumer) | Actually passed | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|------|-----------|-----------|---------------------------|-----------------|-------|----------------|---------------|-------------|--------------|
| TS | `stars_amount` | payment_utils.py:20-27 — `package_stars_amount(package)` | Pre-checkout: `query.total_amount` must equal `stars_amount` | ✅ `package_stars_amount()` → `invoice_payload` → parsed back → compared | No | **Yes** — `int` in payload, returned as `int` from parse, compared with `query.total_amount` (int). OK. | None | None | No |
| TS | `invoice_payload` | payment_utils.py:31 — `f"stars:{order_id}:{stars_amount}"` | Pre-checkout: `parse_stars_invoice_payload(query.invoice_payload)` | ✅ Serialized as string, parsed back to (order_id, stars_amount) tuple | No | No | **Low** — Payload is not cryptographically signed; Telegram guarantees integrity | None — Telegram guarantees payload integrity | No |
| TS | `currency` | payment_utils.py:8 — `"XTR"` | Pre-checkout: `query.currency != TELEGRAM_STARS_CURRENCY` check | ✅ Hardcoded XTR, compared with `!=` | No | No — string exact match | None | None | No |
| TS | `user_id` verification | Pre-checkout: `get_telegram_id_by_user_id(transaction.user_id)` vs `query.from_user.id` | Must match — rejects if different user tries to pay | ✅ Telegram-native check: invoice can't be paid by different user anyway, but explicit check adds defense | No | No | None — good defense in depth | None | No |
| TS | `charge_id` | `payment.telegram_payment_charge_id` | `update_transaction_payment_id(order_id, charge_id)` | ✅ Replaces the placeholder `pending:{stars_amount}` with real charge_id | No | No — string | None | None | No |
| TS | `payment_id` (initial) | payments.py:442 — `f"pending:{stars_amount}"` | Placeholder until real charge_id arrives | ⚠️ Placeholder string `"pending:{stars_amount}"` used before real charge_id. If DB lookup happens before update, could cause confusion | No | No | **Low** — only exists briefly between invoice creation and payment completion | None | No |

---

## Flow 5: Balance Operations (credits add/deduct)

```
database.py:add_credits(telegram_id, amount)
database.py:deduct_credits(telegram_id, amount, check_balance=True)
  ← called from: complete_payment_atomic (add), handlers/generation.py (deduct), main.py webhook failures (add for refunds)
```

### Flow 5 Parameter Trace Table

| Flow | Parameter | Created at | Expected by (next consumer) | Actually passed | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|------|-----------|-----------|---------------------------|-----------------|-------|----------------|---------------|-------------|--------------|
| BAL | `telegram_id` (add_credits) | Passed from caller; resolved via `get_or_create_user()` | `UPDATE users SET credits = credits + ? WHERE telegram_id = ?` | ✅ int → DB query parameter | No | No | None | None | No |
| BAL | `telegram_id` (deduct_credits) | Passed from caller | `UPDATE users SET credits = credits - ? WHERE telegram_id = ?` | ✅ int → DB query parameter | No | No | None | None | No |
| BAL | `amount` type (add_credits) | `add_credits(telegram_id: int, amount: float)` — function signature expects float | `UPDATE users SET credits = credits + ?` → SQL REAL column | ⚠️ Signature says `float`, but `credits` field in DB is `INTEGER DEFAULT 0` (see line ~543) | No | **Yes — CRITICAL** — DB schema says `credits INTEGER`, but `add_credits` adds float. The DB field `credits` was originally INTEGER. If a fractional amount is passed, SQLite will silently coerce! Already using `Credits(float)` class for display | **HIGH — DB type mismatch** | Either change DB column to REAL or enforce int in add_credits; inconsistency | Yes |
| BAL | `amount` type (deduct_credits) | `deduct_credits(telegram_id: int, amount: float)` | `UPDATE users SET credits = credits - ?` | Same float vs INTEGER issue | No | **Yes — same as add_credits** | High — same issue | Same fix as above | Yes |
| BAL | `check_balance` (deduct_credits) | Caller sets `True` (default) or `False` | `BEGIN IMMEDIATE` → check balance → deduct | ✅ If `True`: uses `WHERE credits >= ?` guard. If `False`: no guard. | No | No — bool | **Medium** — `check_balance=False` skips the guard. Used in some webhook failure refund paths. If misused, could allow negative balances. | Audit all callers of `deduct_credits(check_balance=False)` | Yes |
| BAL | `amount` type (complete_payment_atomic) | `transaction.credits` — int from DB | `UPDATE users SET credits = credits + ?` | ✅ `transaction.credits` is INT from DB (see dataclass `Transaction.credits: int`) | No | No — int | None | None | No |
| BAL | `config.is_admin()` bypass | deduct_credits:130 — `if config.is_admin(telegram_id): return True` | No deduction for admins | ✅ Admin check at top of deduct_credits | No | No | **Low** — Admins bypass credit checks but this is intentional | None | No |
| BAL | `amount` (credits) in Transaction dataclass | database.py:111 — `credits: int` | but `create_transaction(credits: int, ...)` accepts `int` | ⚠️ `total_credits` passed from payments.py (computed as `int(total_package_credits(...))`) is int. Good. | No | No — int consistency | None | None | No |
| BAL | `amount_rub` in Transaction | database.py:112 — `amount_rub: float` | complete_payment_atomic → referral calculations use `float(transaction.amount_rub)` | ✅ Consistent float | No | No | None | None | No |

---

## Cross-Cutting Concerns: Parameter Name Conflicts & Inconsistencies

| Parameter Name | Used As... | In File(s) | Confusion Risk |
|---------------|------------|-----------|----------------|
| `user_id` | Internal DB PK (`users.id`) | database.py:create_transaction, complete_payment_atomic, get_telegram_id_by_user_id | **HIGH** — Same name used for Telegram ID (int from callback.from_user.id) and internal PK (int from users.id). `transactions.user_id` is internal PK. `get_or_create_user(telegram_id)` maps Telegram ID → internal PK. |
| `telegram_id` | Telegram user ID | database.py:add_credits, deduct_credits, get_or_create_user, _notify_user | Consistent — always Telegram ID |
| `payment_id` | Provider-specific invoice/contract/payment ID | payments.py, all services, DB `transactions.payment_id` | **Medium** — Same column stores YK PaymentId, CB invoice_id, LV contract_id, Stars charge_id. Lookups must always include `provider` filter. DB has unique index `(payment_id, provider)` |
| `invoice_id` | CB/LV-specific payment identifier | cryptobot_service.py, lava_service.py, payments.py (local variable) | **Medium** — Local variable `invoice_id` in payments.py maps to DB `payment_id` column. Naming inconsistency between local var and DB column. |
| `order_id` | Our internal order identifier | All files — consistent | None — Always string, always our internal ID |
| `amount` | float / int / str / Decimal — varies by context | See type mismatch table below | **HIGH** — None |
| `status` | String: "pending", "processing", "completed", "failed", "paid", "succeeded", "captured", etc | DB transactions.status uses our internal set; provider APIs use their own sets | **Medium** — Mapping is done manually with `.lower()` and set membership checks. If provider adds a new status, it may be missed. |

---

## Type Mismatch Summary

| Parameter | Where | Type A | Type B | Impact |
|-----------|-------|--------|--------|--------|
| `credits` (user balance) | database.py:add_credits signature | `float` (param type) | `INTEGER` (DB column) | SQLite silently coerces; no crash but semantic wrong |
| `credits` (Transaction dataclass) | database.py:Transaction.credits | `int` (dataclass field) | Same as DB transactions.credits INTEGER | Consistent |
| `amount_rub` | All service create_* methods | `float` (Python) | `str` formatted `"%.2f"` (API JSON) | Correct for external APIs |
| `amount` (Lava) | lava_service.create_invoice | `Optional[float]` | Not always sent (optional) | When not sent, Lava uses offer's default price |
| `telegram_id` vs `user_id` | Various DB functions | `int` both, but different semantics | Internal PK vs Telegram ID | Naming confusion, not runtime bug |

---

## Security Risk Summary

| Risk | Severity | Location | Detail |
|------|----------|----------|--------|
| Lava webhook HMAC optional | **HIGH** | lava_webhook handler | If `LAVA_WEBHOOK_SECRET` is not set, webhooks are accepted without any authentication. Any caller can trigger payment completion. |
| DB credits INTEGER vs float | **HIGH** | database.py add_credits/deduct_credits | DB column is INTEGER but functions accept float. Silent coercion risk. |
| `user_id` naming ambiguity | **Medium** | All payment flows | Same variable name for two different entities (Telegram ID vs internal PK) |
| Lava currency mismatch | **Medium** | lava_service.py vs other services | Lava uses USD, others use RUB. No conversion. |
| CB webhook invoice_id mismatch silently ignores | **Medium** | handle_cryptobot_webhook | Returns 200 on mismatch — logs but doesn't alert |
| YK webhook payment_id resolve gap | **Medium** | handle_yookassa_webhook | Multiple fallback paths for order_id resolution |
| Deduct credits without balance check | **Medium** | deduct_credits(check_balance=False) | If misused, allows negative balances |
| Lava event_type no whitelist | **Medium** | is_success_webhook / is_failed_webhook | Status-based detection could be triggered by non‑payment events |
| Multiple provider status sets | **Low** | All webhooks | Each provider has different status strings; mapping is done manually |

---

## Recommended Actions (Priority Order)

1. **CRITICAL**: Make Lava webhook HMAC validation mandatory — fail if `LAVA_WEBHOOK_SECRET` is not set
2. **HIGH**: Fix DB schema: either change `credits` to REAL or enforce int-only in add_credits/deduct_credits
3. **HIGH**: Document/verify Lava USD pricing — ensure offers match expected amounts
4. **MEDIUM**: Add consistent naming convention: `db_user_id` for internal PK, `telegram_id` for Telegram ID
5. **MEDIUM**: Add alerting for CB webhook invoice_id mismatch
6. **MEDIUM**: Audit all `deduct_credits(check_balance=False)` call sites
7. **LOW**: Add Lava event_type whitelist validation
8. **LOW**: Add tests for all parameter edge cases (empty payment_id, missing order_id in webhook, etc.)

---

## Test Coverage Gaps

| Test Scenario | Flow | Why Needed |
|--------------|------|------------|
| Float → INTEGER credit coercion | BAL | Verify no silent truncation |
| Lava webhook without HMAC secret | LV | Verify rejection |
| CB webhook with mismatched invoice_id | CB | Verify idempotent behavior |
| YK webhook with missing metadata | YK | Verify fallback DB lookup works |
| Stars pre-checkout with mismatched user | TS | Verify rejection |
| Race: webhook + reconcile loop on same order | ALL | Verify `complete_payment_atomic` idempotency |
| payment_id IS NULL lookup | YK/CB/LV | Verify unique index doesn't silently skip |
| Lava USD vs RUB amount mismatch | LV | Verify amounts are correct |
| Dual webhook delivery (same payment, same provider) | ALL | Verify no double credit |

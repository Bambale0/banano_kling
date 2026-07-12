# Trace Map: Payments

## 1. Supported payment surfaces

### Telegram bot

- package selection callbacks in `bot/handlers/payments.py`
- promo code input
- Telegram Stars pre-checkout + successful payment events

### Mini App

- `POST /mini-app/api/create-payment`

### Providers

- `CryptoBot`
- `Lava`
- `YooKassa`
- `Telegram Stars`
- legacy `T-Bank`

## 2. Core payment flow

`user selects package`
-> package resolved from `data/price.json`
-> transaction created in `transactions`
-> provider-specific invoice/session created
-> pending transaction stored with provider metadata
-> user completes payment externally
-> webhook or reconciliation confirms result
-> idempotent completion
-> credits added
-> referral/partner side effects
-> UI notification / balance refresh

## 3. Provider completion map

### CryptoBot

`/cryptobot/webhook`
-> signature validation
-> invoice/order correlation
-> duplicate completion guard
-> `_complete_transaction`

### Lava

`/lava/webhook`
-> JSON parse
-> HMAC validation
-> provider status verification
-> success/failure branch
-> duplicate completion guard
-> `_complete_transaction`

### YooKassa

- `/yookassa/webhook`
- `/webhook/yookassa`

Flow:

-> optional signature verification
-> payment id extraction
-> order resolution
-> duplicate completion guard
-> `_complete_transaction`

### Telegram Stars

`pre_checkout_query` / `successful_payment`
-> payload parsing
-> order resolution
-> transaction completion

## 4. Reconciliation loops

### YooKassa reconcile

Background loop in `bot/main.py`:

- polls pending transactions
- resolves late confirmations
- logs tick summary

### Lava reconcile

Background loop in `bot/main.py`:

- rechecks provider state for pending Lava payments
- closes stale pendings safely

## 5. Promo/referral side effects

On successful completion system may:

- apply promo bonus credits
- set `has_paid`
- trigger referral purchase logic
- update partner totals/balance

## 6. Main DB tables

- `transactions`
- `users`
- `promo_codes`
- `promo_redemptions`
- `referrals`
- `partner_withdrawals`

## 7. Invariants

- same order must not complete twice
- provider webhook retry must be safe
- balance increment must happen only after verified completion
- failed payment must not unlock credits
- provider/order correlation must survive delayed callback

## 8. Operational watchpoints

- provider secret not configured
- provider sends status before backend sees transaction
- payment already completed via webhook before reconcile loop
- stale pending rows not cleaned

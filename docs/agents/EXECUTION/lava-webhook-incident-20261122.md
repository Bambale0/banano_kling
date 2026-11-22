# Lava webhook incident and fast-path verification — 2026-11-22

## Scope and evidence

Production `tanyapi` at `d040127255a1a9481368a5e2c15283284bc58417`.
After a PostgreSQL-blocking incident, Lava deliveries had been rejected with HTTP 403: `LAVA_WEBHOOK_ALLOWED_IPS` did not contain the observed source `45.89.26.129`, and no `LAVA_WEBHOOK_SECRET` or Basic credentials were configured. The documented Lava egress IP is different, so this source's provenance must still be confirmed via the merchant's webhook history and provider support.

Emergency production **configuration only** (not committed): extended the IP allowlist with the observed source and recreated only the bot container using the existing image. A legitimate `payment.failed` webhook then received HTTP 200; the server independently verified `failed` via authenticated Lava API and did not change a final payment.

That real callback required **10,597.5 ms**, exceeding Lava's documented 10-second acknowledgement budget. The handler currently resolves a missing `contractId → invoiceId` mapping by scanning paginated account invoices before trying direct `GET /api/v2/invoices/{payment_id}`. Production direct GET for pending payment IDs is valid, approximately 0.7 seconds, and all 47 legacy pending transactions lack cached binding.

## Minimal code fix

- **Active production path:** `bot/handlers/__init__.py` installs `lava_invoice_compat._provider_status_compatible`, replacing the base safety helper. The incident was reproduced on that active method with a failing test before the fix.
- `bot/services/lava_invoice_compat.py::_provider_status_compatible`: prefer direct provider GET using the existing stored payment/invoice ID; invoke the receipt-verified account catalog only after all direct lookups returned 404, at most once across retries.
- `bot/services/lava_payment_safety.py::_provider_status`: apply the equivalent direct lookup before expensive legacy discovery to preserve the standalone safety path.
- Preserve existing amount/currency checks, provider outage fail-closed behavior and atomic/idempotent settlement.
- `tests/test_lava_webhook_fastpath.py`: nine focused regression cases cover both the safety helper and the installed compatibility handler.

## Verification

- Read-only Lava API probe: 47 pending transactions, all `in_progress` at audit time; **no credit or status mutation**.
- Production Docker restarted on existing SHA and reported `running/healthy`; Telegram webhook continued receiving HTTP 200.
- New real Lava failed-payment callback reached provider-status verification and HTTP 200, but took >10 seconds *before this code fix*.
- The legacy helper passed five isolated async scenarios. The actual installed compatibility handler reproduced a failing pre-fix test, then passed five isolated async scenarios on the patched function. Full repository CI and deployed-latency verification are still required. Full repository CI and post-deploy timing still required.
- No external paid invoice was created for testing.
- The unrelated 12 web-payment orders stranded at `creating` with no invoice binding have **not** been replayed.

## Release and security gates

1. Protected four-gate CI, code review, native squash auto-merge to `tanyapi`, exact-SHA production autodeploy.
2. Observe real Lava webhook HTTP 200 under 10 seconds, retry and idempotency, Telegram /start, DB lock waiters.
3. Configure the separate webhook `X-Api-Key` in the Lava merchant dashboard and `LAVA_WEBHOOK_SECRET` on the server **with the same value**. This is distinct from the outbound merchant `LAVA_API_KEY`. Once verified, remove any unconfirmed source IP from the fallback allowlist.
4. Investigate web `creating` orders without generating duplicate invoices or granting credits absent provider proof.

No secrets, user identifiers, production dumps, balance writes, prices, providers or unrelated models changed.

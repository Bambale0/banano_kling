# Lava invoice-list fallback — 2026-11-19

- Production branch: `tanyapi`, baseline after #629: `13e926870e1df356d0e1ab3f3fb68c318f3002fa`.
- Work item: #533 / PR #628. Normal PR → four protected CI gates → CI deploy, no manual payment settlement.
- User-visible intent: verified paid invoices are eventually credited once, despite Lava detail endpoint returning 404; unpaid invoices never credited merely from a webhook claim.
- Diagnosis: vendor detail GET returned 404 for some invoice UUIDs that were available in listing GET. Provider list contains `COMPLETED`, `FAILED`, and `IN_PROGRESS` even with `invoiceStatuses=IN_PROGRESS`, observed read-only 2026-11-19. `contractId` differs from `invoiceId` on certain webhook events.
- Provider data check (read-only): 75 local pending Lava rows; 46 matched exact provider invoice IDs in the recent listing, all 46 `IN_PROGRESS` and passing amount/currency validation; 29 not found in this bounded recent listing, not classified as unpaid. No customer/payment identifiers exported.
- RED reproduction after merge of #629: when a completed invoice came from listing and webhook contract differed, status was `completed` but resolved invoice ID was `None` (regression test).
- GREEN: preserve the identifier that actually resolved the invoice; save correct contract→invoice mapping. This keeps #629's contract-ID poisoning protection.
- Availability: listing pagination bounded by max pages and a cumulative vendor-request deadline (`LAVA_INVOICE_LIST_TIMEOUT_SECONDS`, default 30); outage triggers retryable provider-unavailable, not false completion.
- Backward compatibility: legacy contract-only invoices continue to use existing detail/list discovery; no schema changes, price changes, payment method priority changes, webhook auth changes, or manual credit/refund actions.
- Atomic settlement and webhook replay rules: unchanged. Missing data, nonmatching receipt, provider 404/outage fail closed; only independently verified completion can call atomic settlement.
- Acceptance tests: list success/pending/failure, receipt mismatch, 404 fallback, contract mapping, provider timeout, repeated webhooks, checkout and Mini App payment handling. Record exact results on PR.
- Deployment: GitHub protected squash merge into `tanyapi`, image rebuild/auto-deploy, verify SHA, container health, /health, webhook 2xx/503 ratio and read-only payment reconciliation.
- Rollback: revert release SHA through protected workflow; no changes to historical financial records without explicit approval.
- Outstanding: classify unmatched/old pending from authoritative provider reports under #533; never classify 404 alone as failed and never grant credit on guesswork.

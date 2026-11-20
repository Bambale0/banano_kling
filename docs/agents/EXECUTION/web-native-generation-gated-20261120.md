# Website-native generation pipeline: gated backend release

Date: 2026-11-20. Base: tanyapi cd1db0359bc019fc2ead72a3cc1789446ece9822. Target is independent web-only accounts. Complements #658; does NOT migrate existing Telegram balances.

## Runtime contracts
- Revocable HttpOnly browser session resolves one shared account ID. Browser never supplies a Telegram ID or account ID to charge.
- Linked Telegram/VK accounts are rejected with FINANCIAL_CUTOVER_REQUIRED at create/quote and, independently, at the central atomic reservation seam. Gemini Omni asset creation uses the same fence.
- New paid creation is permitted only if BOTH WEB_NATIVE_GENERATION_ENABLED and WEB_NATIVE_PAYMENTS_ENABLED are explicitly enabled AND KIE API access plus durable Selectel S3 storage are configured.
- With flags OFF, no new paid jobs or new invoices are accepted. Already pending reserved jobs are still processed and settled by the worker if provider access is available. Worker checks table existence read-only before any DDL.
- Existing legacy Telegram generation and payment code paths stay unchanged; Google/email provider login still depends on separate server config.
- Model prices derive from existing current provider tariffs, not hardcoded retail values; supported models with audited adapters are marked available by the browser model catalog. Unsupported generation models stay visible as disabled (including Seedance 2.5 until its web-specific billing adapter is audited).
- Browser uploads reference only verified, account-owned S3 IDs. Never feed arbitrary user URLs into a provider request. Link imports have SSRF checks.
- Wallet reserve is atomic with task insert, locked by the canonical shared account and protected with an idempotent request key. Provider POST outside DB is never blindly retried on an uncertain create response. Owner-scoped task CAS/leases guard parallel workers.
- Confirmed results are downloaded with bounded HTTPS, validated public DNS and file signatures, persisted to S3, then the matching reservation is captured; failed tasks release exactly the reservation. Crashes recover through stable journal keys and task phase.
- Callback signature only wakes up polling; callback payload cannot create credits, bypass provider status verification or insert a result link. Audio ID/Character ID creation uses a single provider CREATE attempt; existing Telegram callers keep their existing retry policy.
- New account-native history and detail use /web-auth/web-generation/history and /web-auth/web-generation/task/{task_id}, separate from existing linked Telegram read-only history endpoints.

## TDD and test evidence
- RED: mixed account create/adapter gates, direct wallet reserve and Gemini Omni bypass all failed. GREEN: six guards.
- RED: new provider code used a retry_transient kwarg unsupported by Gemini Omni and old independent-history paths conflicted with the live linked-history API. GREEN: compatibility argument with default true for TG, explicit false for web; tests use independent web task paths.
- Offline production-image Docker, no production credentials or network: 115 passed, including transactional balance reserve/capture/release, media references/S3 archive, multimodel adapter checks, price verification and race/duplicate cases.
- Python compileall, Ruff I/F and git diff --check on modified/new code passed.
- Production live payment, live provider integration, full repository tests and real user acceptance MUST be verified separately before flags are enabled.

## Release sequencing, blockers and recovery
1. CI on exact commit, production image and frontend revisions, /health, unauthorized auth 401.
2. No real new paid web use while flags are OFF; smoke admin/test account in a separately approved controlled environment.
3. Do NOT switch existing Telegram users. Historical legacy users.credits float ledger remains authoritative; 854 precision-review balances, pending-status transaction rows, six nonterminal generation tasks, unverified writer fences, immutable opening claims and event watermark are cutover blockers.
4. Follow-up frontend adds web payment/generation controls and explicit owner-scoped task history, but cannot imply a merged wallet.
5. If a later activation needs rollback, disable both new-purchase flags, keep worker reconciler running for existing tasks and checkout reconciler running for paid invoices; preserve ledger, S3 results and task rows, never bulk-delete or double-credit.

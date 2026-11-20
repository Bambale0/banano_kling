# NEUROMIX browser-native paid flow — 2026-11-20

Production target: tanyapi. Source PR #646. Keep draft until real payment/generation smoke is verified.

## Feature flags
- WEB_NATIVE_PAYMENTS_ENABLED=0 default; turn on only after verifying Lava invoice contract.
- WEB_NATIVE_GENERATION_ENABLED=0 default; turn on only after confirming KIE tasks and S3 delivery.
- WEB_GENERATION_CALLBACK_SECRET: recommended dedicated server secret; BOT_TOKEN fallback, not exposed directly.
- WEB_GENERATION_RESULT_HOSTS: default kie.ai,aiquickdraw.com,redpandaai.co,rendergrid.io
- WEB_GENERATION_MAX_REFERENCES: default 10, configurable up to 12; provider caps enforced.
- WEB_GENERATION_REFERENCE_MAX_BYTES: default 16777216
- WEB_GENERATION_REFERENCE_UPLOADS_PER_DAY: default 100
- WEB_GENERATION_MAX_IMAGE_BYTES: default 41943040
- WEB_GENERATION_MAX_VIDEO_BYTES: default 419430400
- WEB_GENERATION_MAX_PENDING_TASKS: default 5
- WEB_PAYMENT_MAX_NEW_INVOICES_PER_HOUR: default 12
- WEB_GENERATION_TASK_DEADLINE_SECONDS: default 7200
- WEB_GENERATION_WORKER_INTERVAL_SECONDS: default 8
- WEB_GENERATION_PROVIDER_SUBMIT_TIMEOUT_SECONDS: default 240
- WEB_GENERATION_RETRY_SECONDS: default 30

Existing LAVA_*, KIE_AI_API_KEY, MEDIA_STORAGE_BACKEND=s3 and Selectel S3 config remain authoritative. Never commit secrets.

## Safety invariants
1. Browser HttpOnly session provides shared_account_id; arbitrary IDs from payload are rejected. No synthetic Telegram IDs or Telegram transaction writes.
2. Invoice order is immutable for account+request key, persists invoice/contract ID and fixed RUB kopecks price. Provider amount/currency/status/identity are verified before any account ledger credit.
3. Existing Lava webhook authenticates sender first; native web orders are reconciled into their own live WalletService ledger while older Telegram transactions continue through the original handler.
4. Credit replay uses one fixed key web:topup:order_id across webhook and timed reconciliation. Crash between credit and order update cannot credit twice.
5. Wallet reserve and web task insertion occur atomically in one DB transaction; concurrent task idempotency repeats return the same task.
6. Provider create POST is at most once by SQL compare-and-swap lease; uncertain provider POST isn't blindly retried. Provider poll completion is authenticated independently of a signed callback.
7. S3 durable result must be available before capture; provider failure releases same reservation. Capture and release are ledger-idempotent; no refunds exceeding captured amounts.
8. Browser refs are upload-limited, MIME-checked, S3 persisted, SHA-deduped, and protected by authenticated account ownership. Any reference IDs belonging to another account are rejected before reserving funds.
9. Provider media is fetched only by HTTPS with bounded redirects, trusted hostname suffixes, validated globally routable DNS/IP addresses, strict byte cap and image/video file signature.
10. All model prices come from runtime preset_manager; no changing business prices are hardcoded in browser or server.

## Model catalog and actual adapter coverage

The API inventory derives dynamically from bot.miniapp.IMAGE_MODELS and
bot.miniapp.VIDEO_MODELS (24 entries). An enabled flag and explicit
unavailable_reason distinguish tested web adapters from unsupported entries.

Current adapter dispatch set is **16 of 24**, pending real provider smoke:

Images: Nano Banana 2 Lite, Seedream 5.5 text/edit, Seedream 5 Pro,
Nano Banana Pro, Nano Banana 2, Seedream 4.5 Edit, GPT Image 2,
Wan 2.7 Pro (single-output 2K default), Grok Imagine I2I.

Videos: Kling 3.0 Pro/Standard, Kling 2.5 Turbo Pro, Grok Imagine Video,
Grok Imagine 1.5, Seedance 2.0, Veo 3.1 Fast.

Unsupported pending full pricing/recipe/delivery:
Seedream 5.5 layers, Wan 3.0 / Wan 3.0 Prime, Gemini Omni,
Kling Motion Control 2.6 / 3.0, Kling Avatar Standard / Pro.
Their names appear in the catalog, but enabled:false prevents purchases.

For quality, reference count and duration, browser UI calls the
web-generation/quote endpoint. Task creation can supply expected_price:
if tariffs change before reservation, API returns 409 instead of silently
charging a different price. Runtime model prices come from original
Mini App resolvers/preset manager, never client literals.

## Verification and rollout gate
The automated isolated database and browser tests cover checkout idempotency, replay, spoofing, provider outage, refunds, settlement recovery, concurrent reservations, cross-account references, and mobile E2E. Live provider invoice status and exact amount fields MUST be confirmed via real small-value checkout before enabling the payment flag. A real KIE photo/video generation and Selectel S3 readback MUST be confirmed before enabling generation. If Lava contract responses lack verified status/amount, fail closed rather than credit.

## Residual considerations
- Provider POST outcome uncertainty still needs manual/provider-side correlation, not a second paid submission.
- Promo/paid referral commissions not yet connected to browser purchases.
- Other Telegram model variants need independent adapters and contract tests.
- Observe pending tasks, webhook lag, ledger reconciliation, S3 writes and generation output failures after activation.

## Verification checkpoint
- Isolated backend regressions: **178 passed** including catalog parity and 16 adapter dispatches.
- Frontend Jest: **19 passed**; Next.js static build passed.
- Browser E2E at mobile 390px and desktop 1440px: passed.
- Focused Ruff: passed.
- Production untouched; both feature flags remain disabled.

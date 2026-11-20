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

Current adapter dispatch set is **20 of 24**, pending real provider smoke:

Images: Nano Banana 2 Lite, Seedream 5.5 text/edit, Seedream 5 Pro,
Nano Banana Pro, Nano Banana 2, Seedream 4.5 Edit, GPT Image 2,
Wan 2.7 Pro (single-output 2K default), Grok Imagine I2I.

Videos: Kling 3.0 Pro/Standard, Kling 2.5 Turbo Pro, Grok Imagine Video,
Grok Imagine 1.5, Seedance 2.0, Veo 3.1 Fast.

Additional video adapters: Kling Motion Control 2.6 / 3.0 and
Kling Avatar Standard / Pro. Motion requires one image plus one video;
Avatar requires one image plus one audio. All are typed owner-bound
S3 uploads and server-side Motion quality pricing.

Unsupported pending full pricing/recipe/delivery:
Seedream 5.5 layers, Wan 3.0 / Wan 3.0 Prime, Gemini Omni.
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


## Additional typed multimedia references and release gates

- Full catalog: 24 original entries; 20 with implemented native adapters,
  4 explicitly disabled in web interface.
- Typed video/audio reference upload: mime verified by file signature,
  memory size bounded per media type, account ownership and kind-scoped
  lookups, no client-provided provider URLs.
- WEB_GENERATION_VIDEO_REFERENCE_MAX_BYTES defaults to 33554432 (max 64MiB);
  WEB_GENERATION_AUDIO_REFERENCE_MAX_BYTES defaults to 16777216 (max 32MiB).
- Motion Control 2.6/3.0 require one owned image and one owned video; quality
  follows original motion_modes and live get_video_cost_with_quality.
- Kling Avatar Standard/Pro require one owned image and one owned audio.
- Browser forms and server quote include typed refs and the proper cost
  before reserving any wallet funds. All adapters have isolated tests.
- Real provider paid smoke is still required before enabling these routes.
- Remaining 4 products not yet live-ready:
  Seedream 5.5 layer decomposition (multi-image output, variable billing),
  Wan 3.0 & Prime (multimodal recipes and quality-specific lifecycle),
  Gemini Omni (video/audio-ID/character-ID distinct result schemas).
  They must remain disabled until full safe recipe, billing, delivery support.


## Follow-up: provider contract and pricing guard (verified locally)

- Veo 3.1 Fast provider supports only 4/6/8 seconds, though older UI
  inventory also exposed 2/10. Independent web quotes and forms now restrict
  this model to 4/6/8. No silent clamping to another billable duration.
- Veo first-and-last-frame scenario is limited to two owned images, rather
  than accepting extra client refs that would be silently ignored.
- Seedream 4.5 Edit provider truncates input beyond five refs; web requires
  at most five and maps 2K to provider basic, 4K to provider high.
- Typed media image/video/audio uploads and account-scoped task reservations
  are tested end-to-end for Motion Control and Avatar in the isolated runtime.
- Full focused regression including pre-existing Telegram/Lava paths:
  **214 backend tests passed**, 21 frontend tests passed, optimized Next.js
  build successful and Playwright browser E2E successful.
- The full GitHub safe regression previously failed only on the static
  login guard assertion in test_public_landing. Login now checks BOTH HTTP
  success and verified payload after the legacy fallback, and targeted
  public landing regressions pass. Rerun the full CI on the new commit.


## Continuation checkpoint: native web model contracts

This is an unreleased draft. Original 24-model Mini App catalog is projected
into the independent browser studio. With the checked-in admin price file,
22/24 have enabled independent adapters; Wan 3.0 and Wan 3.0 Prime remain
disabled because no per-resolution quality rates are configured. We NEVER
fallback to unrelated generic video prices.

Gemini Omni Video: text/image to video via existing KIE adapter, 720p/1080p/4k
resolution-specific pricing. Account-owned video/audio/character asset IDs
and their creation flows are NOT implemented; arbitrary IDs are forbidden.

Wan 3.0 Standard and Prime: prepared native adapter supports text, first frame,
first+last and image-reference scenarios, bounded and owned input image IDs,
fixed 2-30 second duration, 480P/720P/1080P admin rate snapshots. Auto -1,
edit, video/audio/file/link recipes are intentionally unavailable until media
duration probing and exact supplier-seconds settlement are implemented.

Seedream 5.5 Layers: maximum 2-100 output images quoted by the original
admin-managed image/reference rates; the maximum price is reserved in the
account-native wallet. The input and output unit prices are SNAPSHOTTED at
reservation. The provider result is polled through our KIE API key; every
output is fetched with allowlisted public-only HTTPS, byte cap and image
signature check, then stored in Selectel S3. All ordered images and manifest
are bundled into an S3 ZIP. Final wallet capture is based on actual image
count, unused reserve is idempotently released, and web history exposes
the ZIP and the final price. Empty/invalid media cannot settle a task.

Verification: 233 backend regression tests, 22 frontend Jest tests,
optimized Next.js build, browser E2E on 390px/1440px, Ruff focused checks.
Live paid KIE/Lava and Selectel S3 readback for this branch NOT performed.

PRODUCTION GATES: configure real Wan3 quality rates through existing admin
price settings; add provider media probing/auto-duration and edit/file/link,
Gemini Audio/Character asset flows, test live paid tasks for all 24 models
and verify S3 GET plus full CI. Keep WEB_NATIVE_GENERATION_ENABLED and
WEB_NATIVE_PAYMENTS_ENABLED disabled in production until then.


## Native Omni assets and Wan 3.0 multimedia continuation (PR #646)

- New independent Gemini Omni Audio ID / Character ID creation endpoints
  and browser forms. Quoted using configured gemini_omni_audio/character
  retail rates; atomic wallet reservation, task idempotency, KIE create at
  most once, polling for a pending ID, completion only after an owned
  web_omni_assets record is persisted. Browser returns only opaque oa_
  identifiers, never raw provider IDs. Linked Audio/Character IDs are
  validated against completed account-owned records before Omni video
  reservation, which passes provider IDs only in the server-to-KIE call.
  Gemini Omni Video also accepts one owned MP4 video source and verified
  duration with the existing provider video_list contract.
- Wan 3.0 / Prime now support account-owned text, first frame, first/last,
  reference image/video/audio, edit (video), file and public-webpage modes.
  Uploaded documents are sniffed independently of declared MIME (PDF/TXT,
  DOC/XLS/PPT and DOCX/XLSX/PPTX + iWork), bounded by upload limit and ZIP
  decompression constraints. External webpages are imported only through an
  authenticated HTTPS endpoint, public-only DNS resolver, validated redirects
  and bounded HTML download; only an opaque owner-bound ID reaches the task.
  Link resolution is revalidated before purchase.
- Wan3 existing ffprobe metadata adapter verifies SHA-256 of account-owned
  S3 uploads, checks source dimensions/page limits/durations and measures
  input video seconds before charge. Auto duration initially reserves the
  maximum 30 billable seconds. Provider video is durably stored in S3,
  locally ffprobed under an exact task-specific storage key, actual seconds
  priced from a frozen per-resolution rate snapshot, captured once; unused
  credit reserve released idempotently. Rates are never client-supplied.
- Existing admin quality-price editor includes Wan3 Standard and Prime
  with 480p/720p/1080p cells. On the checked-in price config those cells
  are unset, so the two Wan3 model rows remain disabled/fail-closed; do not
  invent a business tariff. A real administrator must configure prices
  before either model is purchasable.
- Test evidence before this branch's latest push: 253 isolated backend
  regressions, 26 frontend Jest tests, optimized Next.js/TypeScript build,
  mobile and desktop public login and web checkout E2E, Ruff focused
  checks passed.
- Real KIE paid calls, Lava settlement, S3 PUT/GET public readback and
  external Google/email credentials not performed for this update;
  full GitHub CI must pass before removing Draft.
- Remaining business parity: web-referral *payment commission* payout still
  uses a separate future ledger integration, and source-specific advanced
  options for all existing Telegram models need live contract smoke. The
  web feature flags intentionally remain off in production pending proof.

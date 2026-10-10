# Wan 3.0 Video Prime integration contract

Provider reference: local snapshot `docs/providers/wan3-prime-kie.md`; public docs https://docs.kie.ai/market/wan/3-0-video-prime.

## Provider adapter

- Internal model key: `wan_3_prime`; provider model: `wan/3-0-video-prime`.
- Create: `POST /api/v1/jobs/createTask` with `{ model, input, callBackUrl? }`.
- Status: `GET /api/v1/jobs/recordInfo?taskId=...`.
- Supported input fields are exactly the documented 14 fields: `prompt`, `first_frame_url`, `last_frame_url`, `reference_image_urls`, `reference_video_urls`, `reference_audio_urls`, `reference_file_urls`, `reference_link_urls`, `resolution`, `aspect_ratio`, `duration`, `audio`, `seed`, `nsfw_checker`.
- Editing is a NEUROMIX workflow, not a provider-native field: `Video1` is the source video in `reference_video_urls[0]`; user change instructions are stored raw and wrapped once into the provider prompt. The wrapper is managed by bot setting `wan3_prime_edit_prompt_template`; default version is `wan3-prime-edit-v1`.
- No `edit`, `omni_reference_task_type`, Seedance multiplier, sorting, deduplication, truncation, or silent mode reclassification is allowed.

## Mini App API seam

Frontend contract lives in `frontend/miniapp-v0/lib/wan3-prime-api.ts`. Parent lifecycle should provide these authenticated routes under the existing Mini App API base:

- `POST /wan3/quote`: `{ init_data, start_param_fallback, client_request_id, recipe }` -> quote hash, reserve cost, source seconds, tariff state, Auto settlement notice.
- `POST /wan3/generate`: `{ init_data, start_param_fallback, client_request_id, idempotency_key, quote_hash, recipe }` -> internal task id and accepted/unknown/queued state.
- `POST /wan3/upload/init`, `/wan3/upload/chunk`, `/wan3/upload/complete`: owned chunk upload for image/video/audio/file limits without raising generic upload ceilings.
- `POST /wan3/import`: SSRF-safe bounded import for public media/file URL or public unauthenticated link validation.
- `POST /wan3/recipe`: owner-only full recipe restore. Public repeats must redact private media and hidden prompts.

The recipe shape mirrors the provider adapter and preserves `seed: 0`, `audio: false`, array order, and all optional reference slots.

## Telegram FSM seam

`bot/handlers/wan3_prime.py` owns mode state, ordered slot helpers, payload/review assembly, quote review, and explicit start confirmation. Runtime calls are lazy facade calls to lifecycle-owned `bot.wan3_prime_api`:

- `quote_telegram_wan3_prime(telegram_id, client_request_id, recipe)`
- `launch_telegram_wan3_prime(telegram_id, client_request_id, idempotency_key, quote_hash, recipe)`

Telegram media download/import is intentionally a bridge seam for the lifecycle/media slice. Large files should offer Mini App upload when Telegram download limits apply; the model capability must not be hidden.

## Pricing/admin

Wan paid launches require a positive admin-configured quality rate for `480p`, `720p`, or `1080p`. Admin-free launches can quote zero while rates are missing. Admin video prices are grouped and paginated; unknown/future configured models remain in `Другое`.

## Release hardening and unified repeats (2026-10-10)

The public Telegram picker now has family tabs and six models per page. All seven Wan modes remain available; mode drafts preserve inputs. Editing keeps Video1 as the source, including a missing-source placeholder after its removal. Native voice messages are converted in full to MP3 before the same media validation.

All new Wan launches use the dedicated persistent lifecycle. Public feed repeats and curated trends compile server-side from an original recipe and explicit per-slot consent. Fixed source URLs and the original hidden prompt never enter the consumer form or an owned derived recipe. Settings, ordered image/video/audio/document/link roles and first/last frame fields remain intact. Consent is rechecked in the reservation transaction. Accepted repeat accounting and successful-generation rewards use the existing partner ledger; replay and duplicate callbacks cannot credit twice. Administrative video replays use the same Wan adapter, not Kling. Generic pending-Wan refunds are refused because their amounts are lifecycle reserves.

Admins can publish an original completed Wan task from its Mini App detail panel. Title/description and URL-free settings appear in the existing Trends catalog. The complete private recipe lives in wan3_prime_trend_recipes. Each media slot can be fixed or replaced, including the source Video1. Old generic clients are redirected to the Wan editor before debit.

Storage quotas account for open, assembling/importing and completed inputs under one SQLite/PostgreSQL lock. Capacity checks use the actual uploads filesystem. Expired chunks release quota only after deletion; unused media expires while task/trend-referenced originals remain protected. Configuration: WAN3_UPLOAD_USER_QUOTA_BYTES, WAN3_UPLOAD_GLOBAL_QUOTA_BYTES, WAN3_UPLOAD_MIN_FREE_BYTES, WAN3_UNUSED_MEDIA_TTL_SECONDS, WAN3_ASSEMBLY_LEASE_SECONDS. Defaults preserve all provider-supported per-file limits. PDF page validation uses a time/memory-bounded child process with pypdf; 50 pages is accepted without counting /Pages as an extra page.

Callbacks require the per-intent secret before provider lookup/polling. Unknown createTask outcomes, including gateway 5xx, retain the original reservation and idempotency key. Canonical callback URL, model and prepared input must agree to recover an unbound provider ID. /wan3_ops lists unresolved cases; /wan3_resolve offers explicit confirmed, audited bind/refund operations without creating a new generation.

Verification in the isolated workspace: all seven signed Mini App HTTP scenarios traverse real SQLite quote/reserve/status/owner-recipe paths with only the provider/probe mocked; full seven-mode mobile browser run passes (including 320px editor), family search/pages and lost acknowledgement retry. Frontend production build and TypeScript check pass. Focused backend, replay, consent and partner regressions pass. Exact final-head GitHub CI, PostgreSQL concurrency, security review and deployment verification remain release gates, not implied by these local results.

Retail rates are intentionally not invented: configure Wan 480p/720p/1080p in the existing admin price editor. Existing production price.json must be retained. Paid launches fail before debit when the selected rate is absent. No paid upstream generation or visual result-quality verification is claimed by automated tests.

### Final release review closure

The final review added bounded recovery for canonical-download failures as well as invalid bytes. Missing URLs, HTTP errors, missing files and failed probes consume the same finite result-repair budget and then enter `/wan3_ops`; no paid generation is resubmitted. Operators can resolve the reserve with the existing audited confirmation.

ZIP-backed Office/iWork documents now use the same isolated metadata worker as PDF, with CPU, memory and wall-clock limits applied before opening the archive. Per-user/per-worker parser admission remains held across cancellation. Invalid documents terminate their upload session; rejected bytes remain in quota until removed.

Result retention is task-aware: only private, completed, Telegram-delivered outputs older than `WAN3_RESULT_RETENTION_SECONDS` (default 30 days) are expired. Published/profile-visible, referenced, curated-trend and undelivered outputs are preserved. Financial/completion history remains. The quote discloses the retention period. `WAN3_RESULT_GLOBAL_QUOTA_BYTES` (default 20 GiB) and actual filesystem free space bound retained results plus pending-result reservations before any debit/provider call.

Secure callbacks use KIE's documented `X-Webhook-Timestamp`/`X-Webhook-Signature` HMAC-SHA256 headers and the existing `KIE_WEBHOOK_HMAC_KEY`; timestamps must be recent. The URL carries only the non-secret intent identifier. Without that key, the durable worker uses polling; this does not disable any generation/editing mode. Legacy nonce URLs require explicit `WAN3_CALLBACK_QUERY_LOGS_REDACTED=1` after every proxy/app log is safe. An optional TLS-server snippet is provided at `ops/wan3-callback.conf`; this task could not install it because `/etc/nginx` is read-only to SentinelX. No permissions were widened and no live nginx configuration was changed. The nonce opt-in remains disabled by default, so this does not expose callback secrets in existing proxy logs.

Official signature contract: https://docs.kie.ai/common-api/webhook-verification

Fresh local focused result after these changes: 171 passed, 6 PostgreSQL-only cases skipped locally; those run in the dedicated disposable PostgreSQL CI job. The exact candidate's full GitHub CI and production deployment must be checked separately.

### Final concurrency and preprocessing follow-up

The follow-up review identified five additional edge cases, all reproduced by regression tests before their fixes. Audio preprocessing now acquires the shared per-user/per-worker admission slot before Telegram download/conversion. A standalone child probes duration before ffmpeg and enforces local-only protocols/demuxers, one codec thread, CPU/memory/output-byte ceilings, and wall-clock deadlines. Supported audio is not shortened; out-of-range sources are rejected. Link imports and quote-time webpage fetches use the same admission budget.

Capacity admission counts pending result reservations before scanning retained files, so a concurrent settlement cannot disappear from both counts. Feed and profile publication acquire the Wan storage lock before the authoritative task read and keep it through media persistence and commit, preventing expiry from deleting an in-flight publication source. This is exercised with deterministic SQLite publication races and a real PostgreSQL lock test.

Accepted provider tasks that do not reach a terminal state by `WAN3_PROVIDER_MAX_PENDING_SECONDS` (default 7200 seconds) are escalated to the existing operator-attention queue. Their provider IDs, reserves and user history remain intact; there is no automatic resubmission or guessed refund. Canonical polling and authenticated callbacks remain active for this timeout reason, so a later terminal result can still settle and deliver exactly once. Explicit audited operator resolution remains available. Result-validation and download failures keep their bounded repair budget and are not reopened by the timeout reconciliation path. Sanitized provider failure reasons are retained privately for diagnosis; public failure responses remain generic and secrets/reference URLs are removed.

Focused validation after this follow-up: 195 passed, 7 PostgreSQL-only skipped locally, including the publication compatibility suite. Exact-head CI and independent review remain required before release.

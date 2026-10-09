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

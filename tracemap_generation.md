# Parameter Trace Map — banano_kling Generation Flows

> Generated: 2026-07-04  
> Scope: All image & video generation flows from Telegram + Mini App through services → Kie.ai API → webhook → DB → user notification

---

## Flow 1: Image Generation (Telegram) — Nano Banana Pro

**Path:** `handlers/generation.py:_start_image_generation_task()` → `nano_banana_pro_service.py:generate_image()` → `Kie.ai POST /api/v1/jobs/createTask` → `main.py:handle_kling_webhook()` → `database.py:complete_video_task()` → user notification

### Parameter Trace

| Flow name | Parameter name | Created at (file:line) | Expected by (next consumer) | Actually passed (name/type) | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|---|---|---|---|---|---|---|---|---|---|
| TG Banana Pro | `telegram_id` | handlers/generation.py:931 (function arg) | database.py:add_generation_task(db column telegram_id) | `telegram_id`: int | No | No | none | none | No |
| TG Banana Pro | `user.id` | handlers/generation.py:931 (via `user` arg from `get_or_create_user`) | database.py:add_generation_task(db column user_id) | `user_id`: int | No | No | none | Rename `user` arg to `user_obj` to distinguish from `telegram_id` — low priority | No |
| TG Banana Pro | `local_task_id` | handlers/generation.py:963 (`f"img_{uuid.uuid4().hex[:12]}"`) | database.py:add_generation_task → generate_image result comparison | `local_task_id`: str (`"img_XXXX"`) | **YES** — if API returns task_id, local_task_id is overwritten in DB (line 1107) and only logged | No | none | Preserved as `task_id_aliases` via `_merge_task_id_aliases` — OK, but retrieval by local_task_id depends on alias fallback | No |
| TG Banana Pro | `task_id` (API) | nano_banana_pro_service.py:create_task() line ~185 `data.get("taskId")` | handlers/generation.py:1104 `result["task_id"]` → DB UPDATE replaces local_task_id | `task_id`: str (Kie.ai UUID) | No — replaces local_task_id in DB | No | none | none | No |
| TG Banana Pro | `model` / `service` / `provider_model` | handlers/generation.py:952 `_get_image_provider_model()` - returns `"nano-banana-pro"` | nano_banana_pro_service.py:create_task() payload `"model": "nano-banana-pro"` | **Hardcoded** in service: `"nano-banana-pro"` (line ~168). The `model` param is implicit. Provider model from `_get_image_provider_model()` is passed to generate_image but **NOT used** by banana_pro service — service ignores model param and always sends `"nano-banana-pro"` | **YES** — `model` kwarg accepted but not forwarded; service hardcodes it | **YES** — `model` parameter in `nano_banana_2_service.generate_image()` vs `nano_banana_pro_service.generate_image()`: banana_2 has `model` kwarg, banana_pro does NOT | low | Add `model` kwarg to `nano_banana_pro_service.generate_image()` and pass it through to `create_task()` for consistency | Yes |
| TG Banana Pro | `callback_url` | handlers/generation.py:931 (function kwarg) → derived from `config.kie_notification_url` outside | service create_task → payload `callBackUrl` | `callBackUrl`: str | No — passed correctly | **YES** — naming: param is `callback_url` in handlers, `callBackUrl` in Kie.ai payload (camelCase) | low | Consistent naming across layers would reduce confusion, but Kie.ai requires camelCase — conversion is correct | No |
| TG Banana Pro | `aspect_ratio` | handlers/generation.py:`_resolve_image_aspect_ratio()` returns `img_ratio` | nano_banana_pro_service.py:create_task() payload `"aspect_ratio"` | `aspect_ratio`: str (e.g., `"1:1"`, `"16:9"`) | No | No | none | none | No |
| TG Banana Pro | `image` / `image_input` / `reference_images` | handlers/generation.py:961 `_prepare_banana_reference_images()` → list[str] of URLs | nano_banana_pro_service.py:create_task() → payload `input.image_input`: list[str] | `image_input`: list[str] | No — passed via `generate_image(image_input=...)` | **YES** — naming: param is `reference_images` in handlers, `image_input` in service, `image_input` in Kie.ai payload | none | Consistent naming: all layers use `image_input` or all use `reference_images`. Current mixed naming is confusing. | No |
| TG Banana Pro | `resolution` / `quality` / `img_quality` | handlers/generation.py:941 `_default_image_flow_data()` → `img_quality` (default `"2K"`) | nano_banana_pro_service.py:generate_image() param `resolution` → `_normalize_resolution()` → payload `input.resolution` | `resolution`: str (`"1K"`, `"2K"`, `"4K"`) | No — `img_quality` → `resolution` mapping is correct | **YES** — handlers uses `img_quality` name, service uses `resolution` name. Resolution alias table maps `"BASIC"` → `"2K"`, `"HIGH"` → `"4K"` | none | Alias table maps correctly; naming inconsistency is cosmetic | No |
| TG Banana Pro | `seed` | Not used | Not applicable | Not passed | **YES** — no seed parameter anywhere in the banana_pro flow | N/A | none | Banana Pro/Gemini fallback doesn't support seed — OK | No |
| TG Banana Pro | `duration` | Not applicable (image flow) | Not applicable | Not passed | N/A | N/A | N/A | N/A | No |
| TG Banana Pro | `cost` / `amount` | handlers/generation.py:`deduct_credits(telegram_id, unit_cost)` — `unit_cost`: int (bananas) | database.py:add_generation_task(cost=unit_cost) → DB column `cost` INTEGER | `cost`: int (banana currency) | No | **YES** — `deduct_credits(telegram_id, amount: float)` but banana costs are ints. `float` is used only because credits column might need fractional. The call passes `int` but function signature accepts `float`. | medium | Credits column is INTEGER in DB (line 660: `credits INTEGER DEFAULT 0`), but function signatures use `float`. This is a latent bug — if someone passes a float cost, DB will truncate. Consistent type should be `int`. | Yes |
| TG Banana Pro | `status` (provider vs internal) | Kie.ai API responds with task_id → internal status = `"queued"` | handlers/generation.py:1095 `result_status == "queued"` | Internal: `"queued"` → `"pending"` in DB; Provider: `"state"` field (`"success"`/`"fail"`) | No | **YES** — Provider uses `"state": "success"/"fail"/"processing"`, DB uses `"pending"/"completed"/"failed"`. Webhook translates correctly. | none | Translation is correct; consider enum for internal statuses | No |
| TG Banana Pro | `prompt` / `effective_prompt` | handlers/generation.py:964 `_apply_safe_prompt_framing()` → `effective_prompt` | nano_banana_pro_service.py:create_task() → payload `input.prompt` | `prompt`: str (safety-wrapped) | **PARTIAL** — original prompt stored in request_data, effective_prompt sent to API. Original lost if request_data not inspected. | No (both strings) | low | Original vs effective prompt: stored correctly in request_data key `"prompt"` vs `"effective_prompt"` | No |
| TG Banana Pro | `output_format` | nano_banana_pro_service.py:generate_image() kwarg, default `"png"` | Kie.ai payload `input.output_format` | `output_format`: str | No — passed with default | No | none | none | No |
| TG Banana Pro | `nsfw_checker` / `nsfw_enabled` | handlers/generation.py:nsfw_checker=False, nsfw_enabled=False | NOT passed to nano_banana_pro_service | Not forwarded | **YES** — `img_nsfw_checker` and `nsfw_enabled` stored in request_data but never sent to service | N/A | none | Intentionally omitted (Banana Pro has no NSFW toggle) — OK | No |

---

## Flow 2: Image Generation (Mini App) — Nano Banana 2

**Path:** `miniapp.py:_handle_image_generate()` → `nano_banana_2_service.py:generate_image()` → `Kie.ai POST /api/v1/jobs/createTask` → `main.py:handle_kling_webhook()` → `database.py:complete_video_task()` → user notification

### Parameter Trace

| Flow name | Parameter name | Created at (file:line) | Expected by (next consumer) | Actually passed (name/type) | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|---|---|---|---|---|---|---|---|---|---|
| MiniApp Banana 2 | `telegram_id` | miniapp.py:_get_user_context() → `int(telegram_user["id"])` | database.py:add_generation_task(telegram_id=...) | `telegram_id`: int | No | No | none | none | No |
| MiniApp Banana 2 | `chat_id` vs `telegram_id` | miniapp.py: telegram context uses `telegram_id` throughout | Bot.send_message(chat_id=telegram_id) | Both passed as `telegram_id` | No | No | none | In Telegram, `chat_id == telegram_id` for private chats, but for groups this could break — not in scope here | No |
| MiniApp Banana 2 | `task_id` (API) | nano_banana_2_service.py:create_task() → `data.get("taskId")` | miniapp.py:_handle_image_generate() → add_generation_task(task_id=result["task_id"]) | `task_id`: str (Kie.ai UUID) | No — directly stored in DB as `task_id` | No | none | none | No |
| MiniApp Banana 2 | `model` | miniapp.py: `banana_2` (model selection from IMAGE_MODELS dict) | nano_banana_2_service.py:generate_image(model=...) | `model`: str — passed to banana_2 service, which uses it to decide: `"nano-banana-2"` default, or `"nano-banana-2-lite"` for lite variant | No — model routing works correctly | **YES** — banana_2 service has `model` kwarg, banana_pro service does NOT; they have different signatures | low | Unify service signatures: both should accept `model` kwarg | Yes |
| MiniApp Banana 2 | `model` → Lite path | nano_banana_2_service.py: if model in NANO_BANANA_2_LITE_MODEL_IDS → `kie_market_service.create_nano_banana_2_lite_task()` | kie_market_service → different endpoint | `model` = `"nano-banana-2-lite"` | No | No | none | Lite path uses different service entirely — correct routing | No |
| MiniApp Banana 2 | `callback_url` / `webhook_url` | nano_banana_2_service.py:create_task() — passed from handler as `callback_url` | Kie.ai payload `callBackUrl` | `callBackUrl`: str | **PARTIAL** — For Lite model: uses `config.kie_market_notification_url` (market webhook), for standard: uses handler's `callback_url` | No | medium | Two different webhook URLs for same model family — standard vs lite. Ensure both webhook endpoints handle responses correctly. | Yes |
| MiniApp Banana 2 | `aspect_ratio` | miniapp.py: from user model selection → service | nano_banana_2_service.py:create_task() → payload `input.aspect_ratio` | `aspect_ratio`: str | No | No | none | For Lite: `aspect_ratio="auto"` default vs standard: `"1:1"` default — inconsistency between model variants | No |
| MiniApp Banana 2 | `resolution` / `img_quality` | miniapp.py: `img_quality` from quality selector | nano_banana_2_service.py:generate_image(resolution=...) | `resolution`: str (`"1K"`, `"2K"`, `"4K"`) | No — mapped correctly | **YES** — `img_quality` → `resolution` naming difference | none | Same naming issue as Flow 1 | No |
| MiniApp Banana 2 | `image_input` / `reference_images` | miniapp.py: `image_references` list from upload | nano_banana_2_service.py:create_task(image_input=...) → payload `input.image_input` | `image_input`: list[str] URL | No | **YES** — naming: `reference_images` → `image_input` | none | Same naming inconsistency as Flow 1 | No |
| MiniApp Banana 2 | `seed` | Not used | Not applicable | Not passed | **YES** — seed not supported | N/A | none | Intentionally omitted | No |
| MiniApp Banana 2 | `status` | nano_banana_2_service.py: same Kie.ai response → `classify_image_generation_result()` → `"queued"` | miniapp.py → add_generation_task(status="pending") | Internal: `"queued"` → `"pending"` | No | **YES** — provider state (`"success"`/`"fail"`) vs DB status (`"pending"`/`"completed"`/`"failed"`) | none | Correctly translated | No |
| MiniApp Banana 2 | `cost` | miniapp.py: `unit_cost` from preset_manager cost | database.py:add_generation_task(cost=unit_cost) | `cost`: int (bananas) | No | **YES** — same int vs float signature mismatch as Flow 1 | medium | Same `float` signature bug as Flow 1 | Yes |

---

## Flow 3: Video Generation (Kling)

**Path:** `handlers/generation.py:_start_video_generation_task()` → `kling_service.py:generate_video()` → `Kie.ai POST /api/v1/jobs/createTask` → `main.py:handle_kling_webhook()` → `database.py:complete_video_task()` → user notification

### Parameter Trace

| Flow name | Parameter name | Created at (file:line) | Expected by (next consumer) | Actually passed (name/type) | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|---|---|---|---|---|---|---|---|---|---|
| TG Kling | `telegram_id` | handlers/generation.py: function argument (from callback/state) | database.py:add_generation_task(telegram_id=...) | `telegram_id`: int | No | No | none | none | No |
| TG Kling | `task_id` (API) | kling_service.py:_parse_kie_create_response() → `task_id` from `inner_data.get("taskId")` | handlers → add_generation_task(task_id=result["task_id"]) → DB | `task_id`: str (Kie.ai UUID) | No | No | none | none | No |
| TG Kling | `task_id` → `webhook lookup` | main.py:handle_kling_webhook(): reads `task_id` from `data["taskId"]` or `kie_data["taskId"]` | database.py:get_task_by_id(task_id) → complete_video_task(task_id, ...) | `task_id`: str — used as primary lookup key | No — also supports `task_id_aliases` fallback | No | medium | Webhook looks up by exact task_id + alias fallback. If Kie.ai sends a different task_id format than what was stored, lookup fails silently. Alias fallback is a safety net. | Yes |
| TG Kling | `model` / `service` routing | handlers/generation.py: `_get_video_provider_model()` → model str | kling_service.py:generate_video(model=...) → routes to specific method | `model`: str (e.g., `"v3_std"`, `"v26_pro"`, `"avatar_std"`) | No — model correctly routes internally | No | none | Kling service has `NON_KLING_MODELS` blocklist to reject misrouted models — good defense | No |
| TG Kling | `provider_model` | kling_service.py:generate_video() → generates Kie.ai model string: `"kling-3.0/video"`, `"kling/v2-5-turbo-text-to-video-pro"`, `"kling/v2-5-turbo-image-to-video-pro"`, `"kling/ai-avatar-standard"`, `"kling-2.6/motion-control"` | Kie.ai payload `"model"`: str | `model`: str (Kie.ai format) | No | No | none | Internal `model` (e.g. `v3_std`) is different from Kie.ai model (`kling-3.0/video`) — documented clearly in service | No |
| TG Kling | `callback_url` / `webhook_url` | handlers/generation.py:6672-6673 `config.kling_notification_url` → `/webhook/kling` | kling_service.py:generate_video(webhook_url=...) → payload `callBackUrl` | `callBackUrl`: str | No | **YES** — param is named `webhook_url` in handlers/generation.py and kling_service.generate_video(), but `callBackUrl` in Kie.ai payload | none | Naming variance is unavoidable (Kie.ai requires camelCase) — OK | No |
| TG Kling | `duration` | handlers/generation.py: user selects from [5, 10, 15] | kling_service.py:generate_video(duration=int) → payload `input.duration` | `duration`: int in handlers → `str(duration)` in Kie.ai payload | **YES** — Kling 3.0 converts to str: `"5"`, `"10"`, `"15"`; Kling 2.5 also converts via `str(self._safe_duration_25(duration))` | **YES** — `duration` is `int` in handlers, `int` in kling_service args, but `str` in Kie.ai payload | low | Type change is intentional (Kie.ai expects string duration); document explicitly | No |
| TG Kling | `aspect_ratio` | handlers/generation.py: user selects ratio | kling_service.py: `_safe_aspect_ratio()` validates → `{"16:9", "9:16", "1:1"}` | `aspect_ratio`: str | No — validated and normalized | No | none | Defaults to `"16:9"` if invalid — safe fallback | No |
| TG Kling | `image_url` / `image_urls` | handlers/generation.py: single `image_url: Optional[str]` or list references | kling_service.py: `_collect_image_urls()` → `image_urls: List[str]` | Via Kling 3.0: `input.image_urls`: list[str]; Kling 2.5: `input.image_url`: str (single) | No — correctly merged + deduped | **YES** — Kling 3.0 `image_urls` (list) vs Kling 2.5 `image_url` (single string) — different Kie.ai payload structure | medium | Single vs list difference is documented; handled correctly per model in kling_service | No |
| TG Kling | `video_urls` / `motion_video` | handlers/generation.py: `video_references` list | kling_service.py:generate_video(video_urls=...) → payload `input.video_urls` (motion control) or `audio_url` (avatar) | `video_urls`: list[str] for motion; `video_urls[0]` as `audio_url` for avatar | **PARTIAL** — Avatar receives `video_urls[0]` as audio_url; this is a semantic map: video ref URL → audio input in avatar context | No | medium | `video_urls` used for audio in avatar flow — semantically confusing. Rename avatar audio parameter to `audio_url`. | Yes |
| TG Kling | `negative_prompt` | handlers/generation.py: optional from user | kling_service.py:generate_kling_25_turbo_video(negative_prompt=...) | `negative_prompt`: str (truncated to 500 chars) | No — only for Kling 2.5 Turbo | No | none | Only applies to v26_pro — correct filtering | No |
| TG Kling | `cfg_scale` | handlers/generation.py: optional float | kling_service.py: `_safe_cfg_scale()` clamps to [0.0, 1.0] | `cfg_scale`: float | No — clamped and rounded to 1 decimal | **YES** — `float` in handlers, `float` in service, but Kee.ai expects numeric — potential for 0.5 vs 0.5000000000001 mismatch | low | Rounding to 1 decimal is safe | No |
| TG Kling | `elements` / `kling_elements` | handlers/generation.py: `elements` list of dicts (from multi-reference image flow) | kling_service.py: `_build_kling_elements()` → `kling_elements: List[Dict]` → payload `input.kling_elements` | `kling_elements`: list[dict] (max 3 elements, 2-4 images each) | No | No | none | Complex multi-reference element construction — well-validated | No |
| TG Kling | `mode` (std/pro) | handlers/generation.py: `"std"` or `"pro"` from model selection | kling_service.py:generate_video() → `generate_kling_3_video(mode=...)` | `mode`: str → mapped to Kling 3.0 input | No | No | none | Only `"std"`/`"pro"` accepted; any other value → `"std"` | No |
| TG Kling | `generate_audio` / `sound` | handlers/generation.py: `generate_audio: bool` | kling_service.py: `generate_kling_3_video(sound=...)` → payload `input.sound` | `sound`: bool | No — `generate_audio` → `sound` mapping | **YES** — naming: `generate_audio` → `sound` in Kling 3.0 payload | none | Naming variance between layers is cosmetic | No |
| TG Kling | `multi_shots` / `multi_prompt` | handlers/generation.py: optional multi-shot prompts | kling_service.py:generate_kling_3_video(multi_shots=bool, multi_prompt=list) | `multi_shots`: bool, `multi_prompt`: list[dict] (max 6) | No | No | none | Multi-shot feature is complex but correctly implemented | No |
| TG Kling | `status` (webhook) | main.py:handle_kling_webhook(): parsed from `data["data"]["state"]` or `data["status"]` | complete_video_task(task_id, video_url) → `"completed"` or complete_video_task(task_id, None) → `"failed"` | Provider statuses: `"success"`, `"completed"`, `"failed"`; DB: `"completed"`, `"failed"` | No — idempotency guard: skips if `task.status == "completed"` (line 1836) | No | low | Three different webhook formats supported (Kling direct, Kie.ai unified, PiAPI/Replicate fallback) — robust | No |
| TG Kling | `cost` | handlers/generation.py: computed before service call | database.py:add_generation_task(cost=...) | `cost`: int | No — but credits refunded from `task.cost` field on failure (webhook line 2456) | **YES** — cost stored in DB as `int`, refunded as `float` via `add_credits(telegram_id, task.cost or 0)` | medium | Same `float` signature bug — DB column is INTEGER but function signature is `float` | Yes |
| TG Kling | `seed` | Not used | Not applicable | Not passed | **YES** — Kling does not expose seed parameter | N/A | none | Not supported by Kling API | No |

---

## Flow 4: Video Generation (Seedance)

**Path:** `handlers/generation.py:_start_video_generation_task()` or `miniapp.py:_launch_video_generation_task()` → `seedance_service.py:generate_video()` → `Kie.ai POST /api/v1/jobs/createTask` → `main.py:handle_kling_webhook()` → `database.py:complete_video_task()` → user notification

### Parameter Trace

| Flow name | Parameter name | Created at (file:line) | Expected by (next consumer) | Actually passed (name/type) | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|---|---|---|---|---|---|---|---|---|---|
| Seedance | `telegram_id` | handlers/miniapp → from user context | database.py:add_generation_task(telegram_id=...) | `telegram_id`: int | No | No | none | none | No |
| Seedance | `task_id` | seedance_service.py:generate_video() → `_kie_post()` → `_parse_kie_create_response()` → `task_id` | Handlers → add_generation_task(task_id=result["task_id"]) | `task_id`: str (Kie.ai UUID) | No | No | none | Inherits from KlingService base; same task_id flow | No |
| Seedance | `model` | seedance_service.py: hardcoded `MODEL_NAME = "bytedance/seedance-2"` | Kie.ai payload `"model": "bytedance/seedance-2"` | `model`: str — hardcoded in service | No — but handler passes `model` value that is NOT used by seedance_service | **YES** — handler passes `model="seedance_2"` but service ignores it and hardcodes `"bytedance/seedance-2"` | low | Same pattern as banana_pro — handler model param not forwarded. OK if only one Seedance model exists. | No |
| Seedance | `callback_url` / `callBackUrl` | handlers: `config.kie_notification_url` → `/webhook/kie` | seedance_service.py:generate_video(callBackUrl=...) → payload `callBackUrl` | `callBackUrl`: str | No | **YES** — param uses `callBackUrl` (camelCase) throughout seedance_service, unlike banana services which convert from `callback_url` | low | Inconsistent naming: seedance uses `callBackUrl`, nano banana uses `callback_url` → `callBackUrl` conversion | No |
| Seedance | `duration` | handlers: user selects [5, 10, 15] | seedance_service.py:generate_video(duration=int) → payload `input.duration: int` (clamped 5-15) | `duration`: int — passed as int to Kie.ai (unlike Kling which converts to str) | No | **YES** — Seedance sends `duration` as `int` (clamped 5-15), Kling sends as `str`. Kee.ai API accepts both but inconsistent. | low | Both forms work; unified type would be cleaner | No |
| Seedance | `aspect_ratio` | handlers: user selection | seedance_service.py: validated against `SUPPORTED_RATIOS = {"16:9", "9:16", "1:1"}` | `aspect_ratio`: str | No — defaults to `"16:9"` if invalid | No | none | Correctly validated | No |
| Seedance | `resolution` | handlers: `resolution="720p"` (hardcoded from miniapp) or from user selection | seedance_service.py: validated against `SUPPORTED_RESOLUTIONS = {"480p", "720p", "1080p"}` | `resolution`: str, defaults to `"720p"` if invalid | No | No | none | Resolution validated against supported set | No |
| Seedance | `image` / `first_frame_url` / `reference_image_urls` | handlers: `first_frame_url` (single image) OR `reference_image_urls` (list) — mutually exclusive | seedance_service.py:generate_video(first_frame_url=..., reference_image_urls=...) → payload `input.first_frame_url` OR `input.reference_image_urls` | `first_frame_url`: str (single) OR `reference_image_urls`: list[str] | No — mutual exclusion enforced: error if both supplied (line 131-135) | No | none | Mutual exclusion is correctly enforced with error return | No |
| Seedance | `video` / `reference_video_urls` | handlers: `video_references` list | seedance_service.py:generate_video(reference_video_urls=...) → payload `input.reference_video_urls` (max 3) | `reference_video_urls`: list[str] | No | No | none | Trimmed to MAX_REFERENCE_VIDEOS (3) | No |
| Seedance | `image upload` via kie_file_upload_service | seedance_service.py:`_prepare_image_urls()` → `kie_file_upload_service.upload_local_image_sources()` | Kie.ai payload | Uploaded URLs → used directly in `first_frame_url` / `reference_image_urls` | **PARTIAL** — local upload sources that fail become "missing" and block the task (lines 151-163) | No — but uploaded URLs replaced in-place | medium | If local upload fails, task is blocked with `"missing_local_references"` error. Credits may have already been deducted. Check if credit deduction happens before or after seedance service call. | Yes |
| Seedance | `last_frame_url` | handlers: optional second frame for frame animation | seedance_service.py:generate_video(last_frame_url=...) → payload `input.last_frame_url` | `last_frame_url`: str | No | No | none | Correctly passed | No |
| Seedance | `return_last_frame` | seedance_service.py: bool, default `False` | Kie.ai payload `input.return_last_frame` | `return_last_frame`: bool | No | No | none | Correct | No |
| Seedance | `generate_audio` | seedance_service.py: bool, default `True` | Kie.ai payload `input.generate_audio` | `generate_audio`: bool | No | No | none | Correct | No |
| Seedance | `web_search` | seedance_service.py: bool, default `False` | Kie.ai payload `input.web_search` | `web_search`: bool | No | No | none | Correct | No |
| Seedance | `reference_audio_urls` | handlers: optional audio URL | seedance_service.py:generate_video(reference_audio_urls=...) → payload `input.reference_audio_urls` (max 1) | `reference_audio_urls`: list[str] | No | No | none | Trimmed to MAX_REFERENCE_AUDIO (1) | No |
| Seedance | `seed` | Not used | Not applicable | Not passed | **YES** — Seedance does not expose seed | N/A | none | Not supported | No |
| Seedance | `cost` | handlers: computed via preset_manager | database.py:add_generation_task(cost=...) | `cost`: int | No | **YES** — same `float` signature mismatch for deduct_credits | medium | Same issue as other flows | Yes |

---

## Flow 5: Motion Control (Mini App)

**Path:** `miniapp.py:_launch_video_generation_task()` → `kling_service.py:generate_video()` → `generate_motion_control()` → `Kie.ai POST /api/v1/jobs/createTask` → `main.py:handle_kling_webhook()` → `database.py:complete_video_task()` → user notification

### Parameter Trace

| Flow name | Parameter name | Created at (file:line) | Expected by (next consumer) | Actually passed (name/type) | Lost? | Type mismatch? | Security risk? | Fix needed? | Test needed? |
|---|---|---|---|---|---|---|---|---|---|
| Motion Ctrl | `telegram_id` | miniapp.py: from _launch_video_generation_task() args | database.py:add_generation_task(telegram_id=...) | `telegram_id`: int | No | No | none | none | No |
| Motion Ctrl | `task_id` | kling_service.py:generate_motion_control() → `create_kie_motion_task()` → `_parse_kie_create_response()` | miniapp.py → add_generation_task(task_id=result["task_id"]) | `task_id`: str (Kie.ai UUID) | No | No | none | Same Kie.ai task creation flow | No |
| Motion Ctrl | `model` → `motion_model` | miniapp.py: `model="motion_control_v26"` or `"motion_control_v30"` | kling_service.py: mapped to `"kling-2.6/motion-control"` or `"kling-3.0/motion-control"` | `motion_model`: str | No | **YES** — miniapp model `"motion_control_v26"` → kling_service `"kling-2.6/motion-control"`; naming is significantly different | low | Mapping is correct but spans two files; could benefit from centralized model registry | No |
| Motion Ctrl | `callback_url` / `webhook_url` | miniapp.py: `config.kling_notification_url` → `/webhook/kling` | kling_service.py:generate_motion_control(webhook_url=...) → payload `callBackUrl` | `callBackUrl`: str | No | No | none | Same webhook as other Kling flows | No |
| Motion Ctrl | `duration` | miniapp.py: hardcoded to 5 (from VIDEO_MODELS) | kling_service.py: not explicitly sent in motion control payload | Not sent to API | **YES** — duration is stored in DB but NOT sent in Kie.ai motion control payload. Motion Control duration is fixed by the model/video. | N/A | none | OK — motion control duration is determined by the reference video, not API parameter | No |
| Motion Ctrl | `image_url` | miniapp.py: `image_url` from upload | kling_service.py:generate_motion_control(image_url=...) → payload `input.input_urls: [image_url]` | `input_urls`: list[str] (single element) | No | **YES** — param is `image_url` (single), but Kie.ai expects `input_urls` (list) — correctly wrapped into list | low | Wrapping is correct | No |
| Motion Ctrl | `video_urls` / `video_references` | miniapp.py: `video_references[:1]` (only first video used) | kling_service.py:generate_motion_control(video_urls=...) → payload `input.video_urls` | `video_urls`: list[str] | No — validated (required: must have at least one video) | No | none | Only first video used — intentional; motion control needs one reference video | No |
| Motion Ctrl | `preset_motion` | kling_service.py:generate_motion_control(preset_motion=...) → payload `input.preset_motion` | Kie.ai payload | `preset_motion`: str or None | No — optional; only sent if provided | No | none | Optional parameter; correctly handled | No |
| Motion Ctrl | `mode` / `motion_mode` | miniapp.py: from model selection `motion_modes: ["720p", "1080p"]` | kling_service.py:generate_motion_control(mode=...) → maps to `"720p"` or `"1080p"` | `mode`: str in payload `input.mode` | No | No | none | Correctly mapped | No |
| Motion Ctrl | `character_orientation` | kling_service.py:generate_motion_control() → payload `input.character_orientation` | Kie.ai payload | `character_orientation`: str, default `"video"` | No — hardcoded to `"video"` | No | none | Hardcoded; no user override available. OK for current use case. | No |
| Motion Ctrl | `aspect_ratio` | kling_service.py:generate_motion_control() → payload `input.aspect_ratio` | Kie.ai payload | `aspect_ratio`: str, hardcoded to `"1:1"` | No — motion control always uses 1:1 | No | none | Fixed ratio is correct for motion control | No |
| Motion Ctrl | `cost` | miniapp.py: from preset_manager | database.py:add_generation_task(cost=...) | `cost`: int | No | **YES** — same float issue | medium | Same issue as other flows | Yes |
| Motion Ctrl | `seed` | Not used | Not applicable | Not passed | **YES** | N/A | none | Not supported | No |
| Motion Ctrl | `status` | Same as Kling flow: Kie.ai → webhook → DB | complete_video_task(task_id, result_url) | Same mapping as Flow 3 | No | Same as Flow 3 | low | Same pattern | No |

---

## Cross-Cutting Parameter Analysis

### 1. `user_id` vs `telegram_id` vs `chat_id`

| Usage Location | Name Used | Type | Notes |
|---|---|---|---|
| `database.py:add_generation_task()` | `user_id`: int (DB user PK), `telegram_id`: int (Telegram user id) | int, int | Stored as separate columns |
| `handlers/generation.py:_start_image_generation_task()` | `user` (object), `telegram_id` (int) | User object, int | `user.id` extracted for DB |
| `miniapp.py:_launch_video_generation_task()` | `telegram_id` (int), `user` (object) | int, User | Same pattern |
| `main.py:_resolve_task_telegram_id()` | reads `task.telegram_id` | int | Fallback to `task.user_id` |
| `main.py:bot.send_message(chat_id=telegram_id)` | `chat_id` param = `telegram_id` value | int | For private chats only; would break for groups |
| **Risk**: `user_id` (DB PK) and `telegram_id` (Telegram ID) are different values but both called "user_id" in different contexts. `_resolve_task_telegram_id` falls back to `task.user_id` if `task.telegram_id` is None — this silently uses the wrong ID. | | | |
| **Fix**: Add explicit assertion that `task.telegram_id` is not None; do not fallback to `user_id`. | | | |

### 2. `task_id` vs `generation_id` vs `external_task_id`

| Usage | Name | Notes |
|---|---|---|
| `database.py:generation_tasks.task_id` | `task_id` | Primary identifier; stores BOTH local IDs and API IDs at different life stages |
| `_merge_task_id_aliases()` | `task_id_aliases` | Request_data key storing all historical task IDs |
| `get_task_by_id()` | lookup by `task_id`, `id`, `task_id_aliases` | Three-level fallback |
| **Pattern**: Local `task_id` ("img_XXXX") is created → stored in DB → after API response, DB row is UPDATED to use API `taskId` → local ID moved to `task_id_aliases` | | |
| **Risk**: The overwrite of `task_id` from local to API value could cause a race condition if a webhook arrives before the UPDATE completes. The alias fallback mitigates this. | | |
| **Status**: Design is defensive; alias system works well. | | |

### 3. `model` vs `provider_model` vs `service`

| Layer | Name | Example Values |
|---|---|---|
| Handler (user-facing) | `img_service` | `"banana_pro"`, `"banana_2"`, `"wan_27"` |
| Routing helper | `_get_image_provider_model()` | `"nano-banana-pro"`, `"nano-banana-2"` |
| Service (hardcoded) | `payload["model"]` | `"nano-banana-pro"`, `"nano-banana-2"`, `"bytedance/seedance-2"` |
| DB | `model` column | Stored as handler model name (`"banana_pro"`) |

**Issue**: Three different model naming schemes in three layers. The `_get_image_provider_model()` function computes a provider name that is then IGNORED by the banana services (which hardcode the model). Only the routing decision is used.

**Fix**: Either (a) pass the provider_model from the routing function through to the service, or (b) remove `_get_image_provider_model()` and let services own their model names. Current: the function exists but its output is discarded for banana services.

### 4. `image` vs `image_url` vs `reference_image`

| Layer | Name | Type | Notes |
|---|---|---|---|
| Handler (TG) | `reference_images` | `list[str]` (URLs) | User-uploaded references |
| Handler (MiniApp) | `image_references` | `list[str]` (URLs) | Same concept, different name |
| nano_banana_pro_service | `image_input` | `list[str]` | Kie.ai format |
| nano_banana_2_service | `image_input` | `list[str]` | Kie.ai format |
| kling_service (2.5) | `image_url` | `str` (single) | Single image for img2vid |
| kling_service (3.0) | `image_urls` | `list[str]` | Multiple images |
| seedance_service | `first_frame_url`, `reference_image_urls` | `str`, `list[str]` | Differentiated by semantic role |
| **Risk**: Low. Naming inconsistency is confusing but functionally correct. | | | |
| **Recommendation**: Standardize on `reference_images` (list of URLs) across all handlers, with services mapping to provider-specific names. | | | |

### 5. `callback_url` vs `webhook_url`

| Service | Parameter Name | Kie.ai Payload Key |
|---|---|---|
| nano_banana_pro_service | `callback_url` | `callBackUrl` |
| nano_banana_2_service | `callback_url` | `callBackUrl` |
| kling_service | `webhook_url` | `callBackUrl` |
| seedance_service | `callBackUrl` | `callBackUrl` |
| veo_service | `callBackUrl` | `callBackUrl` |

**Pattern**: Three different parameter names. All map to the same Kie.ai `callBackUrl` payload key.  
**URL endpoints**: `/webhook/kling` (kling_service), `/webhook/kie` (banana/seedance/veo via `config.kie_notification_url`), `/webhook/kie-market` (nano-banana-2-lite via `config.kie_market_notification_url`). Three separate webhook endpoints handle the same JSON response from main.py:handle_kling_webhook().

**Risk**: If a wrong callback URL is passed, the webhook won't receive the result. Currently correct.  
**Fix**: Unify parameter naming to `webhook_url` in all services.

### 6. `status` — Provider vs Internal

| Provider (Kie.ai) | Internal (DB) | Translation |
|---|---|---|
| `"state": "success"` | `"completed"` | `complete_video_task(task_id, result_url)` |
| `"state": "fail"` | `"failed"` | `complete_video_task(task_id, None)` |
| `"state": "processing"` or `"queued"` | `"pending"` | initial DB insert |
| (Webhook code=200, taskId present) | `"completed"` | Kling direct format |

**Translation is correct across all three webhook formats.**

### 7. `cost` / `amount` — int vs float (CRITICAL)

| Location | Type | Notes |
|---|---|---|
| DB `generation_tasks.cost` | INTEGER | Stored as int |
| DB `users.credits` | INTEGER DEFAULT 0 | Stored as int |
| `deduct_credits(telegram_id, amount: float)` | float | Function signature says float |
| `add_credits(telegram_id, amount: float)` | float | Function signature says float |
| `get_user_credits()` returns | float | Returns `float` even though DB is INTEGER |

**BUG**: All credit operations use `float` signatures but the DB column is `INTEGER`. SQLite will silently truncate float values to integers on INSERT/UPDATE, but the in-memory comparison (`row["credits"] < amount`) with a float against an INTEGER could have floating-point precision issues. Additionally, if someone accidentally passes `9.5` for cost, SQLite stores `9`.

**Fix**: Change signatures to `int` throughout, or change DB column to REAL. Since banana costs are whole numbers, `int` is correct.

### 8. `duration` — seconds vs string

| Service | Handler Type | API Type | Notes |
|---|---|---|---|
| Kling 3.0 | int (5/10/15) | str ("5"/"10"/"15") | Converts via `str(duration)` |
| Kling 2.5 | int (5/10) | str via `str(self._safe_duration_25(duration))` | Same conversion |
| Seedance | int (5/10/15) | int (clamped 5-15) | Different! No string conversion |
| Veo | int (4/6/8) | int via `_normalize_veo_duration()` | No string conversion |
| **Inconsistency**: Two different types sent to Kie.ai for the same concept. | | | |
| **Risk**: Low — Kie.ai accepts both. | | | |

### 9. `aspect_ratio` — Format Consistency

| Source | Format | Notes |
|---|---|---|
| Handler default | `"1:1"` | `_default_image_flow_data()` |
| User input | `"1:1"`, `"16:9"`, `"9:16"`, etc. | From keyboard/selector |
| `_resolve_image_aspect_ratio()` | `"1:1"` normalized | Handles unicode `∶` → `:` |
| Banana services | `"1:1"` | Passed as-is |
| Kling `_safe_aspect_ratio()` | `"16:9"` default | Validated against set |
| MiniApp `_normalize_video_ratio()` | `"auto"` → `"auto"` special case | Auto for some models |
| **Consistent**: All use `"W:H"` format with `:` separator. | | | |

### 10. `seed` — Passed? Default?

| Service | Seed Supported? | Notes |
|---|---|---|
| nano_banana_pro | No | — |
| nano_banana_2 | No | — |
| kling_service | No | Kling API doesn't expose seed |
| seedance | No | — |
| wan_27 | **Yes** | `seed=random.randint(1, 2147483647)` — random per call |
| veo_service | **Yes** | `seeds: Optional[int]` — user-provided |
| gemini_omni | **Yes** | `omni_seed: Optional[int]` — user-provided |

**Risk**: `wan_27` generates a random seed but doesn't store it for reproducibility. The seed is sent to API but not saved to DB.

**Fix**: Store seed in request_data for reproducibility. Low priority.

### 11. `quality` / `resolution` — Consistency

| Service | Parameter Used | Values | Notes |
|---|---|---|---|
| nano_banana_pro | `resolution` + `img_quality` | `"1K"`, `"2K"`, `"4K"` | Alias `"BASIC"`→`"2K"`, `"HIGH"`→`"4K"` |
| nano_banana_2 | `resolution` + `img_quality` | Same | Same alias system |
| kling | N/A | — | No quality param for video |
| seedance | `resolution` | `"480p"`, `"720p"`, `"1080p"` | Video-specific resolution |
| veo | `resolution` | `"720p"`, `"1080p"`, `"4k"` | Different format (lowercase k) |

**Inconsistency**: Image models use `"2K"`, `"4K"` (uppercase with Kelvin-like suffix), while video models use `"720p"`, `"1080p"` (lowercase with p suffix). These are different dimensional scales — intentional but confusing.

---

## Summary of Issues Found

### Critical
None identified.

### Medium Severity
1. **`cost`/`amount` — int vs float mismatch**: DB uses INTEGER, function signatures use `float`. SQLite silently truncates. Affects all 5 flows.
2. **`user_id` fallback in webhook**: `_resolve_task_telegram_id` silently falls back to `user_id` (DB PK) when `telegram_id` is None. This could route notifications to the wrong user.
3. **Credit deduction before seedance upload**: If `_prepare_image_urls()` fails (missing local refs), task is blocked but credits may have already been deducted. Need to check call order.
4. **Avatar audio via `video_urls`**: `video_urls` semantically carries audio URL in avatar flow — confusing naming.

### Low Severity
5. **Inconsistent parameter naming**: `reference_images` vs `image_input` vs `image_urls` across handlers and services.
6. **`callback_url` vs `webhook_url` vs `callBackUrl`**: Three names for the same concept.
7. **`model` parameter ignored**: `_get_image_provider_model()` output ignored by banana services that hardcode their model.
8. **`duration` type inconsistency**: `str` for Kling, `int` for Seedance/Veo.
9. **`seed` not stored**: `wan_27` generates but doesn't persist seed.

### Cosmetic
10. **`generate_audio` → `sound`**: Naming inconsistency between handler and Kling 3.0 payload.
11. **`img_quality` → `resolution`**: Different names in handler vs service.
12. **`mode` → `motion_mode`**: Handler uses `motion_mode`, service uses `mode`.

---

## Recommended Fixes (Prioritized)

| # | Issue | Fix | Files to Change | Effort |
|---|---|---|---|---|
| 1 | Cost int/float mismatch | Change `deduct_credits` and `add_credits` signatures to `amount: int` | `database.py` | Low |
| 2 | `user_id` fallback bug | Remove fallback from `user_id` to `telegram_id` in `_resolve_task_telegram_id` | `main.py` | Low |
| 3 | Credit deduction ordering | Ensure credits are deducted AFTER service call succeeds (not before) | `handlers/generation.py`, `miniapp.py` | Medium |
| 4 | Unify callback/webhook param naming | Use `webhook_url` consistently in all service signatures | All `bot/services/*.py` | Medium |
| 5 | Store wan_27 seed | Add seed to `request_data` in `_start_image_generation_task` | `handlers/generation.py` | Low |
| 6 | Unify `model` param in banana services | Add `model` kwarg to `nano_banana_pro_service.generate_image()` | `nano_banana_pro_service.py` | Low |
| 7 | Rename avatar audio | Use `audio_url` instead of `video_urls[0]` in avatar flow | `handlers/generation.py` | Low |

---

## Test Recommendations

| Test | Priority | Description |
|---|---|---|
| Cost precision | High | Verify that `int(9.5)` cost stored as `9` doesn't cause billing errors |
| Task ID alias retrieval | High | Verify webhook finds task by alias when local_task_id → api_task_id swap happened |
| Webhook idempotency | High | Verify double-delivery of webhook doesn't double-notify user |
| Credit refund on failure | High | Verify credit refund on webhook failure matches original deduction |
| Seedance local upload failure | Medium | Verify credit refund when `_prepare_image_urls` fails |
| Model routing blocklist | Medium | Verify Grok image model sent to KlingService is rejected with error |
| Callback URL correctness | Medium | Verify each service receives correct webhook URL (kling vs kie vs kie-market) |
| Seed reproducibility | Low | Verify wan_27 seed can be reused from request_data |
| Duration type across providers | Low | Verify both int and str durations are accepted by Kie.ai |

# Kling 4 — administrator release

Kling 4 is available only to current administrators in Telegram and the Mini App. Use `/kling4` in Telegram or open **Создание видео → Kling → Kling 4** (also listed once in **Все**). It is not pinned above unrelated model families. Public rollout requires Igor's separate instruction; this release has no public billing path.

Provider contracts: [Reference](https://docs.kie.ai/market/kling/v4-reference-to-video), [Keyframe](https://docs.kie.ai/market/kling/v4-keyframe-to-video), [pricing](https://kie.ai/pricing), [task details](https://docs.kie.ai/market/common/get-task-detail), [webhook verification](https://docs.kie.ai/common-api/webhook-verification).

The two provider IDs are `kling-4.0/reference-to-video` and `kling-4.0/keyframe-to-video`. Duration 3–30 integer seconds; 720p/1080p. Reference supports up to10 images,5 videos,7 named elements (up to3 video characters),3 voices,15 combined materials,30 total input video seconds. Keyframe supports first/last and up to8 ordered intermediate frames, total <=min(10,duration+1). Changing duration never silently removes frames. Unknown fields and missing prompt tags fail before launch.

Provider rates per billed second (2026-10-22 snapshot): keyframe and reference without video 28.5/42.5 credits (720p/1080p); reference with video17/25.5. Paid smoke verified: select the video tariff only when ordinary `video_urls` are present. Sum ordinary clip durations, round the aggregate up to whole seconds, then multiply rate by output+max(ceil(sum(ordinary video)),output). Video elements count quota limits but do not select the video tariff or add billed input. Without ordinary video multiply the reference/keyframe rate by output duration. These are provider credits, separate from user bananas. Missing actual credits remain unknown. Model-generated audio is native; keep-original-sound is applicable only with ordinary reference videos.

Uploads reuse owned, bounded, inspected storage; external links must first be imported through SSRF-protected downloading. Product media profiles can be narrower than provider limits. Input byte identity, dimensions and measured durations are persisted. Original result is stored locally before task success. Telegram delivery is separate and retries without re-generation; large originals use download links.

Launch requires a current quote and stable idempotency key. Telegram resolves the measured quote internally when a prompt arrives; Mini App retains explicit quote confirmation. Ambiguous POST stays `unknown`, never silently retries or releases a supposed charge. Reconcile a known provider task ID through the authenticated admin recovery surface after verifying ownership/model remotely. Polling survives process restarts. HMAC does not authenticate callback body: provider GET is authoritative. This release uses polling and does not require an additional callback configuration.

Settings are versioned in the DB and edited through authenticated `/api/kling4/settings`; updates are audited. Defaults remain admin-only. Existing KIE environment credentials are reused. No real user balance is charged. A future public rollout must explicitly introduce/review retail billing and publication permissions before relaxing the server gate.

## Verified paid smoke — 2026-10-22

12/12 tasks succeeded; total1328.5 KIE credits ($6.6425), below2000 cap. Six tariff rows, video-element-only, mixed ordinary+element, fractional/multiple videos, missing-first keyframes and spoken WAV passed. Every output downloaded, SHA256+ffprobe checked (720p/1080p H264+AAC). See [structured evidence](kling4-live-smoke.json). Balance delta included230.5 credits of unrelated account activity and is not used as this ticket expense. Ratio precedence with differently sized keyframes and other audio profiles remain unverified; request acceptance alone is not proof of voice identity.

## Telegram navigation

The editor exposes direct aspect ratio choices (`auto`, `16:9`, `9:16`, `1:1`, `21:9`) and a **−1с / current duration / +1с** row bounded to 3–30 seconds. The main keyboard also exposes explicit **По референсам / По кадрам**, **720p / 1080p**, **Elements / Голоса** and applicable sound controls, plus **Очистить медиа** and **К моделям**. There is no Main Menu, prompt-entry, calculate or launch button. Each selected mode/quality/ratio is marked. The five ratios are the complete current KIE enum; `4:3`, `3:4` and `480p` from other models are not supported. With frame inputs KIE uses the first provided frame geometry. New drafts use 5s/720p/auto. Changing duration or ratio does not launch a task.

Send photos, videos, audio/voice messages or supported files directly; their type is inferred and owned storage validates the actual bytes. A direct media URL is imported through the existing protected downloader. Images become `@image_1`, etc.; videos become `@video_1`, etc.; standalone audio is assigned `@Voice1`, etc. A prompt message or media caption automatically obtains the current quote and launches once. Consecutive prompt fragments reuse the existing configured quiet window. Captioned albums also wait for pending uploads and the long quiet window; reference ordering follows Telegram message IDs, not upload completion. A failed, interrupted or unsupported upload blocks generation until successfully resent or cleared.

Reference mode is automatic by default. Explicit `@first_frame`, `@last_frame` or `@keyframe_N` prompt tags select frame mode from the ordered photos; mixed frame tags with video/voice references are rejected instead of silently dropping media. Frame limits and missing/unknown tags are still validated by the shared contract. New ordinary references switch a frame draft back to Reference, preserve the frame images in order, restore existing reference materials, and retain the frame draft for returning later. Named elements/voices are reachable from the main Telegram editor and remain available in Mini App. Create an element to open its card, then select its media field. Photo elements accept 2–4 views of the same subject, first image primary; Telegram album order follows message IDs and duplicate messages are ignored within the upload session. An explicit reorder remains in place when adding more images. New image elements leave the type unset for native inference; the type control cycles all supported categories and Auto. Video elements use one 3–8s character clip; voice and description fields remain available. Editing a field returns to the material card. Generated names are unique across elements/voices even after deletions.

Clear media resets the prompt/references while retaining duration, quality and ratio; it invalidates pending captions/uploads. Leaving for the catalog releases the input FSM and ignores late uploads. Returning starts a new editor session. Exact message receipts deduplicate redelivery; prompt fragments and media are ordered by Telegram message IDs even when handling starts out of order. Stable message-based launch keys and durable intent handling prevent duplicate creates. Old prompt/quote/confirm buttons simply show the automatic editor; a prompt field persisted by an older deployment enters the same upload-readiness pipeline. Server-side admin checks remain required. Legacy material/history/recovery callbacks retain parent/catalog navigation without a Main Menu button.

Repeating a saved Telegram task also starts a fresh intake session. Pending uploads/captions from the replaced draft cannot attach to or launch the restored recipe. The restored task's parameters and references remain intact until a new prompt is sent.

## Reference binding and KIE Agent audit — 2026-10-23

The official [kie-models skill](https://docs.kie.ai/ai-agent/install-kie-models) was used to read the live Kling catalog and both model schemas. Model IDs, create path, input fields and defaults match this integration. The [reference API](https://docs.kie.ai/market/kling/v4-reference-to-video) binds `@image_1`, `@image_2`, etc. to `image_urls` in array order; videos use `@video_1`, etc. Elements and voices use their declared `@name`. Frame mode uses `@first_frame`, `@keyframe_N`, `@last_frame`.

Telegram displays the actual loaded tags as text without additional buttons. Mini App retains its canonical material tag chips. Give each reference its intended role in the prompt, for example: `@image_1 задаёт внешность девушки, @image_2 — внешность мужчины. Они стоят рядом и смотрят в камеру.` This describes binding, not a guarantee of visual similarity.

The shared server validator accepts copied `@Image1`/`@Image2`/`@Video1` notation and canonicalizes it for KIE only when the corresponding numbered asset exists. Exact named materials keep their meaning; a case variant colliding with an existing custom name is rejected rather than silently bound to an ordinary image. Unknown/missing references and frame-mode mismatches remain errors before submission. The normalized prompt also obeys the 8000-character provider limit. The original request remains unchanged for durable idempotency; the prepared snapshot records the exact canonical provider prompt.

Read-only runtime verification found the stored reference image/video order and prompt identical to KIE's existing-task echo. No paid comparison was performed, so this audit does not establish the cause of any particular face-similarity result. No identity instructions are injected, media grouped into characters, or provider modes changed speculatively.

Original-sound controls preserve or omit the input video audio only when ordinary reference videos exist. Without them the button explains native audio generation and adds no unsupported audio field. Explicit mode/quality callbacks are validated, repeat selection is stable, and older toggle callbacks remain compatible.

## MOV reference preparation — 2026-10-23

Kling quote/launch now prepares owned MOV clips as MP4 before applying the KIE contract, including existing Telegram drafts and Mini App requests. The original file and recipe remain unchanged; the provider snapshot uses the prepared MP4. Preparation remuxes video and optional audio with stream copy (no re-encoding or trimming), checks measured duration/dimensions, and saves through the existing owner/quota-protected media storage. A per-owner/content lock bounds concurrent preparation; repeated quotes reuse the verified stored copy. Failed or timed-out preparation does not create a provider task. Video element and ordinary-reference duration limits remain distinct and enforced.

### Repeat retention after MOV preparation

Unused-media cleanup checks both `kling4_intents.recipe` (original input) and
`kling4_intents.snapshot` (prepared provider input), in addition to existing task,
trend and saved-reference checks. This protects existing and future ordinary MOV
references and video elements without rewriting historical recipes or requiring
a backfill. All intent states retain their inputs: private, failed and unknown
jobs can still be restored by the owner. Retention is not a grant of access;
owner/admin checks and original-file verification before cached MP4 reuse are
unchanged.

Only a genuinely absent Kling intent table is optional. Table-discovery or
reference-query failures abort cleanup before unlinking the affected candidate.
Unreferenced uploads still expire under `WAN3_UNUSED_MEDIA_TTL_SECONDS`; protected
media continue to count toward storage quotas. The configured production TTL and
actual historical file loss have not been verified. This prevents future cleanup
of existing referenced files; it cannot recover files already removed.

Regression coverage in `tests/test_kling4_mov.py` ages synthetic uploads, runs
paged cleanup, restores the original owner recipe, quotes and launches a repeat
through a fake transport. It also covers intent-only snapshots, malformed/failed
lookups, absent schemas and unrelated orphan cleanup. Focused verification at `e714f275`: 22 tests passed (19 MOV and 3 existing
retention tests) using Python 3.12.14, FFmpeg 7.1.5, isolated SQLite and fake
provider transport. The isolated runner disables plugin autoload, clears the
environment, substitutes only the eager services package initializer with a
namespace package, and blocks network, PostgreSQL imports and forbidden-file
access before loading the unchanged modules/tests. No guard violations occurred.
Ruff and compilation passed for the two changed Python files. Replaying the
done/ordinary regression against baseline retention failed because cleanup
removed the original as well as the orphan; restoring the fix passed.

The focused results above do not substitute for full CI or production validation.
The owner subsequently authorized the existing automated CI tests for this PR,
including read/import of the PostgreSQL adapter without modifying it, and release
only after mandatory checks are green. A follow-up commit resumes normal CI
without changing workflows or protections. Local adapter access remains
prohibited. Keep the PR draft until the genuine required checks and review pass;
then use the normal protected merge and exact-SHA deployment pipeline.

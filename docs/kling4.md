# Kling 4 — administrator release

Kling 4 is available only to current administrators in Telegram and the Mini App. Use `/kling4` in Telegram or choose Kling 4 in the video catalog. Public rollout requires Igor's separate instruction; this release has no public billing path.

Provider contracts: [Reference](https://docs.kie.ai/market/kling/v4-reference-to-video), [Keyframe](https://docs.kie.ai/market/kling/v4-keyframe-to-video), [pricing](https://kie.ai/pricing), [task details](https://docs.kie.ai/market/common/get-task-detail), [webhook verification](https://docs.kie.ai/common-api/webhook-verification).

The two provider IDs are `kling-4.0/reference-to-video` and `kling-4.0/keyframe-to-video`. Duration 3–30 integer seconds; 720p/1080p. Reference supports up to10 images,5 videos,7 named elements (up to3 video characters),3 voices,15 combined materials,30 total input video seconds. Keyframe supports first/last and up to8 ordered intermediate frames, total <=min(10,duration+1). Changing duration never silently removes frames. Unknown fields and missing prompt tags fail before launch.

Provider rates per billed second (2026-10-22 snapshot): keyframe and reference without video 28.5/42.5 credits (720p/1080p); reference with video17/25.5. Paid smoke verified: select the video tariff only when ordinary `video_urls` are present. Sum ordinary clip durations, round the aggregate up to whole seconds, then multiply rate by output+max(ceil(sum(ordinary video)),output). Video elements count quota limits but do not select the video tariff or add billed input. Without ordinary video multiply the reference/keyframe rate by output duration. These are provider credits, separate from user bananas. Missing actual credits remain unknown. Model-generated audio is native; keep-original-sound is applicable only with ordinary reference videos.

Uploads reuse owned, bounded, inspected storage; external links must first be imported through SSRF-protected downloading. Product media profiles can be narrower than provider limits. Input byte identity, dimensions and measured durations are persisted. Original result is stored locally before task success. Telegram delivery is separate and retries without re-generation; large originals use download links.

Launch requires a current quote and stable idempotency key. Ambiguous POST stays `unknown`, never silently retries or releases a supposed charge. Reconcile a known provider task ID through the authenticated admin recovery surface after verifying ownership/model remotely. Polling survives process restarts. HMAC does not authenticate callback body: provider GET is authoritative. This release uses polling and does not require an additional callback configuration.

Settings are versioned in the DB and edited through authenticated `/api/kling4/settings`; updates are audited. Defaults remain admin-only. Existing KIE environment credentials are reused. No real user balance is charged. A future public rollout must explicitly introduce/review retail billing and publication permissions before relaxing the server gate.

## Verified paid smoke — 2026-10-22

12/12 tasks succeeded; total1328.5 KIE credits ($6.6425), below2000 cap. Six tariff rows, video-element-only, mixed ordinary+element, fractional/multiple videos, missing-first keyframes and spoken WAV passed. Every output downloaded, SHA256+ffprobe checked (720p/1080p H264+AAC). See [structured evidence](kling4-live-smoke.json). Balance delta included230.5 credits of unrelated account activity and is not used as this ticket expense. Ratio precedence with differently sized keyframes and other audio profiles remain unverified; request acceptance alone is not proof of voice identity.

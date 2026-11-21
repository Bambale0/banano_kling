# 2026-11-21 — Blank newly published video Trend thumbnail

## Evidence and reproduction
- Runtime host tanyapi bot image revision at inspection: `380a70c5350431c2229f9fc9d65eb8101530d894`.
- Public example `/uploads/trend-previews/179526/a82a32c9078934fa5a38e93c.jpg` returned 200 image/jpeg. Original 480×854 JPEG had luminance mean 70.6 (range 1..244); the poster itself was not wholly black.
- Matched compact MP4 returned 307 to signed `s3.ru-1.storage.selcloud.ru` (browsers may not reach the endpoint). Client-network trace was not available, and the sample has not been attributed to a specific user's new post.
- `LivePreview` always rendered a full-size `<video>` after its JPG, allowing the video layer to occlude the JPG while stalled, blocked or loading. Earlier tests only covered original MP4s (which never got the video tile), not compact MP4s.
- Regression test asserts a new compact MP4's video is visually hidden before playing, visible during playback, hidden again when paused, and removed on failure while JPG stays present. Before the fix the initial `opacity-0` assertion would fail.

## Scope and fix
- Frontend-only. Make video layer transparent until its actual `playing` event, and hide again on pause, empty, error, viewport exit, hidden document or preview replacement.
- Keep successful compact preview autoplay, 2-video limit, same-origin JPGs, originals in full-screen dialogs, lazy loading and all existing prices/auth/publishing logic unchanged.
- Avoid proxying arbitrary MP4s through backend (cost/security concerns); signed MP4 may still fail but users keep a working JPG fallback.

## Verification plan
1. Focused Jest and TypeScript/ESLint.
2. Protected CI: Python/deploy, safe regression, browser E2E, production Docker.
3. Native squash auto-merge into tanyapi only when green.
4. Verify exact production SHA/backend/frontend, same-origin JPG HTTP 200, MP4 307 fallback user-facing tile, browser smoke and logs.

## Risks
- End-user Telegram WebView playback and the identity of the latest user-published trend still require client-specific verification.
- Signed MP4 redirect remains in place; this fix preserves the poster rather than solving direct S3 reachability.

# Video repeat modal disappears while source video loads

Date: 2026-11-20. Target: tanyapi only.
Reported evidence: IMG_1184.MP4 (50-second iOS Telegram recording).

## Reproduction and verified root cause

A feed post's video opens in an in-app fullscreen preview. Its media element
uses preload=auto, and onError directly invoked dismissPreview(). A CDN media
error can arrive seconds after the modal is opened; that callback removes the
entire modal and its Repeat button. A quick tap succeeds before the media error,
while waiting returns the user to the feed. This is UI navigation behavior, not
proof that a provider generation failed or a payment was charged.

TDD red command: cd frontend/miniapp-v0 && ./node_modules/.bin/jest
--config jest.config.ts --runInBand
components/tabs/__tests__/feed-video-repeat.test.tsx

Before fix, the new delayed media error test fails because Repeat no
longer exists. Existing normal repeat tests pass.

## Fix and invariants

- A failed preview media GET now marks that preview item unavailable and
  displays a small fallback explanation, not a navigation/close event.
- Repeat remains enabled and is still resolved from the server-fed recipe
  metadata; no author-hidden media, private prompt, or reference permissions
  are changed.
- Opening a new preview resets the old transient media error. An explicit
  close still cancels an unfinished repeat hydration.
- Applies to video AND image preview, including after lazy media failures.
- No provider API calls, charge, database mutation, or media archive migration.

GREEN: targeted video + image repeat tests 6/6; TypeScript and ESLint passed.
Production merge and exact-SHA smoke remain required. Do not claim media CDN
availability was fixed: this patch is resilient when media fails.

# Trend viewport loading: production acceptance (2026-11-17)

Base `tanyapi` SHA: `586cb93be84a98e3e5133995a85bab02f784ef5a` (#597).

## Confirmed root cause and acceptance

- Live catalog had 91 cards lacking compact posters even after switching media storage to Selectel S3 with local cache disabled. Frontend attached video original URLs while browsing tiles; full MP4/PNG downloads competed with app startup and WebView decoding.
- The #597 production backfill ran in three bounded, resumable batches: 5 + 35 + 51, all created, zero failed. A subsequent read-only scan reported `total_visible=0`; 91 durable source/poster mappings exist. Sample poster returned HTTP 200 `image/jpeg`, 8,780 bytes. Originals were not modified or removed.
- This PR cleanly ports only the frontend portion of the earlier #596 onto the released #597 base. Grid uses compact poster JPG where available, suppresses full MP4/legacy extensionless video until an explicit click; the dialog retains original video. Photos prefer compact poster with original fallback.
- Lazy viewport gate uses `IntersectionObserver` with `rootMargin: 240px 0px`: no image or video DOM media until near viewport. Native image lazy loading and async decode remain. Unsupported IntersectionObserver falls back to loading normally for backward compatibility; independently visible grid preview video playback still pauses offscreen and respects reduced-motion/data-saver.
- No backend API/schema, tariffs, payments, owner privacy, provider, domain, auth or VK contour changes in this PR.

## TDD and checks

- Reproduced failing Jest regression: offscreen tile eagerly attached JPG before intersection; after patch the same test is green.
- Focused 5/5 Jest pass, TypeScript and ESLint pass, Next.js 16.4.2 static production build passes.
- Real local Chromium mobile category showcase browser E2E passes with original video only in dialog and repeat/admin/category flows preserved. Fixture assertions updated for the deliberate media contract, not skipped.
- Security dependency audit and protected GitHub CI remain required before merge; exact backend/static SHA, browser smoke and asset HTTP verification required after deploy.

## Rollback

Revert the frontend PR; the additive 91 S3 poster objects and mapping manifest may remain. No local storage purge.

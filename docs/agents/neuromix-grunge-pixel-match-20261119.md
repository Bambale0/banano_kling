# NEUROMIX — pixel-match grunge landing (2026-11-19)

## Task / acceptance
Replicate the exact user-approved 1672 × 941 grunge hero from the rendered reference image: weathered black paper, torn brushstrokes, plaster bust, gold and cyan collage, large condensed copy, links that work. Preserve all eight factual marketing sections, the existing Telegram Mini App and auth, and existing financial integrations.

- **Reference artwork**: AI-rendered image chosen by the user in this conversation, source SHA-256 `1a97ac971b0327882e5311ce1dbee91c7bb2ef0d6fca2e9e5954b3719092ee04`.
- **Desktop**: encoded pixel-accurate background `web/landing/grunge-hero-v1.webp`, 1672×941, quality 90 (461 KB), Git blob `c06789916224649c68f14c1a7b947ebaf072f4eb`. The screenshot itself is the full poster; links are semantic, keyboard-focusable transparent hotspots over the pictured controls.
- **Mobile**: cropped original-art poster `web/landing/grunge-mobile-art-v1.webp`, 975×719, quality 86 (190 KB), Git blob `82e04b03825bdb8312c74678b2895d6b85f7d443`, live typography and mobile first-fold CTA. Existing lower sections use grunge-specific CSS overrides, no new JavaScript dependencies.
- **Authenticated entry**: all working entry buttons go only to `/mini-app/` (existing browser Telegram auth). Other OAuth providers remain labelled as future availability; no fabricated identity or wallet state.
- **Legacy Telegram deep links**: root entries with `tgWebAppData`, `tgWebAppStartParam`, `startapp` etc keep forwarding unchanged to `/mini-app/`.

## Release and isolation
- New files under `web/landing`. Publisher `scripts/deploy_landing_local.sh` atomically installs both assets into **isolated** `/var/www/neuromix-landing` with rollback; no writes to symlinked `/var/www/neuromixbot.com` shared with Mini App.
- Nginx adds only two **exact** static asset routes, with 1-day Cache-Control and MIME `image/webp`; all Mini App/API routes unchanged. No static fallback to the app.
- Publisher's Nginx modification is safe for the original (3 public routes), existing (5 public routes), or legacy redirect; unknown vhost shape fails closed.
- Deployed assets are checked from public Cloudflare and origin by HTTP 200 and `image/webp` before marking success; Mini App exact revision verified.
- `AGENTS.md`: task branch → protected PR to `tanyapi` → all checks → auto-merge → production exact SHA → smoke.

## Verification completed (not equivalent to production verification)
- **Visual**: Headless Chromium at 1672×941 against exact source reference; mean per-channel absolute pixel error **2.3646 / 255**, due to perceptually compressed WebP. This verifies the actual desktop first screen **1:1** (not a CSS approximation).
- **Browser**: 320/360/390/768/1200/1672 px, no horizontal overflow. Mobile primary CTA above first fold, one-line at 320–390; all anchors present, 11 links to existing `/mini-app/`, no JavaScript exceptions. Scroll-triggered sticky CTA tested as invisible/inert on top and visible on scroll.
- **Contracts**: 16/16 `tests/test_public_landing.py`; both Bash deploy scripts pass `bash -n`.
- **Nginx dry run**: extracted updater applied to copy of actual live vhost twice; second pass idempotent, each asset location exactly once, existing `/mini-app/` route preserved.
- **Git content integrity**: uploaded WebP Git blob hashes exactly match `git hash-object` on binary source files.

## Not claimed
The live marketing site is **not** updated until current commit is merged to `tanyapi`, the production deploy is completed, and the public screenshot plus asset/health checks pass. The source reference is a generated **marketing concept**, not a claim about a real user image/video produced by NEUROMIX.

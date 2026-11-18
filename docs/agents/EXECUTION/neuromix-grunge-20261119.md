# NEUROMIX — reference-matched grunge landing (19.11.2026)

## Scope and evidence

- **Request:** implement the user-approved 1672×941 grunge reference as the real public landing at `https://neuromixbot.com/`, preserving all eight marketing sections and the working Mini App at `/mini-app/`.
- **Baseline:** `tanyapi` at `435dd6b8c8d623bf35f357e13d388dea7c7b1166`; task branch `feature/neuromix-grunge-reference-20261119`.
- **Design inputs:** exact approved source image (`neuromix_идеи_в_фото_и_видео.png`, 1672×941) and styles in `frontend/miniapp-v0/app/globals.css`. Applied `anthropics/skills/frontend-design` and `Bambale0/.agents` anti-ui-slop.
- **User journey:** public marketing root → functional `/mini-app/` CTA → existing browser Telegram auth. No fake Google/Yandex/email login, no unrelated VK or payment changes.

## Reproduction, findings, fixes

1. Previous public page used editorial cards and smooth colors, unlike distressed reference. Preserve the real page's semantic HTML and eight marketing sections, replace mast + hero + categories with collage/letterpress/stencil composition while maintaining working links.
2. Cropped approved right-side bust/photo/film collage from 3.12MB RGB reference to WebP 850×640, ~94KB; feathered left/bottom transparent seam so baked secondary CTA text from reference cannot leak into the live UI. `grunge-collage.webp` stays a decorative local resource, no external CDN.
3. Gallery asset routing: production Nginx root is symlinked for Mini App. Image goes only in isolated `/var/www/neuromix-landing`, with exact `location = /grunge-collage.webp`. Deploy publisher now stages and backs up image with HTML, changes Nginx surgically, verifies WebP header, GET 200 origin/public and byte-for-byte identical image; rolls back on errors.
4. Chromium revealed a real CSS specificity regression: existing `.intro h1 span` made white text gold, painted `ИДЕИ` unreadable, and moved handwritten `В` onto its own line. Added scoped `.grunge-intro h1...` overrides and a dedicated regression test.

## Acceptance

- Header pulse monogram, textured black stock, golden ripped strip, white condensed headline and painted `ИДЕИ`, handwritten connector, torn photographic collage, brushed golden CTA, four-function strip.
- 8 existing below-fold marketing sections remain factual, FAQ works, Telegram deep links with `startapp` bypass marketing and retain parameters.
- Browser tests on 320, 390, 768, 1280 and 1672 widths; no horizontal overflow, first CTA above fold at mobile widths, no JavaScript exceptions, real 850px image decode; color/layout geometry verified in computed style and screenshot.
- Full existing landing regression tests plus new image-route and typography tests; Bash syntax validation for both deploy scripts.
- **Release gate:** task branch PR → protected `tanyapi` CI (four required gates) → exact production SHA smoke for `/`, `/grunge-collage.webp`, `/mini-app/`, `/mini-app/api/browser-auth/config`. Do not state live/grunge until observed.

## Non-goals/risks

- Existing Mini App and backend untouched.
- Reference itself depicts labels inside decorative artwork; the functional CTA/navigation remains actual selectable HTML, not an image map.
- Static image is ~94KB and cacheable for one day; first visit on slow networks may show dark art area briefly before decode, but all calls to action remain independent and usable.

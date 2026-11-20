# 2026-11-20 — Telegram portrait 9:16 trend preview safe area

## Scope and baseline
- Branch: `fix/telegram-trend-portrait-safe-area-20261120` from `tanyapi` SHA `8be8af25661f90656ed7b5abae6af0a0da8ccad2`.
- Symptom: on Android Telegram Mini App, long portrait trend preview starts beneath native "Закрыть" controls; title/close overlap and the portrait media/CTA overflow.
- Reproduction: user screenshot of 9:16 trend; original component uses fixed viewport-center, `max-h-[92dvh]` and a tall `max-h-[60dvh]` video, no Telegram safe-area bounds.
- Hypotheses: (1) full viewport centering ignores native top bar (supported by code); (2) 9:16 media expands modal height (supported by screenshot and CSS); (3) incorrect Telegram inset reporting (possible on older WebViews, not verified).

## Changes
- Bound the preview dialog within dynamic Telegram safe-area variables with a conservative mobile fallback for WebViews reporting zero.
- Keep title and close icon outside a dedicated independently scrolling media/action region.
- Cap portrait preview to `52dvh`; preserve original media URLs, video controls, repeat/sharing callbacks, pricing and admin actions.
- No API, DB, provider, price, payment, or config change. No migration.

## Regression and verification
- React Testing Library test asserts fixed header, scroll region, 9:16 video and both user actions.
- Playwright catalog test simulates mobile 375x640 and Telegram top 80px/bottom 28px insets; asserts dialog/close geometry and accessible Share action.
- Required release gate: focused Jest, Next.js TypeScript/ESLint/build, browser Playwright E2E, four protected GitHub checks, squash auto-merge, exact production SHA and live mobile smoke.
- Limit: simulator does not prove behavior on the user's Android Telegram client; verify that separately after deployment.

## Rollback
- Revert the task PR or its merge commit. CSS and component changes are isolated and contain no persistence migration.

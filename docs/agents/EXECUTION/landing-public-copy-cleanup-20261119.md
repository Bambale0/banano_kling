# Public landing and login: customer-facing copy audit (2026-11-19)

## Scope and baseline
- Base tanyapi SHA at task start: 57c708c04d019282f6bfaf0c717f5dad01ff0982.
- Public routes: / (isolated static marketing), /login and /login/ (shared Next export).
- /mini-app/ authenticated studio, payment and referral logic explicitly excluded.
- Goal: remove internal technical copy and inert provider previews without breaking auth.

## Findings and changes
- Marketing copy exposed implementation jargon: prompts, modes, statuses, server-auth linking.
- The login showed not-yet-working Google/Yandex/email tiles and low-level OIDC status messaging.
- Reword all eight marketing sections and login as customer-focused benefits and simple actions.
- Remove non-functional provider previews. Keep an honest FAQ: Telegram is currently required.
- Preserve native Telegram deep link bypass, signed legacy widget, referral pass-through to /login.
- Preserve approved grunge artwork, real pricing entry, accessible FAQ and all CTA targets.

## Tests
- Red test verified prior to fix.
- Python public landing + browser auth + Telegram OIDC: 39 passed.
- Next static export build passed in isolated worktree.
- Playwright login/landing E2E passed at 320/390/768/1440 widths.
- Payment return-to, referral context, inactive OIDC fallback, login CTA validated.
- git diff --check passed.

## Release
- PR to protected tanyapi; native squash auto-merge after required four checks.
- Verify production SHA, root and login HTTP, CTA routing, public customer copy and Telegram API.
- No secrets, external provider config, user data, payment, balances, or other domains touched.
- OAuth PR #626 not included: first-class independent web actor is not yet ready.

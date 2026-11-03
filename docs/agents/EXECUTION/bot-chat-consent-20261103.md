# Bot chat consent — 2026-11-03
Baseline: 4104831b8c75430f97a7318b402dc2863f79cc6d (tanyapi).

Outcome: visible, clickable optional delivery offer opens text bot /start preserving referral attribution. Delivery remains server-confirmed.

Preflight: existing real target=_blank t.me /start link, bootstrap getMe bot username, lifecycle never_started and idempotent referral service are reusable. No schema/config/provider/payment changes required. Existing trend/Genjutsu deferral misses other Radix modals.

1. Reproduced on deployed export with synthetic APIs: open Services → Support; capability refresh returns never_started. Gate appears over Radix sheet while body pointer-events=none. temporary minimal browser repro failed (1 !== 0); permanent regression added to e2e/bot-start-gate.mjs. Ordinary bot-start baseline passed at 320/375px, confirming missing modal interaction coverage.
2. Fix in progress: defer optional offer while any shared Radix dialog/sheet owns pointer/focus, including exit animation. Keep original launch URL and /start referral. Include recipe referral attribution without replaying recipe actions.
3. Verification planned: failing browser repro → fixed export Chromium/WebKit; existing gate unit/browser tests; referral lifecycle backend regressions; lint/build; exact-head CI and automatic release.

Observability: existing bootstrap capability and /start logs remain authoritative; no client-side access grant or outbound bot messages in tests.
Guidance applied: Bambale0/skills diagnosing-bugs, Bambale0/claw frontend audit, anthropics/skills webapp-testing; wondelai UX heuristics.

Progress: gate defers for mounted Radix dialog/sheet/alert-dialog; watches DOM ownership and restores offer after unmount. Recipe referrals now use the same safe ref_ payload as other entry points. Unit: 36 passed. Production build passed. ESLint: 0 errors, one pre-existing kling4-form exhaustive-deps warning. Added actual popup URL assertion after Support closes and wired Chromium/WebKit consent browser checks into Mini App E2E CI. Backend tests exercise /start twice with referral attached before/after entering chat, assert single referral and unchanged credits.

Backend verification: 77 passed (bot start eligibility including two real DB referral lifecycle cases, write access, referral system, trend referral links); ruff passes. WebKit cannot launch on the production host because required OS libraries are absent; no host packages were changed. WebKit runs in CI with installed browser dependencies. No real Telegram sends, paid generations, schema or production data writes were used in verification.

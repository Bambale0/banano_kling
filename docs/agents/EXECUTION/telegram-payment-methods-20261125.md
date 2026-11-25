# Restore checkout across Telegram and website

Baseline: a3164ebc (tanyapi), 2026-11-25. User explicitly accepted Telegram platform restriction risk and requested retaining external methods inside Telegram after the Stars-only policy was explained. Official policy: https://core.telegram.org/bots/payments-stars . This implementation must not be described as Telegram-compliant.

Preflight: providers and checkout FSM already exist. The redirect was enforced by inbound/outbound Telegram middleware, API platform policy, frontend openBalance, payment API and balance sheet filtering. Existing open PR #646 covers independent web commerce; do not enable its wallet gates or mix independent web wallets with Telegram balances. This task preserves linked Telegram wallet ownership. No migration, pricing, credentials or provider changes.

Invariants: signed initData/server auth, transaction owner, config prices, webhook validation, provider confirmation, atomic completion and referral antifraud remain in existing services. Stars root settlement registration remains ahead of generic FSM handlers. Native Bot API invoices remain XTR-only; external methods open their hosted checkout URLs.

Plan: (1) regression tests for direct callbacks and UI; (2) remove forced website handoffs; (3) run payment, settlement, owner and webhook suites plus frontend tests/build/browser E2E; (4) PR to tanyapi with protected auto-merge; (5) verify exact CI/release SHA and production smoke or explicitly report limits.

Playbooks inspected: Bambale0/skills diagnosing-bugs (regression-first diagnosis); Bambale0/claw docs/agents/ACTIVE_AGENT_RULES.md (backend authority, transaction/idempotency); anthropics/skills webapp-testing (browser state and explicit waits). This is a requested routing behavior change; no provider redesign is needed.

Progress: tests changed before implementation; local tooling preparation in progress.

Rollback: revert this PR, restoring website-only routing. No data changes to undo. Production telemetry and live payment tests require verified runtime access; do not infer them from local fixtures.

Verification progress: regression-first run reproduced 20 redirect failures (plus Windows lacks resource for existing main-dispatcher test). After implementation: 35 routing/API tests passed (1 dispatcher test deselected locally); 60 focused payment/web settlement/Lava tests passed; 42 frontend payment tests passed. New HTTP cases exercise actual Mini App payment endpoint with server-owned actor and configured price despite forged client owner/amount/credits. Initial build compiled and typed successfully but Next emitted a security-advisory stop after export; retrying without changing dependencies. SSH runtime audit attempted: publickey/password authentication denied, so no production logs/config/deployed SHA asserted. Branch protection verified strict=true with all four required gates.

Further verification: 82 existing payment/referral/owner/privacy checks passed; TypeScript noEmit passed, scoped ESLint has zero errors and one existing app-context useCallback warning. Ruff and diff whitespace check passed. Frontend payment tests: 42/42. Browser E2E now covers native TG fiat checkout and browser/webstudio checkout as well as native Stars. The existing root dispatcher test requires Linux resource module and is retained for Linux CI. No new flags or migrations; provider availability and prices remain existing configuration.

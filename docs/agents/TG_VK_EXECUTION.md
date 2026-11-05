# TG–VK shared accounts execution ledger

Parent plan #408; E1 #409. Isolated branch:
feature/tg-vk-identity-preview-20261105.
Baseline tanyapi@03a9918db303b8ac075115fde8cbccecf6d10aeb.

## Constraints

- Implementation authorized 05.11.2026; no production merge or deployment until
  the complete feature is finished. Draft PR, auto-merge off.
- New behavior must be restricted to administrators on the server. Defaults off.
- Production balances, references, existing runtime price configuration and
  provider routing are untouched. No production schema migration.

## Preflight

- Re-read project instructions, release workflow, browser auth, Mini App
  bootstrap/profile, shared DB adapter and tests. Origin tanyapi equals baseline.
- Existing Telegram/VK account/wallet architecture audited in #408. Separate
  identity/session/wallet tables absent; schema drift must precede money cutover.
- Reuse bot_settings for typed administrator controls; exact HTTP routes before
  the existing catch-all; existing own-profile screen for admin-only UI.
- Source identity is platform-scoped. Existing Terraform/cloud/admin security
  is not relaxed, and no fake Telegram user is created for VK.
- Guidance: Bambale0/skills implement/tdd; prior Bambale0/claw QA checklist;
  anthropics/skills inspected, browser UI verification applies to later E2E.

## Steps and evidence

1. [x] Pin baseline and create isolated worktree; preserve production checkout.
2. [x] RED admin-only HTTP tests: missing module on baseline. Initial guard GREEN:
   3 passed; signed-session/VK tests RED: 5 failed, 4 passed before implementation.
3. [x] Implement typed preview policy, source-scoped auth, accounts and revocable
   hashed sessions; legacy credits untouched. Initial signed-session GREEN: 9 passed.
4. [x] Add admin UI controls and exact route wiring. UI RED on absent API/component.
5. [x] SQLite + isolated PostgreSQL HTTP/security/concurrency matrix and adjacent
   browser-auth/audit checks: final 57 passed. Policy revision binds sessions;
   disable/re-enable regression RED on both engines, GREEN after fix. Review
   follow-up adds tamper/stale/future/duplicate/unsigned Telegram launches on both
   session and settings routes, plus equal cross-platform IDs.
6. [x] Full backend safe suite before final narrow security additions: 4641 passed,
   121 skipped, 76 subtests. Full frontend: 82 suites / 647 tests passed; final new
   UI/API focused checks: 8 passed. Ruff, ESLint, TypeScript, compileall, diff
   whitespace and final production build passed. New Chromium browser check
   passes ordinary/admin at mobile 430px and desktop 1280px. General critical-flows
   attempt timed out at 210s and is NOT counted as passed. Its existing CI remains
   required; the new browser scenario is also wired into Mini App Browser E2E.
7. [x] Independent Standards review: no blocking findings. Spec review: missing
   negative Telegram launch tests; added and reviewer confirmed resolved. Initial
   implementation committed as 15084a0e; follow-up regression/CI commit pending.
   Draft PR and no production merge/deploy remain mandatory.
8. [ ] Push final branch, open Draft PR, verify auto-merge remains off, and record
   exact SHA/check status in #408/#409. All epic descriptions now reflect the user
   restriction: implementation allowed, production merge/deploy held until complete.

## Risk and rollback

Preview schema is additive and lazy. Default-off leaves existing routes alone.
Rollback removes branch code; preview data can remain isolated. Do not deploy to
test it in production. General wallet/account-merge rollback is a separate E8
concern and must not restore independent writable legacy wallets after cutover.

## Remaining work

No common wallet, magic-link merge, public VK bootstrap, generation parity,
delivery, referrals or production rollout is complete in this first slice.
App-cabinet credentials/settings and migration policy decisions remain external
prerequisites. Complete feature acceptance follows #408, not this initial PR.

## Draft publication and CI follow-up

Draft PR #415 opened, not merged. Initial exact-head CI found an import-order
error in the existing browser_auth import block; corrected without behavior
changes and reproduced the repository changed-line gate. Full production
release hold is unchanged.

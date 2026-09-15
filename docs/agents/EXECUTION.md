# Execution ledger

## 2026-09-15 — payment provider priority

- Baseline: tanyapi @ ac4f35c7c6f5.
- Intended result: Robokassa is the first/default visible RUB option and is labeled СБП / карта; FK Kassa is second and explicitly marked reserve; Lava is moved below the primary/reserve and alternative methods.
- Existing state: backend config already selects Robokassa as primary, but Telegram and Mini App UI plus regression tests still encode Lava-first / Robokassa-reserve behavior.
- Scope: presentation/routing order only. Provider webhook validation, transaction creation, amounts, bonuses, idempotency and crediting are unchanged.
- Surfaces: Telegram flat payment menu, legacy provider keyboards, Mini App balance sheet, E2E/static regression contracts.
- Risk: duplicate choose_pay handlers make router order important; the production flat menu is owned by lava_checkout and decorated by miniapp_lava_payment_methods_compat.
- Test plan: first update regression expectations and confirm RED, then implement order/labels, run focused pytest, Mini App E2E/build checks, review diff, CI, merge to tanyapi, verify exact deployed SHA and production smoke/logs.

- RED evidence: focused contract suite initially failed 9 assertions on the old Lava-first / Robokassa-reserve ordering.
- Implementation: Telegram flat menu, legacy reserve keyboards, Mini App balance UI and E2E were aligned to Robokassa → KASSA reserve → alternatives → Lava.
- Documentation: robokassa.md and freekassa.md now describe the same verified priority.
- Verification so far:
  - focused Python payment contract suite: 57 passed;
  - Ruff on all changed Python/test files: passed;
  - Mini App Jest: 17 suites / 46 tests passed;
  - Mini App ESLint: passed;
  - Next.js production export/build: passed;
  - critical Playwright browser E2E: passed.

## 2026-09-15 — tanyapi automatic merge gate

- Root cause: PRs could become fully green but stay open indefinitely because no auto-merge mechanism existed.
- Added `.github/workflows/tanyapi-auto-merge.yml`.
- The workflow runs only for non-draft same-repository PRs targeting `tanyapi`.
- It does not checkout PR code while holding write permissions.
- Repository native auto-merge is disabled, so the workflow waits for the exact PR head and every registered PR Actions run to complete successfully, then performs an exact-head squash merge.
- Regression contract added in `tests/test_tanyapi_auto_merge_workflow.py`.
- Because merges performed by `GITHUB_TOKEN` do not reliably fan out normal push-triggered workflows, auto-merge explicitly dispatches `ci.yml` and then `deploy-production-reliable.yml` for the merged `tanyapi` head. Reliable deploy accepts `workflow_dispatch` CI as an exact-SHA gate.

# NEUROMIX — owner-scoped task detail across linked browser and Telegram

Date: 2026-11-20. Branch: \`feature/web-linked-task-detail-20261120\`, derived from read-only history PR #650 (rebased onto merged #650 SHA e835385bbaee19abc240d30c5e2ad1d212742a4f; latest \`tanyapi\` after #650 squash merges). No production changes from this branch.

## Goal

The browser account connected to a real Telegram identity can open an existing generation task by ID, using **the identical native Mini App task detail formatter and protected recipe sanitizer**. No second provider model adapter, no login-token forgery, no legacy wallet cloning and no new paid generation.

## New endpoint

\`GET /mini-app/api/web-auth/task?task_id=<opaque ID>\`:

- Reject missing/oversize task IDs and any unknown query parameters including client-provided account_id and telegram_id.
- Derive account_id and optional verified telegram_id from revocable \`nm_web_session\` via \`resolve_account_actor\`. Return HTTP 401 without session, 404 for a browser-only account without real Telegram link, and 404 for a task belonging to a different verified Telegram account.
- Reuse native \`miniapp._fetch_task_detail(verified_telegram_id, task_id)\` with unchanged SQL \`WHERE telegram_id=?\` owner scope, aliases and existing media formatting.
- Reuse exactly \`trend_task_privacy.sanitize_task_api_payload\`, which redacts curated trend prompts, private source links, reference lists and forbidden repeat actions.
- Before returning anything private, resolve the cookie and verified exact Telegram link a second time. A logout during slow task/media lookup returns 401; an unlink or reassignment returns 403. The response must never contain the previously owner-scoped task on a stale session.
- Only a read-only task object is returned, with \`scope=legacy_telegram\`. No task creation, debit, credit, payment, mutating webhook or file copy.
- Existing native Telegram detail endpoint remains untouched, including repeat personalization and admin-specific UI capabilities. Browser detail does not enable those mutations.

## Validation

TDD: initial test failed HTTP 404 because the route did not exist. Added verified route, owner query, native formatter/sanitizer and revalidation. Isolated backend run: **126 passed, 73 skipped** (includes new owner/foreign/race/private-sanitizer tests plus existing account history, native history, identity and shared accounts). Targeted Ruff, Python compilation and diff checks passed. Before protected branch merge, run full CI including Postgres, browser E2E, production Docker build; verify actual production SHA, anonymous endpoint 401, foreign task 404, linked user own task 200 using only an authorized test account.

## Existing blockers

This completes only a READ-ONLY linked-account projection of native tasks. It does not merge \`web_generation_tasks\` with \`generation_tasks\`, change balances, release Seedance 2.5 independent-browser paid generation, or replace WebAccountWorkspace with MiniAppShell. Financial P0 cutover requires writer fences and an audited opening manifest; see existing \`docs/adr/20261106-opening-balance-readiness.md\`. Never enable \`WEB_NATIVE_GENERATION_ENABLED\` / \`WEB_NATIVE_PAYMENTS_ENABLED\` through this PR.

## Rollback

Revert the additive endpoint; no schema or wallet/task data modifications.

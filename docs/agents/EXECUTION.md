# Agent execution ledger

## 2026-09-15 — Payments / Lava reconcile / RenderGrid log noise

### Scope
- Branch: `fix/payment-reconcile-test-log-isolation`
- Base/target: `tanyapi`
- Production branch only; `dev` is out of scope.

### Evidence
- Mini App payment `400` responses were not caused by missing provider support. Compatibility wrappers handle explicit Lava methods, FreeKassa and Robokassa before route registration.
- Repeated Lava `401 Invalid API key` came from legacy pending invoice `e482507d-ef0f-44a5-8eaf-ac73ae74c801`, created 2026-09-02. Current Lava invoices succeed with the active credentials.
- RenderGrid `422/503` lines matched exact mocked exceptions from `tests/test_rendergrid_nanobanana_provider.py`; pytest was able to append those synthetic warnings to runtime `logs/bot.log`.

### Changes
- Validate Lava customer email in Mini App before checkout API submission.
- Keep backend validation and add reason-only telemetry for stale clients.
- Quarantine Lava pending rows older than configured TTL from automatic provider polling without changing their financial status.
- Include quarantined stale count in reconcile telemetry.
- Force pytest file logging off through `tests/conftest.py`.
- Document test/runtime log isolation.

### Verification
- Focused Python: `24 passed` for Lava payment safety + RenderGrid provider regression tests.
- Python compileall: passed.
- Ruff on changed Python: passed.
- Mini App production build / TypeScript: passed.
- Mini App critical Playwright E2E: passed, including no checkout request when Lava email is empty.
- Test worktree produced no runtime log files.

### Remaining release gate
- Open PR to `tanyapi`.
- Require exact-head CI.
- Merge to `tanyapi`.
- Verify exact deployed SHA, backend health, Mini App revision and post-deploy telemetry.

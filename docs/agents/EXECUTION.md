# Agent execution ledger

## 2026-09-15 — Payments / Lava reconcile / RenderGrid log noise

### Scope
- Branch: `fix/payment-reconcile-test-log-isolation`
- Base/target: `tanyapi`
- Production branch only; `dev` is out of scope.

### Evidence
- Mini App payment `400` responses were not caused by missing provider support. Compatibility wrappers handle explicit Lava methods, FreeKassa and Robokassa before route registration.
- Repeated Lava `401 Invalid API key` came from a legacy pending invoice created 2026-09-02. Current Lava invoices succeed with the active credentials.
- RenderGrid `422/503` lines matched exact mocked exceptions from `tests/test_rendergrid_nanobanana_provider.py`; pytest was able to append those synthetic warnings to runtime `logs/bot.log`.

### Changes
- Validate Lava customer email in Mini App before checkout API submission.
- Keep backend validation and add reason-only telemetry for stale clients.
- Quarantine only stale Lava pending rows that return provider HTTP 401/403 under the current credential fingerprint; financial status is not changed, and a credential change makes them eligible for reconciliation again.
- Include quarantined stale count in reconcile telemetry.
- Force pytest file logging off through `tests/conftest.py`.
- Document test/runtime log isolation.

### Verification
- Focused Python: Lava payment safety + RenderGrid provider regression tests are green, including credential-scoped quarantine persistence.
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

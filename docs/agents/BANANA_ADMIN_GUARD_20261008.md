# Banana price admin authorization correction

Baseline: b07ab430de2b354a134ea4ef451be30dfcb2ba8d (tanyapi).

The existing photo-price menu uses admin.is_admin, backed by config.is_admin.
The Banana quality callbacks instead used preset_manager.is_admin. Different
admin sources could reject a legitimate menu administrator or admit a stale
preset-only administrator. Both callbacks now delegate to the installed parent
admin module and fail closed before installation.

No tariff values, price files, role lists, migrations, or provider behavior change.
The existing price-save handler remains unchanged. No production mutation was
performed in this worktree. Higgs tariff investigation is separate and incomplete.

Evidence-first diagnosing-bugs flow: callback regression tests first failed (five
failures), then all five passed with the correction. Tests execute the actual
callback function AST with isolated dependencies, avoiding live configuration.
The suite covers both callbacks, conflicting authorities in both directions, and
fail-closed initialization. It does not replace full bot-router integration or
production verification.

Validation: 11 tests passed across test_banana_admin_authorization.py,
test_banana_resolution_pricing_contract.py and test_deploy_runtime_pricing_contract.py;
py_compile and git diff --check passed. System pytest emits two pre-existing
unknown asyncio configuration option warnings.

Release: hand off this isolated change for combined review/CI on tanyapi. Preserve
production price.json, including previously configured Seedance prices. Verify
the exact deployed SHA and existing authorized administrator's Banana menu after
release without changing prices. No live admin identity was required for tests.

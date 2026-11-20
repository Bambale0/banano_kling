# NEUROMIX native/browser shared model catalog — read-only release

Date: 2026-11-20. Branch \`feature/shared-model-catalog-readonly-20261120\`, base \`tanyapi\` SHA \`6d021656e280b7313c2d23a5c60e5a35db05b2a2\`. This is an isolated low-risk cross-platform increment, not the full Draft #646.

## Root cause

Telegram's native Mini App bootstrap historically assembled its own list of 10 image + 14 video entries and applied live configured tariffs. Some public models, notably Seedance 2.5, are injected by runtime wrappers and were invisible to the independent-browser catalog that read only static lists. Duplicating provider adapters and hardcoded model menus would cause drift and expose wrong settings/prices.

## Change

1. Extracted the exact original two native bootstrap model metadata expressions into \`bot/model_catalog_service.py::native_model_metadata\`. The native \`miniapp_bootstrap\` now calls it; the producer still uses \`miniapp.IMAGE_MODELS\`, \`VIDEO_MODELS\`, \`_runtime_image_model_metadata\`, per-user \`creator_tariff_display\`, \`preset_manager\` and original controlled \`kling4_public_enabled/catalog_entry\` callables. Existing public Seedance 2.5 bootstrap wrapper is untouched. No new provider implementation.
2. \`public_browser_catalog\` projects the **same** native model metadata through a strict allowlist of public capability fields, removes price/cost/quality_costs and account-specific data, and includes only *actually installed* public Seedance 2.5 extension via \`generation._seedance_25_public_release_installed\` + \`seedance_25_public_release._public_model_meta\`. Kling 4.0 is listed only when the existing public flag and validated retail config allow it.
3. \`GET /mini-app/api/web-auth/catalog\` requires a valid non-revoked \`nm_web_session\`, returns \`catalog_scope=read_only\`, \`web_generate_enabled=false\` and \`Cache-Control: no-store\`. Anonymous/revoked cookie returns 401. Native/Telegram auth is not changed.
4. Browser-only sessions do not use a synthetic Telegram ID, do not gain admin pricing, and do not obtain a charge action from this endpoint. A model listed as available in Telegram is **not** necessarily available for paid standalone-browser execution.

## Tests and compatibility

Test \`tests/test_unified_public_model_catalog.py\` verifies exact native model IDs, complete original price+option payload equivalence, creator tariff handoff, public installed Seedance 2.5 limits/options, Kling4 public rollout exclusion/inclusion, no public pricing leakage and authenticated/revoked HTTP catalog. Existing native Mini App bootstrap query budget, regression safety, Kling4 public release, web_auth identity/contract and launch revision suites included in isolated backend run.

Initial RED failed on NotImplementedError; separate existing regression caught Kling4 monkeypatch compatibility and was fixed by injecting existing public flag/catalog entry into the extracted builder without changing native behavior. Focused run: 78 passed. Ruff targeted/py_compile/diff check passed. Full GitHub CI gates still required before release. No live provider charge, DB migration, payment or production feature flag changed.

## Remaining P0/P1 blockers

Read-only catalogue parity does **not** resolve the split between old \`users.credits\`/legacy generation tasks and new \`shared_wallets\`/web tasks, nor the separate WebAccountWorkspace versus Telegram's MiniAppShell. Draft #646 remains blocked until exact financial cutover, one owner-scoped paid task lifecycle, linked identity history, optional delivery and paid KIE/Lava/S3 smokes prove correct. Do not automatically merge Draft #646 or enable paid standalone browser generation from this change.

## Release / rollback

Normal GitHub protected \`tanyapi\` PR → full CI → auto-merge → production deploy. Verify exact Git SHA both Docker and public revision.txt, /health 200, anonymous catalog HTTP 401, verified browser test account HTTP 200 with 10 images and native-registered video entries, Seedance25 public metadata when runtime installed, Kling4 rollout status and native Telegram bootstrap unchanged. Revert just this PR if any regression; financial writes are unaffected.

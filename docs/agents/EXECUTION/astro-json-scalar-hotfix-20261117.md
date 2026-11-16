# Natal API HTTP 500 — native JSON scalar normalization

## Verified production failure

- Production endpoint `/mini-app/api/astro/natal/full` emitted HTTP 500 after a successful 12-house Placidus calculation. The astronomy result was valid; serialization failed at `web.json_response` with `TypeError: Object of type bool is not JSON serializable`.
- Actual OpenEphem output on the production host contains `numpy.bool_` aspect `applying` flags and `numpy.float64` degree/orb/speed values, none of which should be trusted as directly JSON-compatible. This is a server serialization defect, not missing GeoNames/IANA/JPL data.
- Root cause traced from Telegram Mini App -> `/mini-app/api/astro/natal/full` -> GeoNames -> DE440 -> chart engine -> `aiohttp.web.json_response`.

## Fix

- Convert only supported scalar NumPy outputs to native JSON primitives at the chart engine boundary. Recursively copy nested dict/list output, reject nonfinite values and unfamiliar types instead of silently fabricating data or emitting `NaN` JSON.
- Apply to natal, inter-chart synastry aspects, transit aspects and solar-return charts. All chart calculations remain deterministic and unchanged; no wallet, pricing, auth or VK change.
- Log `astro_full_natal_complete` only after the response has actually serialized, so production metrics never claim a successful API response after a hidden 500.
- Keep a runnable operator-only `scripts/astro_natal_http_smoke.py` that validates the real full HTTP handler against installed JPL and GeoNames assets using a synthetic in-process test principal. No real Telegram credentials, user records or charges.

## Evidence

- TDD red: NumPy scalar JSON and nonfinite-aspect regressions originally failed (2 failed) for precisely the original defect.
- TDD green: both now pass.
- Offline read-only Docker: 120 affected Astro regressions pass; one known pytest config warning about `asyncio_default_test_loop_scope` remains unrelated.
- Real GeoNames/JPL HTTP smoke: anonymous 401, synthetic admin 200, 12 houses, native bool applying, timezone Europe/Moscow, client coordinates ignored.
- Real DE440 cross-engine verification: `ASTRO_FULL_NATAL_SMOKE_OK` with 12 bodies, ASC/MC, unknown-time fail closed and astronomy-engine comparison.
- Ruff and git diff whitespace validation pass.

## Release gates

A PR must pass protected branch checks before merge to `tanyapi`; production exact merge SHA and healthy container plus original user scenario must then be verified. Never claim production fixed before the actual merged SHA is running. Existing GeoNames asset SHA and S3 configuration are unaffected.

Activated external .agents skills: `systematic-debugging`, `test-driven-development`, `verification-before-completion`. Project `AGENTS.md` takes precedence.
